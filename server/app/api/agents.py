"""/api/agents · /api/approvals · /api/events — 에이전트 세션과 실시간 이벤트.

이름은 에이전트 공통(Claude 전용으로 짓지 않는다).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..agents.base import MODE_LABELS, MODES
from ..agents.manager import MAX_LIVE, AgentError, manager
from ..events import bus

router = APIRouter()


class CreateBody(BaseModel):
    project: str
    text: str
    title: str = ""
    tree: str = ""
    newBranch: str = ""
    mode: str = "manual"
    model: str = ""
    effort: str = ""
    ultracode: bool = False


class SendBody(BaseModel):
    text: str


class ConfigBody(BaseModel):
    mode: str | None = None
    model: str | None = None
    effort: str | None = None
    ultracode: bool | None = None


class AnswerBody(BaseModel):
    choice: str  # allow · allowSession · deny · answer
    reason: str = ""
    via: str = ""
    #: choice=answer — {질문 글: label 또는 [label, ...]}
    answers: dict[str, str | list[str]] | None = None
    response: str = ""


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/agents/info")
async def info():
    try:
        got = await manager.info()
    except Exception as exc:  # claude 가 없거나 로그인 안 됨
        return _bad(exc, 503)
    return {
        **got,
        "modes": [{"id": m, "label": MODE_LABELS[m]} for m in MODES],
        "maxLive": MAX_LIVE,
        # Ultracode — Claude Code 설정 키를 세션마다 --settings 로 넘긴다.
        # xhigh 를 지원하는 모델에서만 켤 수 있다(문서: model-config)
        "ultracode": {"needsEffort": "xhigh"},
    }


@router.get("/agents/sessions")
def sessions(project: str = ""):
    return {"sessions": manager.list(project), "pending": manager.pending_list(), "live": len(manager.live)}


@router.post("/agents/sessions")
async def create(body: CreateBody):
    try:
        return await manager.create(
            body.project,
            text=body.text,
            title=body.title,
            tree=body.tree,
            new_branch=body.newBranch,
            mode=body.mode,
            model=body.model,
            effort=body.effort,
            ultracode=body.ultracode,
        )
    except AgentError as exc:
        return _bad(exc)


@router.get("/agents/sessions/{sid}")
def get(sid: str):
    try:
        return manager.get(sid)
    except AgentError as exc:
        return _bad(exc, 404)


@router.post("/agents/sessions/{sid}/messages")
async def send(sid: str, body: SendBody):
    try:
        return await manager.send(sid, body.text)
    except AgentError as exc:
        return _bad(exc)


@router.post("/agents/sessions/{sid}/interrupt")
async def interrupt(sid: str):
    try:
        return await manager.interrupt(sid)
    except AgentError as exc:
        return _bad(exc)


@router.put("/agents/sessions/{sid}/config")
async def configure(sid: str, body: ConfigBody):
    try:
        return await manager.configure(sid, mode=body.mode, model=body.model, effort=body.effort, ultracode=body.ultracode)
    except AgentError as exc:
        return _bad(exc)


@router.post("/agents/sessions/{sid}/disconnect")
async def disconnect(sid: str):
    await manager.disconnect(sid)
    return {"ok": True}


@router.get("/approvals")
def approvals():
    return {"pending": manager.pending_list()}


@router.post("/approvals/{aid}")
async def answer(aid: str, body: AnswerBody):
    # async 라서 이벤트 루프에서 돈다 — 기다리는 future 를 같은 루프에서 푼다
    try:
        return manager.answer(aid, body.choice, reason=body.reason, via=body.via, answers=body.answers, response=body.response)
    except AgentError as exc:
        return _bad(exc, 409)


@router.get("/events")
async def events(request: Request):
    """SSE. 화면이 열어 두면 세션·승인·알림 이벤트가 흘러온다."""
    queue = bus.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 프록시가 연결을 끊지 않게
                    continue
                yield bus.format(item)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
