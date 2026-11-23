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
