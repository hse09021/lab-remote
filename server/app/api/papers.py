"""/api/papers — vault 를 읽어 라이브러리 목록 · 지식그래프 (리더 · AI 요약은 아직 mock)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import papers

router = APIRouter()


class VaultBody(BaseModel):
    path: str = ""


class StatusBody(BaseModel):
    status: str


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


@router.patch("/papers/{pid}")
def set_status(pid: str, body: StatusBody):
    try:
        return papers.set_status(pid, body.status)
    except papers.PapersError as exc:
        return _bad(exc)
