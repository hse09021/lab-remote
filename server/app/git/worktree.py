"""worktree 만들기 — `<프로젝트>/.labremote/worktrees/<이름>` 에만 만든다(PLAN 4.1).

지우기(정리)는 여기 없다 — 사람이 누를 때만, 뒤 단계에서.
"""

from __future__ import annotations

import os
import re

from .. import paths, projects
from . import ops

__all__ = ["WorktreeError", "add", "slug"]


class WorktreeError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


BRANCH_RE = re.compile(r"\A(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,100}(?<![./])\Z")


def slug(branch: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.split("/")[-1]).strip("-.") or "work"
    return s[:60]


def add(root: str, branch: str) -> dict:
    """새 브랜치로 worktree 를 만든다. 브랜치가 이미 있으면 그 브랜치로."""
    branch = (branch or "").strip()
    if not BRANCH_RE.match(branch) or branch.endswith(".lock"):
        raise WorktreeError(f"브랜치 이름이 올바르지 않아요: {branch!r}")
    if not ops.inside_worktree(root):
        raise WorktreeError("git 저장소가 아니라 worktree 를 만들 수 없어요.")
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
