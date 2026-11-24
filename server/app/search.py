"""파일 내용 검색 — IDE의 검색 패널.

git 저장소면 `git grep`(gitignore를 따른다, 빠르다), 아니면 파이썬으로 걷는다
(큰 데이터 폴더·.git·node_modules는 건너뛴다). 결과 수에 상한을 둔다.
"""

from __future__ import annotations

import os

from . import paths
from .git import ops
from .git.guard import GitRefused

__all__ = ["search", "MAX_RESULTS"]

MAX_RESULTS = 500
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".labremote", ".venv", "venv", "runs", "data", "wandb", "outputs"}
MAX_FILE = 1024 * 1024


def _git(base: str, q: str, case: bool) -> list[dict] | None:
    args = ["grep", "-n", "-I", "--fixed-strings", "--no-color", "--untracked"]
    if not case:
        args.append("-i")
    args += ["-e", q, "--", "."]
    try:
        if not ops.inside_worktree(base):
            return None
        out = ops.run(base, args, check=False)
    except (GitRefused, ops.GitError):
        return None
    hits = []
    for line in out.splitlines():
        path, _, rest = line.partition(":")
        num, _, text = rest.partition(":")
        if not num.isdigit():
            continue
        hits.append({"path": path, "line": int(num), "text": text[:300]})
        if len(hits) >= MAX_RESULTS:
            break
    return hits


def _walk(base: str, q: str, case: bool) -> list[dict]:
    needle = q if case else q.lower()
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            try:
                if os.path.islink(full) or os.path.getsize(full) > MAX_FILE:
                    continue
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if b"\x00" in data[:4096]:
                continue
            text = data.decode("utf-8", "replace")
            for i, line in enumerate(text.splitlines(), 1):
                if needle in (line if case else line.lower()):
                    hits.append({"path": os.path.relpath(full, base).replace(os.sep, "/"), "line": i, "text": line[:300]})
                    if len(hits) >= MAX_RESULTS:
                        return hits
    return hits


def search(base: str, q: str, *, case: bool = False) -> dict:
    q = (q or "").strip()
    if len(q) < 2:
        return {"results": [], "truncated": False, "via": ""}
    base = paths.real(base)
    hits = _git(base, q, case)
    via = "git grep"
    if hits is None:
        hits, via = _walk(base, q, case), "파일 직접 탐색"
    return {"results": hits, "truncated": len(hits) >= MAX_RESULTS, "via": via}
