"""`labremote doctor` — 설치와 설정을 점검한다.

훅은 조용히 안 뜨는 게 제일 위험하다. 그래서 "안 걸려 있다" 를 눈에 보이게 한다.
"""

from __future__ import annotations

import json
import os
import shutil

from . import loop_layout, paths, policy, registry, runstate
from . import policy_defaults as D
from .hooks import check as hooks_check
from .hooks import install

__all__ = ["run", "Check", "permission_mode_check", "project_secrets"]


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_mode(data: dict) -> str:
    """`permissions.defaultMode` (없으면 최상위 `defaultMode`)."""
    perms = data.get("permissions")
    if isinstance(perms, dict) and perms.get("defaultMode"):
        return str(perms["defaultMode"])
    return str(data.get("defaultMode") or "")


def permission_mode_check(root: str, name: str) -> Check:
    """권한 기본 모드가 고정돼 있는가.

    2.1.317 은 **사용자 설정에 defaultMode 가 없으면 `auto`** 로 뜬다
    (실측: `claude --remote-control` 로 새로 띄운 세션이 auto 였다). 그래서
    프로젝트 `.claude/settings.json` 에 박아 두는 게 유일하게 확실한 방법이고,
    프로젝트 설정이 사용자 설정보다 우선한다.
    """
    project_mode = _default_mode(_read_json(policy.claude_settings_path(root)))
    if project_mode:
        ok = project_mode in ("default", "plan")
        return Check(
            ok,
            f"권한 기본 모드 · {name}",
            f"프로젝트 설정 defaultMode={project_mode}",
            hint="default 나 plan 이어야 승인창이 떠요. .claude/settings.json 을 고쳐 주세요.",
        )

    user_mode = _default_mode(_read_json(install.settings_path()))
    if user_mode in ("default", "plan"):
        return Check(
            True,
            f"권한 기본 모드 · {name}",
            f"사용자 설정 defaultMode={user_mode} (프로젝트 설정에도 넣어 두면 더 안전해요)",
        )
    return Check(
        False,
        f"권한 기본 모드 · {name}",
        f"어디에도 없어요 (사용자 설정 {user_mode or '없음'})",
        hint="2.1.317 은 기본이 auto 예요 → labremote policy migrate " + name,
    )


def project_secrets(root: str) -> list[str]:
    """프로젝트 **안**에 있는 비밀 파일. 예시 파일은 뺀다.

    훅은 "대상이 그 파일인 호출" 만 막는다. `grep -r` 처럼 폴더를 훑는 재귀
    읽기는 막을 수 없으므로, 비밀을 프로젝트 밖에 두는 게 1차 방어다.
    """
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for item in files:
            full = os.path.join(base, item)
            rel = os.path.relpath(full, root)
            if paths.match_globs(rel, D.SECRET_EXEMPT) or paths.match_abs_globs(
                full, D.SECRET_EXEMPT
            ):
                continue
            if paths.match_abs_globs(full, D.SECRET_FILES):
                found.append(rel)
    return sorted(found)


class Check(dict):
    def __init__(self, ok: bool, title: str, detail: str = "", hint: str = ""):
        super().__init__(ok=ok, title=title, detail=detail, hint=hint)


