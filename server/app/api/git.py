"""/api/projects/{name}/git — 읽기만 (상태·diff·브랜치·worktree)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import files, projects
from ..git import ops, view

router = APIRouter()


def _base(name: str, tree: str) -> str:
    return files.base_of(projects.require(name), tree)


@router.get("/projects/{name}/git/status")
def status(name: str, tree: str = ""):
    return view.status(_base(name, tree))


@router.get("/projects/{name}/git/diff")
def diff(name: str, tree: str = "", path: str = "", staged: bool = False):
    base = _base(name, tree)
    if path:
        files.resolve(base, path, must_exist=False)  # 경로 탈출 검사만
    return view.diff(base, path, staged=staged)


@router.get("/projects/{name}/git/branches")
def branches(name: str):
    root = projects.require(name)
    info = view.summary(root)
    if info.get("state") != "ok":
        return info
    return {"state": "ok", "current": info["branch"], "branches": ops.branches(root)}


@router.get("/projects/{name}/git/worktrees")
def worktrees(name: str):
    return view.worktrees(projects.require(name))
