"""`labremote doctor` — 설치와 설정을 점검한다.

훅은 조용히 안 뜨는 게 제일 위험하다. 그래서 "안 걸려 있다" 를 눈에 보이게 한다.
"""

from __future__ import annotations

import json
import os
import shutil

from . import loop_layout, paths, policy, registry, runstate
from .hooks import install

__all__ = ["run", "Check"]


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
        except policy.PolicyError as exc:
            checks.append(Check(False, f"정책 · {name}", str(exc)))

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
