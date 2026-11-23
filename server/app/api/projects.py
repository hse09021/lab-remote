"""/api/projects — 목록·등록·해제·고정·설정."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from .. import projects
from ..git import view

router = APIRouter()


class RegisterBody(BaseModel):
    path: str
    name: str = ""


class PinBody(BaseModel):
    pinned: bool


def _row(p: dict, *, with_git: bool = True) -> dict:
    out = dict(p)
    out["git"] = view.summary(p["root"]) if with_git and p["exists"] else {"state": "missing"}
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