def run() -> dict:
    checks: list[Check] = []

    # --- 폴더 구조 ---------------------------------------------------------
    left = loop_layout.pending_keys()
    checks.append(
        Check(
            not left,
            "Loop Engineering 경로",
            "모두 확정됐어요" if not left else f"자리표시가 남아 있어요: {', '.join(left)}",
            hint="docs/Loop*.pdf 를 읽고 app/loop_layout.py 를 채워 주세요.",
        )
    )

    # --- 훅 설치 -----------------------------------------------------------
    state = install.status()
    mode = (state.get("state") or {}).get("mode")
    checks.append(
        Check(
            bool(state["installed"]),
            "훅 등록",
            f"{', '.join(sorted(state['installed'])) or '없음'}" + (f" · {mode} 모드" if mode else ""),
            hint="labremote hooks install --mode enforce",
        )
    )

    # 설치한 뒤에 이벤트가 늘어나면 조용히 빠진다 (UserPromptSubmit 이 그 예).
    if state["installed"]:
        want = install.expected_events(mode or "enforce")
        missing_events = sorted(want - set(state["installed"]))
        checks.append(
            Check(
                not missing_events,
                "훅 이벤트",
                "전부 걸려 있어요" if not missing_events else f"빠진 이벤트: {', '.join(missing_events)}",
                hint="labremote hooks install 을 다시 돌려 주세요. UserPromptSubmit 이 "
                "없으면 거부로 끊긴 턴의 승인 대기 건이 세션 끝까지 남아요.",
            )
        )
    checks.append(
        Check(
            state["wrapperExists"] and os.access(state["wrapper"], os.X_OK),
            "래퍼 파일",
            state["wrapper"],
            hint="labremote hooks install 을 다시 돌려 주세요.",
        )
    )

    interpreter = (state.get("state") or {}).get("python") or ""
    checks.append(
        Check(
            bool(interpreter) and os.access(interpreter, os.X_OK),
            "훅이 쓸 파이썬",
            interpreter or "(모름)",
            hint="인터프리터가 사라지면 실험 프로젝트에서 모든 작업이 막혀요.",
        )
    )

    if mode == "dump":
        checks.append(
            Check(False, "판정 모드", "dump — 받아 적기만 하고 아무것도 막지 않아요",
                  hint="labremote hooks install --mode enforce")
        )

    baked = (state.get("state") or {}).get("roots") or ""
    live = registry.projects_root()
    checks.append(
        Check(
            baked == live if baked else False,
            "프로젝트 루트",
            f"래퍼에 박힌 값 {baked or '(모름)'} · 지금 설정 {live}",
            hint="다르면 labremote hooks install 을 다시 돌려 주세요.",
        )
    )

    # --- 프로젝트 ----------------------------------------------------------
    projects = registry.load()
    checks.append(
        Check(bool(projects), "등록된 프로젝트", f"{len(projects)}개", hint="labremote init-project <이름>")
    )
    for root, name in sorted(projects.items()):
        checks.append(Check(os.path.isdir(root), f"프로젝트 폴더 · {name}", root))
        try:
            pol = policy.load(name)
            checks.append(
                Check(True, f"정책 · {name}", f"{pol.effective_mode()} · {pol.path}")
            )
            locked = [k for k in ("outside", "stop", "prev") if pol.resolve(k) != "block"]
            checks.append(
                Check(not locked, f"잠금 · {name}", "3개 다 잠겨 있어요" if not locked else f"풀린 항목: {locked}")
            )
            # extraWritableRoots 가 보호 목록을 건드리는가 (판정은 보호 목록이
            # 이기지만, 조용히 두면 "열었다" 고 오해한다)
            conflicts = policy.conflicting_writable_roots(pol)
            checks.append(
                Check(
                    not conflicts,
                    f"쓰기 예외 · {name}",
                    "겹치는 곳이 없어요" if not conflicts else f"보호 경로와 겹쳐요: {conflicts}",
                    hint="이 경로는 어떤 설정에서도 막혀요. extraWritableRoots 에서 빼 주세요.",
                )
            )
        except policy.PolicyError as exc:
            hint = ""
            if "판이 맞지 않아요" in str(exc):
                hint = f"labremote policy migrate {name}"
            checks.append(Check(False, f"정책 · {name}", str(exc), hint=hint))

        checks.append(permission_mode_check(root, name))

        secrets = project_secrets(root)
        checks.append(
            Check(
                not secrets,
                f"비밀 파일 위치 · {name}",
                "프로젝트 안에 없어요" if not secrets else f"프로젝트 안에 있어요: {secrets}",
                hint="재귀 읽기(grep -r)는 훅이 못 막아요. "
                f"~/.config/labremote/{name}.env 로 옮기고 .env.example 만 남겨 주세요.",
            )
        )

        state_now = runstate.load(name)
        detail = "안 돌고 있어요" if not state_now.running else f"{state_now.experiment_id} 실행 중"
        if state_now.started:
            detail += f" · 시작된 실험 {len(state_now.started)}개"
        checks.append(Check(not state_now.stale, f"실행 상태 · {name}", detail,
                            hint="running 인데 프로세스가 없어요. labremote run-state --idle 로 정리해 주세요."))
        checks.append(
            Check(
                paths.rel_or_none(root, paths.real(registry.policy_path(name))) is None,
                f"정책 위치 · {name}",
                "프로젝트 밖에 있어요 (AI 가 못 고쳐요)",
            )
        )

    # 자가 점검이 중간에 죽으면 임시 프로젝트 폴더가 남는다
    leftovers = hooks_check.scratch_leftovers()
    checks.append(
        Check(
            not leftovers,
            "자가 점검 잔해",
            "없어요" if not leftovers else f"{len(leftovers)}개 남아 있어요: {leftovers}",
            hint="labremote hooks check 를 다시 돌리면 스스로 지워요 (rm -rf 해도 돼요).",
        )
    )

    # --- 바깥 도구 ----------------------------------------------------------
    checks.append(Check(bool(shutil.which("git")), "git", shutil.which("git") or "없음"))
    data_dir = registry.data_dir()
    checks.append(
        Check(
            os.path.isdir(data_dir),
            "런타임 폴더",
            data_dir,
            hint="server/data/ 는 gitignore 라 백업되지 않아요. ②에서 붙입니다.",
        )
    )

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "limitations": install.limitations(),
    }


def render(report: dict) -> str:
    lines = []
    for check in report["checks"]:
        mark = "✔" if check["ok"] else "✘"
        line = f"{mark} {check['title']:<24} {check['detail']}"
        lines.append(line)
        if not check["ok"] and check["hint"]:
            lines.append(f"    → {check['hint']}")
    lines.append("")
    for note in report["limitations"]:
        lines.append(f"· {note}")
    return "\n".join(lines)
