"""git 저수준 — **로컬 브랜치만.**

`push`·`merge`·PR 은 ② 에서 만들지 않는다(결정: 로컬 브랜치만). `worktree` 도
일부러 안 만든다 — 작업 트리 루트가 바뀌면 `registry.lookup` 이 깨져 훅이 안 뜬다.

> ⚠ **git 명령은 오케스트레이터가 직접 실행하므로 훅을 거치지 않는다.**
> 그래서 `commit` 의 대상 경로를 코드가 화이트리스트로 지정한다 — 자유
> `git add -A` 는 만들지 않는다. 이 비대칭은 의도된 것이다.
"""

from __future__ import annotations

import os
import subprocess

from .. import paths

__all__ = [
    "GitError",
    "run",
    "inside_worktree",
    "current_branch",
    "branches",
    "create_branch",
    "switch",
    "commit",
    "status_porcelain",
    "diff_name_only",
    "log",
    "head_sha",
]

TIMEOUT_SEC = 60


class GitError(RuntimeError):
    """git 이 실패했을 때. 메시지에 stderr 를 그대로 싣는다."""


def run(root: str, args: list[str], *, check: bool = True) -> str:
    """`git -C <root> <args>`. 실패하면 `GitError`."""
    try:
        done = subprocess.run(
            ["git", "-C", paths.real(root), *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git 을 띄우지 못했어요: {exc}") from None
    if check and done.returncode != 0:
        raise GitError(
            f"git {' '.join(args[:2])} 가 실패했어요 (종료코드 {done.returncode}): "
            + (done.stderr or done.stdout or "").strip()[:400]
        )
    return done.stdout


def inside_worktree(root: str) -> bool:
    try:
        return run(root, ["rev-parse", "--is-inside-work-tree"]).strip() == "true"
    except GitError:
        return False


def current_branch(root: str) -> str:
    return run(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def head_sha(root: str, short: bool = True) -> str:
    args = ["rev-parse", "--short" if short else "--verify", "HEAD"]
    try:
        return run(root, args).strip()
    except GitError:
        return ""


def branches(root: str) -> list[str]:
    out = run(root, ["branch", "--format=%(refname:short)"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def create_branch(root: str, name: str, *, switch_to: bool = True) -> str:
    """브랜치를 만든다. 이미 있으면 그대로 두고 (요청하면) 옮겨 간다."""
    if name in branches(root):
        if switch_to:
            switch(root, name)
        return name
    run(root, ["switch", "-c", name] if switch_to else ["branch", name])
    return name


def status_porcelain(root: str, paths_only: list[str] | None = None) -> list[str]:
    args = ["status", "--porcelain"]
    if paths_only:
        args += ["--", *paths_only]
    return [line for line in run(root, args).splitlines() if line.strip()]


def switch(root: str, name: str, *, retries: int = 1) -> dict:
    """브랜치를 옮긴다. **강제 전환(`-f`)은 하지 않는다.**

    훅이 계속 쓰는 파일(`Approval_log.csv` 등) 때문에 실패할 수 있다. 한 번만
    다시 해 보고, 그래도 안 되면 그대로 둔다 — 강제로 밀면 그 기록이 사라진다.
    """
    last = ""
    for attempt in range(max(1, retries + 1)):
        try:
            run(root, ["switch", name])
            return {"ok": True, "branch": name, "attempts": attempt + 1}
        except GitError as exc:
            last = str(exc)
    return {"ok": False, "branch": current_branch(root), "error": last}


def commit(root: str, message: str, paths_list: list[str]) -> dict:
    """**지정한 경로만** 담아 커밋한다. 자유 `add -A` 는 만들지 않는다.

    바뀐 게 없으면 커밋하지 않고 `{"committed": False}` 를 돌려준다.
    """
    if not paths_list:
        raise GitError("커밋할 경로를 지정해 주세요 (자유 add 는 안 만들어요).")
    existing = [p for p in paths_list if os.path.exists(os.path.join(paths.real(root), p))]
    if not existing:
        return {"committed": False, "reason": "그 경로가 아직 없어요", "paths": []}
    run(root, ["add", "--", *existing])
    staged = [
        line
        for line in run(root, ["diff", "--cached", "--name-only", "--", *existing]).splitlines()
        if line.strip()
    ]
    if not staged:
        return {"committed": False, "reason": "바뀐 게 없어요", "paths": []}
    # **담긴 파일만** 넘긴다. 빈 폴더를 pathspec 으로 주면 git 이 거절한다.
    run(root, ["commit", "-m", message, "--", *staged])
    return {"committed": True, "sha": head_sha(root), "paths": staged}


def diff_name_only(root: str, ref: str = "HEAD") -> list[str]:
    return [line for line in run(root, ["diff", "--name-only", ref]).splitlines() if line]


def log(root: str, count: int = 10) -> list[dict]:
    out = run(root, ["log", f"-{int(count)}", "--format=%h%x1f%an%x1f%ad%x1f%s", "--date=iso"])
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append({"sha": parts[0], "author": parts[1], "at": parts[2], "subject": parts[3]})
    return rows
