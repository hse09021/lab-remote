"""/api/papers — vault 를 읽어 라이브러리 목록 · 지식그래프 (리더 · AI 요약은 아직 mock)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .. import papers

router = APIRouter()


class VaultBody(BaseModel):
    path: str = ""


class StatusBody(BaseModel):
    status: str


class ArxivBody(BaseModel):
    url: str


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/papers")
def list_papers():
    return papers.list_papers()


@router.get("/papers/vault")
def vault():
    return papers.info()


@router.put("/papers/vault")
def set_vault(body: VaultBody):
    try:
        return papers.set_vault(body.path)
    except papers.PapersError as exc:
        return _bad(exc)


@router.get("/papers/graph")
def graph():
    return papers.graph()


@router.get("/papers/summary-md")
def summaries():
    """논문 노트 본문을 요약 MD 로 (읽기만)."""
    out = {}
    for p in papers.scan()["papers"]:
        try:
            out[p["id"]] = papers.body_of(p["id"])
        except papers.PapersError:
            continue
    return out


@router.post("/papers/arxiv")
def add_arxiv(body: ArxivBody):
    """arXiv 링크로 논문 추가 — vault 에 새 노트(+ PDF)만 쓴다."""
    try:
        return papers.add_arxiv(body.url)
    except papers.PapersError as exc:
        return _bad(exc)


@router.put("/papers/pdf")
async def add_pdf(request: Request, name: str = ""):
    """PDF 올리기 — 본문 그대로가 파일 내용이다."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > papers.MAX_PDF:
            return _bad(papers.PapersError("PDF 가 너무 커요 (100MB 까지)."))
    try:
        return await asyncio.to_thread(papers.add_pdf, name, bytes(data))
    except papers.PapersError as exc:
        return _bad(exc)


@router.get("/papers/{pid}/pdf")
def get_pdf(pid: str):
    try:
        return FileResponse(papers.pdf_of(pid), media_type="application/pdf")
    except papers.PapersError as exc:
        return _bad(exc, 404)


@router.patch("/papers/{pid}")
def set_status(pid: str, body: StatusBody):
    try:
        return papers.set_status(pid, body.status)
    except papers.PapersError as exc:
        return _bad(exc)
