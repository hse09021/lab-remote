"""/api/projects/{name}/files — 프로젝트 안 파일.

`tree` 는 기준 폴더(프로젝트 루트나 그 안의 worktree, 루트 기준 상대 경로),
`path` 는 그 기준 폴더 안의 상대 경로다.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import files, projects
from ..git import view

router = APIRouter()


class TextBody(BaseModel):
    tree: str = ""
    path: str
    text: str


class MakeBody(BaseModel):
    tree: str = ""
    path: str
    kind: str


class MoveBody(BaseModel):
    tree: str = ""
    src: str = Field(alias="from")
    dst: str = Field(alias="to")


class DeleteBody(BaseModel):
    tree: str = ""
    path: str
    confirm: str


def _base(name: str, tree: str) -> tuple[str, str]:
    root = projects.require(name)
    return root, files.base_of(root, tree)


@router.get("/projects/{name}/files")
def list_dir(name: str, tree: str = "", path: str = ""):
    _root, base = _base(name, tree)
    return files.list_dir(base, path, git_marks=view.marks_for(base, path))


@router.get("/projects/{name}/files/content")
def read(name: str, path: str, tree: str = ""):
    _root, base = _base(name, tree)
    return files.read_text(base, path)


@router.put("/projects/{name}/files/content")
def write(name: str, body: TextBody):
    _root, base = _base(name, body.tree)
    return files.write_text(base, body.path, body.text)


@router.post("/projects/{name}/files")
def make(name: str, body: MakeBody):
    _root, base = _base(name, body.tree)
    return files.make(base, body.path, body.kind)


@router.post("/projects/{name}/files/move")
def move(name: str, body: MoveBody):
    root, base = _base(name, body.tree)
    return files.move(root, base, body.src, body.dst)


@router.post("/projects/{name}/files/delete")
def delete(name: str, body: DeleteBody):
    root, base = _base(name, body.tree)
    return files.delete(root, base, body.path, confirm=body.confirm)


@router.get("/projects/{name}/files/download")
def download(name: str, path: str, tree: str = ""):
    _root, base = _base(name, tree)
    target = files.download_path(base, path)
    return FileResponse(target, filename=os.path.basename(target))


@router.put("/projects/{name}/files/upload")
async def upload(name: str, path: str, request: Request, tree: str = "", overwrite: bool = False):
    """본문 그대로가 파일 내용이다 (multipart 를 쓰지 않는다)."""
    _root, base = _base(name, tree)
    target = files.upload_target(base, path, overwrite=overwrite)
    fd, tmp = tempfile.mkstemp(prefix=".labremote-up-", dir=os.path.dirname(target))
    size = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                fh.write(chunk)
                size += len(chunk)
        # 기다리는 사이 누가 같은 이름을 만들었으면 덮지 않는다
        if not overwrite and os.path.lexists(target):
            raise files.FileRefused(f"이미 있어요: {os.path.basename(target)}")
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"path": files.rel_of(base, target), "size": size}
