"""/api/projects — 목록·등록·해제·고정·설정."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from .. import projects, runs
from ..git import view

router = APIRouter()


class RegisterBody(BaseModel):
    path: str
    name: str = ""


class PinBody(BaseModel):
    pinned: bool


def _runs_line(name: str) -> dict:
    """목록·헤더용 실행 요약 — 실행 중인 것과 마지막 실행."""
    try:
        items = runs.list_runs(name)
    except Exception:
        return {"running": [], "last": None, "total": 0}
    keep = ("id", "name", "state", "stateLabel", "startedAt", "endedAt", "exitCode")
    return {
        "running": [{k: r.get(k) for k in keep} for r in items if r["state"] == "running"],
        "last": {k: items[0].get(k) for k in keep} if items else None,
        "total": len(items),
    }


def _row(p: dict, *, with_git: bool = True) -> dict:
    out = dict(p)
    out["git"] = view.summary(p["root"]) if with_git and p["exists"] else {"state": "missing"}
    out["runs"] = _runs_line(p["name"]) if p["exists"] else {"running": [], "last": None, "total": 0}
    return out


@router.get("/projects")
def list_projects():
    return {"projects": [_row(p) for p in projects.list_projects()]}


@router.post("/projects")
def register(body: RegisterBody):
    made = projects.register(body.path, body.name)
    return _detail(made["name"])


def _detail(name: str) -> dict:
    root = projects.require(name)
    row = next(p for p in projects.list_projects() if p["name"] == name)
    out = _row(row)
    out["settings"] = projects.load_settings(root)
    out["labremote"] = os.path.isdir(projects.labremote_dir(root))
    return out


@router.get("/projects/{name}")
def detail(name: str):
    return _detail(name)


@router.delete("/projects/{name}")
def unregister(name: str, removeLabremote: bool = False):  # noqa: N803 - 화면 쪽 이름
    return projects.unregister(name, remove_labremote=removeLabremote)


@router.put("/projects/{name}/pin")
def pin(name: str, body: PinBody):
    projects.require(name)
    return {"pins": projects.set_pin(name, body.pinned)}


@router.get("/projects/{name}/settings")
def get_settings(name: str):
    return projects.load_settings(projects.require(name))


@router.put("/projects/{name}/settings")
def put_settings(name: str, body: dict):
    return projects.save_settings(projects.require(name), body)
