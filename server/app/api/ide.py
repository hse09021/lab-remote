"""IDE — 검색 · 커밋 · main 에 합치기 · 터미널(WebSocket ↔ tmux)."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import files, projects, search, terminals
from ..git import actions

router = APIRouter()


class CommitBody(BaseModel):
    tree: str = ""
    message: str
    paths: list[str] | None = None


class MergeBody(BaseModel):
    branch: str


class TermBody(BaseModel):
    tree: str = ""


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/projects/{name}/search")
def find(name: str, q: str = "", tree: str = "", case: bool = False):
    base = files.base_of(projects.require(name), tree)
    return search.search(base, q, case=case)


@router.get("/projects/{name}/git/caps")
def caps(name: str):
    projects.require(name)
    return {"pr": actions.gh_available()}


@router.post("/projects/{name}/git/commit")
def commit(name: str, body: CommitBody):
    base = files.base_of(projects.require(name), body.tree)
    try:
        return actions.commit(base, body.message, body.paths)
    except actions.ActionError as exc:
        return _bad(exc)


@router.post("/projects/{name}/git/merge")
def merge(name: str, body: MergeBody):
    try:
        return actions.merge_to_main(projects.require(name), body.branch)
    except actions.ActionError as exc:
        return _bad(exc, 409)


@router.get("/projects/{name}/terminals")
def list_terminals(name: str):
    return {"terminals": terminals.list_sessions(name)}


@router.post("/projects/{name}/terminals")
def new_terminal(name: str, body: TermBody):
    try:
        return terminals.create(name, body.tree)
    except terminals.TerminalError as exc:
        return _bad(exc)


@router.delete("/projects/{name}/terminals/{term}")
def kill_terminal(name: str, term: str):
    try:
        terminals.kill(name, term)
    except terminals.TerminalError as exc:
        return _bad(exc)
    return {"ok": True}


def _ws_allowed(ws: WebSocket) -> bool:
    """🔑 WebSocket 은 HTTP 미들웨어를 안 지난다 — Host 와 Origin 을 여기서 본다.

    다른 사이트의 페이지도 브라우저로 이 주소에 WebSocket 을 열 수 있다
    (cross-site WebSocket hijacking). 브라우저는 Origin 을 반드시 붙이므로,
    Origin 이 없거나 허용 목록 밖이면 거절한다.
    """
    from ..main import _hostname, allowed_hosts

    hosts = allowed_hosts()
    if _hostname(ws.headers.get("host", "")) not in hosts:
        return False
    origin = ws.headers.get("origin") or ""
    return bool(origin) and _hostname(urlsplit(origin).netloc) in hosts


@router.websocket("/terminals/ws")
async def terminal_ws(
    ws: WebSocket, project: str, name: str = "", run: str = "", write: bool = False, cols: int = 120, rows: int = 32
):
    """메시지: 화면 → `{"type":"input","data":..}` · `{"type":"resize","cols","rows"}`,
    서버 → 터미널 출력(바이트)."""
    if not _ws_allowed(ws):
        await ws.close(code=4403)
        return
    try:
        argv = terminals.attach_argv(project, name=name, run=run, write=write)
    except (terminals.TerminalError, projects.ProjectError) as exc:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        await ws.close(code=4400)
        return
    except Exception as exc:  # 없는 실행 등
        await ws.accept()
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        await ws.close(code=4400)
        return
    await ws.accept()
    # 화면이 잰 크기로 시작한다 — 큰 크기로 그렸다 줄이면 tmux 가 남긴 줄이 깨져 보인다
    term = terminals.Pty(argv, cols=cols, rows=rows)

    async def send(chunk: bytes) -> None:
        await ws.send_bytes(chunk)

    pump = asyncio.create_task(term.pump(send))
    try:
        while True:
            recv = asyncio.create_task(ws.receive_text())
            done, _ = await asyncio.wait({recv, pump}, return_when=asyncio.FIRST_COMPLETED)
            if pump in done:
                recv.cancel()
                break
            msg = json.loads(recv.result())
            if msg.get("type") == "input":
                term.write(str(msg.get("data", "")).encode("utf-8"))
            elif msg.get("type") == "resize":
                term.resize(int(msg.get("cols", 120)), int(msg.get("rows", 32)))
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        pump.cancel()
        term.close()
        try:
            await ws.close()
        except RuntimeError:
            pass


class WorktreeBody(BaseModel):
    branch: str = ""
    rel: str = ""


@router.post("/projects/{name}/git/worktrees")
def add_worktree(name: str, body: WorktreeBody):
    from ..git import worktree

    try:
        return worktree.add(projects.require(name), body.branch)
    except worktree.WorktreeError as exc:
        return _bad(exc)


@router.post("/projects/{name}/git/worktrees/remove")
def remove_worktree(name: str, body: WorktreeBody):
    """정리 — 화면이 한 번 더 확인한 뒤에만 부른다. 브랜치는 남긴다."""
    from ..agents.manager import manager
    from ..git import worktree

    root = projects.require(name)
    rel = (body.rel or "").strip().strip("/")
    if any(x.get("tree") == rel and (x.get("busy") or x.get("connected")) for x in manager.list(name)):
        return _bad(worktree.WorktreeError("이 worktree 에서 에이전트 세션이 돌고 있어요. 세션을 멈춘 뒤에 정리해 주세요."), 409)
    try:
        return worktree.remove(root, rel)
    except worktree.WorktreeError as exc:
        return _bad(exc, 409)
