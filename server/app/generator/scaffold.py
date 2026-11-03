"""프로젝트 생성 — 검사 -> 임시 폴더에 쓰기 -> git -> 최종 경로로 이동.

롤백이 간단하도록 **부모 폴더의 임시 디렉터리에 전부 만들고** git init·커밋까지
끝낸 다음 `os.rename` 으로 옮긴다. 중간에 실패하면 임시 폴더 하나만 지우면
되고, 최종 경로에는 아무것도 생긴 적이 없다.
"""

from __future__ import annotations

import os
import shutil
import stat

from .. import loop_layout as L
from .. import paths, policy, registry, runstate
from . import conda, gitops, render, tree
from .plan import PlannedFile, build_plan
from .spec import ProjectSpec

__all__ = ["ScaffoldError", "target_path", "preflight", "create_project", "dry_run"]

#: lab-remote 저장소. 실험 프로젝트는 반드시 이 밖에 만든다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ScaffoldError(RuntimeError):
    pass


def repo_root() -> str:
    return paths.real(os.path.dirname(_REPO_ROOT))


def target_path(name: str) -> str:
    return os.path.join(registry.projects_root(), registry.valid_name(name))


def preflight(spec: ProjectSpec, if_exists: str = "fail") -> str:
    """만들기 전에 막을 것들. 통과하면 최종 경로를 돌려준다."""
    registry.valid_name(spec.name)
    target = target_path(spec.name)

    if paths.is_inside(repo_root(), paths.real(target)):
        raise ScaffoldError(
            f"실험 프로젝트는 이 저장소 밖에 만들어야 해요: {target} · "
            "LAB_PROJECTS_DIR 을 저장소 밖으로 바꿔 주세요."
        )

    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise ScaffoldError(f"부모 폴더가 없어요: {parent} · 먼저 만들어 주세요.")

    worktree = gitops.inside_worktree(parent)
    if worktree:
        raise ScaffoldError(
            f"이미 git 저장소 안이에요: {worktree} · 1 프로젝트 1 저장소라서 여기엔 못 만들어요."
        )

    if os.path.exists(target):
        if if_exists != "update":
            marker = os.path.join(target, L.LOOP_LAYOUT["state"])
            kind = "이미 lab.remote 프로젝트예요" if os.path.exists(marker) else "이미 있는 폴더예요"
            raise ScaffoldError(f"{target} 은 {kind}. --if-exists update 를 쓰거나 다른 이름을 골라 주세요.")
    elif if_exists == "update":
        raise ScaffoldError(f"{target} 이 없어서 update 할 게 없어요.")

    return target


def _render_file(item: PlannedFile, spec: ProjectSpec, plan: list[PlannedFile]) -> str:
    if not item.template:
        return ""
    values = spec.values()
    if item.path == L.LOOP_LAYOUT["file_directory"]:
        values = {**values, "tree": tree.render_tree(spec.name, plan), "roles": tree.render_roles(plan)}
    return render.render(item.template, values)


def _write_all(root: str, spec: ProjectSpec, plan: list[PlannedFile], *, only_missing: bool = False) -> list[str]:
    written: list[str] = []
    for item in plan:
        path = os.path.join(root, item.path)
        if only_missing and os.path.exists(path):
            continue
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        body = _render_file(item, spec, plan)
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)
        if item.owner == "lock":
            # 실수로 지나가는 걸 줄이는 표시. 진짜 강제는 훅이 한다.
            os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR)
        written.append(item.path)
    return written


def dry_run(spec: ProjectSpec) -> dict:
    """만들 파일 목록. 웹 UI 의 "생성될 파일 목록 미리 보기" 가 이걸 쓴다."""
    plan = build_plan(spec)
    return {
        "name": spec.name,
        "target": target_path(spec.name),
        "files": [
            {"path": item.path, "owner": item.owner, "tracked": item.tracked, "role": item.role}
            for item in plan
        ],
        "count": len(plan),
        "tree": tree.render_tree(spec.name, plan),
    }


def create_project(spec: ProjectSpec, *, if_exists: str = "fail", create_env: bool = False) -> dict:
    target = preflight(spec, if_exists)
    plan = build_plan(spec)

    if if_exists == "update" and os.path.exists(target):
        return _update(target, spec, plan)

    parent = os.path.dirname(target)
    staging = os.path.join(parent, f".{spec.name}.labremote-tmp-{os.getpid()}")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    try:
        written = _write_all(staging, spec, plan)
        commit = gitops.init_and_commit(staging)
        if spec.remote:
            gitops.add_remote(staging, spec.remote)
        os.rename(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # 서버 쪽 등록. 이게 빠지면 훅이 이 프로젝트를 모르고 지나간다.
    root = registry.register(target, spec.name)
    pol = policy.ensure(spec.name, root)
    if spec.mode != pol.data.get("defaultMode"):
        pol.data["defaultMode"] = spec.mode
        policy.save(pol)
    runstate.set_idle(spec.name)

    env = {"ok": True, "skipped": True, "reason": "environment.yml 만 만들었어요"}
    if create_env:
        env = conda.create_env(target, L.LOOP_LAYOUT["environment"], spec.env_name)

    return {
        "target": target,
        "commit": commit,
        "files": written,
        "count": len(written),
        "policy": pol.path,
        "mode": spec.mode,
        "env": env,
        "remote": spec.remote or None,
    }


def _update(target: str, spec: ProjectSpec, plan: list[PlannedFile]) -> dict:
    """없는 파일만 채우고, `owner == gen` 인 것만 다시 쓴다."""
    backup = os.path.join(target, ".labremote", "backup", spec.created_at.replace(":", ""))
    regen = [item for item in plan if item.owner == "gen"]
    changed: list[str] = []

    for item in regen:
        path = os.path.join(target, item.path)
        if os.path.exists(path):
            dst = os.path.join(backup, item.path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)
            changed.append(item.path)

    added = _write_all(target, spec, plan, only_missing=True)
    _write_all(target, spec, regen)
    return {"target": target, "added": added, "refreshed": [i.path for i in regen], "backup": backup if changed else None}
