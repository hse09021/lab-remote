"""conda 환경.

생성기는 `environment.yml` 만 쓴다. 실제 생성은 `--create-env` 를 줄 때만 하고,
실패해도 프로젝트는 그대로 두고 경고만 남긴다 — 환경 생성 실패로 폴더 구조까지
롤백하면 손해가 크다.
"""

from __future__ import annotations

import os
import shutil
import subprocess

__all__ = ["conda_binary", "env_exists", "create_env"]

TIMEOUT_SEC = 900


def conda_binary() -> str | None:
    found = shutil.which("conda")
    if found:
        return found
    guess = os.path.join(os.path.expanduser("~"), "miniconda3", "bin", "conda")
    return guess if os.path.exists(guess) else None


def env_exists(name: str) -> bool:
    binary = conda_binary()
    if not binary:
        return False
    try:
        out = subprocess.run([binary, "env", "list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[:1] == [name] for line in out.stdout.splitlines() if line.strip())


def create_env(root: str, env_file: str, name: str) -> dict:
    """돌려 보고 결과를 알려 준다. 던지지 않는다."""
    binary = conda_binary()
    if not binary:
        return {"ok": False, "reason": "conda 를 찾지 못했어요"}
    if env_exists(name):
        return {"ok": True, "reason": f"환경 {name} 이 이미 있어요", "skipped": True}
    try:
        result = subprocess.run(
            [binary, "env", "create", "-f", os.path.join(root, env_file)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "reason": result.stderr.strip()[-400:]}
    return {"ok": True, "reason": f"환경 {name} 을 만들었어요"}
