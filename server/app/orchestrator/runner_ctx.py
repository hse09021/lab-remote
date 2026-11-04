"""루프가 쓰는 주변 장치 묶음.

Claude 를 띄우는 것과 학습을 띄우는 것을 **주입받는다.** 시험에서는 가짜를
끼워 Claude 없이 루프를 완주시킨다 (계획의 결정: "가짜 학습으로 루프부터").
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from ..agent import result as result_mod
from ..runner import cache as cache_mod
from ..runner import process as process_mod

__all__ = ["LoopCtx", "real_claude", "real_launcher", "real_waiter"]


def real_claude(made: dict) -> dict:
    """진짜 `claude -p`. **stdin 을 반드시 닫는다** — 안 그러면 출력 앞에
    `Warning: no stdin data received` 가 붙는다 (실측)."""
    try:
        done = subprocess.run(
            made["argv"],
            cwd=made["cwd"],
            env=made["env"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=made.get("timeout", 60 * 60),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return result_mod.parse("", exit_code=1) | {"raw": f"{type(exc).__name__}: {exc}"}
    return result_mod.parse(done.stdout + done.stderr, exit_code=done.returncode)


def real_launcher(spec):
    return process_mod.launch(spec)


def real_waiter(launched, spec):
    return process_mod.wait(
        launched, timeout_sec=spec.timeout_sec, grace_sec=spec.grace_sec
    )


@dataclass
class LoopCtx:
    """루프 한 번에 필요한 것 전부."""

    project: str
    root: str
    preset: str = "full"
    permission_mode: str = "default"
    context: str = ""
    cache_dir: str = ""
    #: `claude -p` 를 띄우는 것 (시험에서는 가짜)
    runner: object = field(default=real_claude)
    #: 학습을 띄우는 것
    launcher: object = field(default=real_launcher)
    #: 학습을 기다리는 것
    waiter: object = field(default=real_waiter)

    def __post_init__(self):
        if not self.cache_dir:
            self.cache_dir = cache_mod.cache_dir()
