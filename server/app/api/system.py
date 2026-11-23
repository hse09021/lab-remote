"""/api/system — System 화면과 헤더의 GPU 한 줄."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import system

router = APIRouter()


@router.get("/system")
def overview(request: Request):
    return system.overview(port=request.app.state.port)


@router.get("/system/gpu")
def gpu():
    return system.gpu_summary()


@router.get("/system/resources")
def resources():
    """Dashboard 자원 칸 — 화면을 보는 동안만 5초마다 불린다(systemctl 은 안 부른다)."""
    return {"gpu": system.gpu_summary(), "host": system.host_summary()}
