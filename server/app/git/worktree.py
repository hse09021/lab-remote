"""worktree 만들기 — `<프로젝트>/.labremote/worktrees/<이름>`에만 만든다(PLAN 4.1).

정리(`remove`)는 사람이 누르고 한 번 더 확인했을 때만 부른다. `--force`는 쓰지 않는다 —
커밋 안 한 변경이 있으면 git이 거절하고 그 문구를 그대로 보여 준다. 브랜치는 지우지 않는다.
"""

from __future__ import annotations

import os
import re

from .. import paths, projects
from . import ops

__all__ = ["WorktreeError", "add", "remove", "slug"]


class WorktreeError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


BRANCH_RE = re.compile(r"\A(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,100}(?<![./])\Z")


def slug(branch: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.split("/")[-1]).strip("-.") or "work"
    return s[:60]


def add(root: str, branch: str) -> dict:
    """새 브랜치로 worktree를 만든다. 브랜치가 이미 있으면 그 브랜치로."""
    branch = (branch or "").strip()
    if not BRANCH_RE.match(branch) or branch.endswith(".lock"):
        raise WorktreeError(f"브랜치 이름이 올바르지 않아요: {branch!r}")
    if not ops.inside_worktree(root):
        raise WorktreeError("git 저장소가 아니라 worktree를 만들 수 없어요.")
    projects.ensure_labremote(root)
    base = os.path.join(projects.labremote_dir(root), "worktrees")
    os.makedirs(base, exist_ok=True)
    name = slug(branch)
    target = os.path.join(base, name)
    n = 2
    while os.path.exists(target):
        target = os.path.join(base, f"{name}-{n}")
        n += 1
    try:
        ops.run(root, ["check-ref-format", "--branch", branch])
        if branch in ops.branches(root):
            ops.run(root, ["worktree", "add", "--", target, branch])
        else:
            ops.run(root, ["worktree", "add", "-b", branch, "--", target])
    except ops.GitError as exc:
        raise WorktreeError(str(exc)) from None
    real = paths.real(target)
    return {"path": real, "rel": paths.rel_or_none(paths.real(root), real), "branch": branch}


def remove(root: str, rel: str) -> dict:
    """`.labremote/worktrees/` 안의 worktree 하나를 정리한다(브랜치는 남긴다)."""
    from .. import files

    try:
        target = files.base_of(root, rel)
    except files.FileRefused as exc:
        raise WorktreeError(str(exc)) from None
    base = paths.real(os.path.join(projects.labremote_dir(root), "worktrees"))
    if not paths.is_inside(base, target) or target == base:
        raise WorktreeError("lab.remote가 만든 worktree(.labremote/worktrees/)만 정리해요.")
    from .. import runs

    if any(paths.is_inside(target, d) for d in runs.busy_dirs(root)):
        raise WorktreeError("이 worktree에서 학습이 실행 중이에요. 끝난 뒤에 정리해 주세요.")
    try:
        ops.run(root, ["worktree", "remove", "--", target])
    except ops.GitError as exc:
        raise WorktreeError(f"정리하지 못했어요. 커밋하지 않은 변경이 있다면 먼저 커밋하거나 되돌려 주세요. ({str(exc)[:200]})") from None
    return {"removed": paths.rel_or_none(paths.real(root), target)}
