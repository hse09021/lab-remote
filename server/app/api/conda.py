"""/api/conda — 환경 · 패키지 · 미리 보기 · 설치 · 만들기 · 삭제."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .. import conda

router = APIRouter()


class ChangeBody(BaseModel):
    tool: str
    action: str
    packages: list[dict]
    dry: bool = True


class CreateBody(BaseModel):
    name: str
    python: str = "3.11"
    clone: str = ""


class DeleteBody(BaseModel):
    confirm: str


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/conda/envs")
def envs():
    try:
        return {"envs": conda.list_envs()}
    except conda.CondaError as exc:
        return _bad(exc, 503)


@router.get("/conda/envs/{name}")
def detail(name: str):
    try:
        return conda.env_detail(name)
    except conda.CondaError as exc:
        return _bad(exc, 404)


@router.post("/conda/envs/{name}/changes")
def change(name: str, body: ChangeBody):
    """dry=true 면 바뀌는 것만 계산. 실제 설치는 dry=false 로 한 번 더."""
    try:
        return conda.start_job("change", name, tool=body.tool, action=body.action, packages=body.packages, dry=body.dry)
    except conda.CondaError as exc:
        return _bad(exc)


@router.post("/conda/envs")
def create(body: CreateBody):
    try:
        return conda.start_job("create", body.name, python=body.python, clone=body.clone)
    except conda.CondaError as exc:
        return _bad(exc)


@router.post("/conda/envs/{name}/delete")
def delete(name: str, body: DeleteBody):
    try:
        return conda.start_job("delete", name, confirm=body.confirm)
    except conda.CondaError as exc:
        return _bad(exc)


@router.get("/conda/envs/{name}/export")
def export(name: str):
    try:
        return PlainTextResponse(
            conda.export_yml(name),
            headers={"Content-Disposition": f'attachment; filename="{name}-environment.yml"'},
        )
    except conda.CondaError as exc:
        return _bad(exc)


@router.get("/conda/jobs/{jid}")
def job(jid: str):
    try:
        return conda.job(jid)
    except conda.CondaError as exc:
        return _bad(exc, 404)
