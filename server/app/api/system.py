"""/api/system — System 화면과 헤더의 GPU 한 줄."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import remote, system

router = APIRouter()


@router.get("/system")
def overview(request: Request):
    return system.overview(port=request.app.state.port)


@router.get("/system/dirs")
def dirs(path: str = "", hidden: bool = False):
    """폴더 등록의 "찾아보기" — 홈 폴더 안의 하위 폴더 목록 (읽기만)"""
    from .. import projects

    try:
        return projects.browse(path, hidden=hidden)
    except projects.ProjectError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


class MakeDirBody(BaseModel):
    parent: str = "~"
    name: str
    gitInit: bool = False


@router.post("/system/dirs")
def make_dir(body: MakeDirBody):
    """찾아보기 › 새 폴더 — 홈 폴더 안에 빈 폴더 (등록은 따로)"""
    from .. import projects

    try:
        return projects.make_dir(body.parent, body.name, git_init=body.gitInit)
    except projects.ProjectError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@router.get("/system/gpu")
def gpu():
    return system.gpu_summary()


@router.get("/system/resources")
def resources():
    """Dashboard 자원 칸 — 화면을 보는 동안만 5초마다 불린다(systemctl은 안 부른다)."""
    return {"gpu": system.gpu_summary(), "host": system.host_summary()}


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


class RemoteBody(BaseModel):
    url: str = ""


@router.get("/system/remote")
def get_remote():
    return remote.info()


@router.put("/system/remote")
def put_remote(body: RemoteBody):
    """바깥 주소(터널로 전달한 주소). 비우면 지운다."""
    try:
        return remote.set_url(body.url) if body.url.strip() else remote.clear()
    except remote.RemoteError as exc:
        return _bad(exc)


@router.post("/system/autostart/restart")
def restart_session():
    """"세션 다시 켜기" — 답을 먼저 돌려주고 서비스가 다시 뜬다(이 서버도 그 안이면 잠깐 끊겨요)."""
    from ..service import autostart

    from ..service import units

    try:
        return autostart.restart(now=not units.inside())
    except autostart.AutostartError as exc:
        return _bad(exc, 409)


class UninstallBody(BaseModel):
    confirm: str = ""


@router.post("/system/autostart/uninstall")
def uninstall_autostart(body: UninstallBody):
    """"자동 시작 끄기…" — 화면에서 한 번 더 확인한 뒤에만. 켜기는 터미널(CLI)에서만 해요."""
    from ..service import autostart

    if body.confirm != "끄기":
        return _bad(ValueError("확인 문구가 일치하지 않아요."))
    from ..service import units

    inside = units.inside()
    try:
        steps = autostart.uninstall(stop=not inside)
    except autostart.AutostartError as exc:
        return _bad(exc, 409)
    if inside:
        autostart.later(["stop", "--no-block"])
    return {"steps": steps, "stopsSelf": inside}
