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


_account: tuple[float, dict] | None = None


@router.get("/agents/account")
async def account():
    """Claude Code 설치 · 로그인 여부 (처음 실행 안내 · 로그인 만료 안내). 연결만 해서 본다, 5분 캐시.

    이메일은 돌려주지 않는다 — 구독 종류만.
    """
    global _account
    import time

    from ..agents.claude import probe_account
    from .. import registry

    if _account and time.time() - _account[0] < 300:
        return _account[1]
    try:
        got = await probe_account(registry.data_dir())
    except Exception as exc:  # 확인 자체가 실패 — 모른다고 말한다
        got = {"installed": True, "loggedIn": None, "plan": "", "error": str(exc)[:200]}
    _account = (time.time(), got)
    return got


@router.get("/agents/info")
async def info():
    try:
        got = await manager.info()
    except Exception as exc:  # claude가 없거나 로그인 안 됨
        return _bad(exc, 503)
    return {
        **got,
        "modes": [{"id": m, "label": MODE_LABELS[m]} for m in MODES],
        "maxLive": MAX_LIVE,
        # Ultracode — Claude Code 설정 키를 세션마다 --settings로 넘긴다.
        # xhigh를 지원하는 모델에서만 켤 수 있다(문서: model-config)
        "ultracode": {"needsEffort": "xhigh"},
    }


@router.get("/agents/sessions")
def sessions(project: str = "", closed: bool = False):
    """닫은 세션은 `closed=true` 일 때만 같이 준다."""
    return {"sessions": manager.list(project, include_closed=closed), "pending": manager.pending_list(), "live": len(manager.live)}


class RenameBody(BaseModel):
    title: str


@router.put("/agents/sessions/{sid}/title")
def rename(sid: str, body: RenameBody):
    try:
        return manager.rename(sid, body.title)
    except AgentError as exc:
        return _bad(exc)


class CloseBody(BaseModel):
    closed: bool = True


@router.post("/agents/sessions/{sid}/close")
async def close(sid: str, body: CloseBody):
    try:
        return await manager.close(sid, body.closed)
    except AgentError as exc:
        return _bad(exc, 409)


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
    # async 라서 이벤트 루프에서 돈다 — 기다리는 future를 같은 루프에서 푼다
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


#: 채팅에 붙이는 파일 하나의 크기 상한
MAX_ATTACH = 30 * 1024 * 1024


@router.put("/agents/attachments")
async def attach(request: Request, project: str, name: str):
    """채팅 입력창 `+` — 고른 파일을 프로젝트의 `.labremote/attachments/`에 두고 그 경로를 돌려준다.

    연구 폴더의 다른 곳은 건드리지 않는다(lab.remote가 만드는 건 `.labremote/` 뿐). 이름이 겹치면 번호를 붙인다.
    """
    import os
    import re

    from .. import projects

    try:
        root = projects.require(project)
    except Exception as exc:  # 없는 프로젝트
        return JSONResponse({"detail": str(exc)}, status_code=404)
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[\x00-\x1f/\\\\]", "", base)[:120]
    if not base or base in (".", ".."):
        return JSONResponse({"detail": "파일 이름이 올바르지 않아요."}, status_code=400)
    folder = os.path.join(projects.labremote_dir(root), "attachments")
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(base)
    target, n = os.path.join(folder, base), 1
    while os.path.lexists(target):
        n += 1
        target = os.path.join(folder, f"{stem} ({n}){ext}")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_ATTACH:
            return JSONResponse({"detail": "파일이 너무 커요 (30MB까지)."}, status_code=400)
    with open(target, "xb") as fh:
        fh.write(bytes(data))
    return {"path": target, "rel": os.path.relpath(target, root), "size": len(data)}
