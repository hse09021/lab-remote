"""Claude Bash 샌드박스가 유닉스 소켓 필터를 **실제로 붙였나** — 사람이 확인하는 절차.

탐침(소켓에 붙어 보기)을 돌리지 않는다. 대신 **무해한 `ls` 하나**를 실제
런처(같은 경계 플래그)로 띄우고 `--debug-file` 에 남는 샌드박스 런타임의
줄을 읽는다. 2.1.318 번들에서 확인한 줄(`docs/operations.md`):

    [Sandbox Linux] Applying seccomp filter for Unix socket blocking
    [Sandbox Linux] Wrapped command with bwrap (… seccomp(unix-block) restrictions)

꺼진 경우:

    [Sandbox Linux] apply-seccomp binary not available - unix socket blocking disabled. …
    [Sandbox Linux] Skipping seccomp filter - allowAllUnixSockets is enabled

**결과를 보고 스위치를 켜는 건 사람이다** (`labremote policy-socket-verified`).
이 모듈은 판정만 돌려준다.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime

from .. import registry

__all__ = ["PROMPT", "ON_MARKS", "OFF_MARKS", "parse", "log_dir", "run"]

PROMPT = (
    "점검용이에요. Bash 로 `ls` 를 **한 번만** 실행하고 끝내 주세요. "
    "파일을 읽거나 다른 명령을 실행하지 마세요."
)

#: 필터가 붙었다는 근거
ON_MARKS = (
    "Applying seccomp filter for Unix socket blocking",
    "seccomp(unix-block)",
)

#: 필터가 빠졌다는 근거 (하나라도 있으면 ✘)
OFF_MARKS = (
    "unix socket blocking disabled",
    "Skipping seccomp filter - allowAllUnixSockets is enabled",
)

#: `(network, filesystem, seccomp(unix-block) restrictions)` — 안에 괄호가 또
#: 있어서 `[^)]*` 로는 `seccomp(unix-block` 에서 끊긴다. `restrictions)` 까지 잡는다.
WRAPPED_RE = re.compile(r"\[Sandbox Linux\] Wrapped command with bwrap \((.*?) restrictions\)")


def parse(text: str) -> dict:
    """디버그 로그 → `{"verdict": "on"|"off"|"unknown", "wrapped", "lines", "reason"}`.

    **모르면 모른다고 한다.** 근거 줄이 하나도 없으면 `unknown` 이다 —
    Bash 가 안 돌았거나 로그 수준이 달라서일 수 있다.
    """
    text = text or ""
    lines = [ln.strip() for ln in text.splitlines()]
    keep = [
        ln for ln in lines
        if "[Sandbox Linux]" in ln or "[SeccompFilter]" in ln
    ]
    wrapped = [m.group(1) for m in WRAPPED_RE.finditer(text)]
    off = [ln for ln in keep if any(mark in ln for mark in OFF_MARKS)]
    on = [ln for ln in keep if any(mark in ln for mark in ON_MARKS)]
    if off:
        verdict, reason = "off", "필터가 빠졌다는 줄이 있어요"
    elif wrapped and all("seccomp(unix-block)" in w for w in wrapped):
        verdict, reason = "on", "모든 Bash 명령이 seccomp(unix-block) 으로 감싸졌어요"
    elif wrapped:
        verdict, reason = "off", "seccomp(unix-block) 없이 감싼 명령이 있어요"
    elif on:
        verdict, reason = "unknown", "필터 적용 줄은 있는데 감싼 명령 줄이 없어요 (Bash 가 안 돌았을 수 있어요)"
    else:
        verdict, reason = "unknown", "샌드박스 줄을 하나도 못 찾았어요"
    return {"verdict": verdict, "wrapped": wrapped, "lines": keep[:40], "reason": reason}


def log_dir() -> str:
    """`server/data/sandbox-check/` — AI 가 못 쓰는 곳."""
    return os.path.join(registry.data_dir(), "sandbox-check")


def run(project: str, *, runner=None, preset: str | None = None) -> dict:
    """한 번 띄워서 판정한다. `runner` 는 시험용."""
    from .. import policy as policy_mod
    from . import launch as launch_mod
    from . import session as session_mod

    root = registry.root_of(project)
    if not root:
        return {"verdict": "unknown", "reason": f"등록된 프로젝트가 아니에요: {project}", "log": ""}
    os.makedirs(log_dir(), mode=0o700, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = os.path.join(log_dir(), f"{project}-{stamp}.log")

    if preset is None:
        try:
            preset = policy_mod.load(project).effective_mode() or "full"
        except Exception:
            preset = "full"
    agent = launch_mod.AgentRun(
        project=project, root=root, prompt=PROMPT,
        session_id=session_mod.new_id(), headless=True,
        extra_flags=["--debug-file", log],
    )
    made = launch_mod.plan(agent, preset=preset)
    if runner is None:
        done = subprocess.run(
            made["argv"], cwd=made["cwd"], env=made["env"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
        )
        exit_code = done.returncode
    else:
        exit_code = runner(made)
    try:
        os.chmod(log, 0o600)
        with open(log, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return {"verdict": "unknown", "reason": f"디버그 로그를 못 읽었어요: {exc}", "log": log, "exitCode": exit_code}
    got = parse(text)
    got.update({"log": log, "exitCode": exit_code, "sessionId": agent.session_id})
    return got
