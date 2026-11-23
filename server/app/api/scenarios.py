"""/api/projects/{name}/scenario — 시나리오 보기 · 그리기(사람이 눌렀을 때만)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import scenarios

router = APIRouter()


class DrawBody(BaseModel):
    model: str = ""


@router.get("/projects/{name}/scenario")
def get(name: str):
    return scenarios.load(name)


@router.post("/projects/{name}/scenario")
async def draw(name: str, body: DrawBody):
    """그리기를 시작만 하고 바로 돌아온다. 끝나면 SSE `scenario.updated`."""
    if scenarios.status(name).get("state") == "running":
        return JSONResponse({"detail": "이미 그리는 중이에요."}, status_code=409)

    async def go():
        try:
            await scenarios.draw(name, model=body.model)
        except Exception:
            pass  # 사유는 job.error 에 남는다

    scenarios.projects.require(name)
    asyncio.create_task(go(), name=f"scenario-{name}")
    return {"started": True}
