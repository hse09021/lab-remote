"""git init 과 첫 커밋.

push 와 `gh repo create` 는 ①에서 하지 않는다 — 인증·네트워크가 섞이면
롤백이 지저분해진다. `--remote` 는 origin 만 달아 둔다.
"""

from __future__ import annotations

import os
import subprocess

__all__ = ["GitError", "inside_worktree", "init_and_commit", "add_remote", "tracked_files"]

COMMIT_MESSAGE = "chore: Loop Engineering 프로젝트 뼈대 생성 (lab.remote 생성기)"


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} 가 실패했어요: {result.stderr.strip()}")
    return result.stdout


def inside_worktree(path: str) -> str | None:
    """이 경로가 이미 다른 git 저장소 안이면 그 루트."""
    probe = path
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent


def init_and_commit(root: str) -> str:
    _run(["init", "-b", "main"], root)
    _run(["add", "-A"], root)
    _run(["-c", "user.name=lab.remote", "-c", "user.email=labremote@localhost",
          "commit", "-m", COMMIT_MESSAGE], root)
    dirty = _run(["status", "--porcelain"], root).strip()
    if dirty:
        raise GitError(f"커밋 뒤에도 정리되지 않은 변경이 있어요:\n{dirty}")
    return _run(["rev-parse", "HEAD"], root).strip()


def add_remote(root: str, url: str) -> None:
    _run(["remote", "add", "origin", url], root)


def tracked_files(root: str) -> list[str]:
    return [line for line in _run(["ls-files"], root).splitlines() if line]
