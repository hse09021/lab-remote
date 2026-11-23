"""/api/papers — vault 를 읽어 라이브러리 목록 · 지식그래프 (리더 · AI 요약은 아직 mock)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .. import annotations, library, papers, summaries

router = APIRouter()


class VaultBody(BaseModel):
    path: str = ""


class StatusBody(BaseModel):
    status: str


class ArxivBody(BaseModel):
    url: str


class TrashBody(BaseModel):
    on: bool = True


class CollectionBody(BaseModel):
    name: str


class MembersBody(BaseModel):
    ids: list[str]
    on: bool = True


class ReferenceBody(BaseModel):
    title: str
    authors: str = ""
    year: str = ""
    venue: str = ""
    arxiv: str = ""


class AskBody(BaseModel):
    question: str
    history: list[dict] = []
    model: str = ""


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/papers")
def list_papers(trash: bool = False):
    return papers.list_papers(trash=trash)


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


@router.get("/papers/notes")
def notes():
    """논문 노트 본문 (앞쪽 메타 제외, 읽기만) — 요약이 없을 때 보여 줄 것."""
    out = {}
    for p in papers.scan()["papers"]:
        try:
            out[p["id"]] = papers.body_of(p["id"])
        except papers.PapersError:
            continue
    return out


@router.get("/papers/summaries")
def get_summaries():
    """AI 요약 (만든 것만) — 정리된 보기."""
    return {pid: {k: v for k, v in s.items() if not k.startswith("_")} for pid, s in summaries.load_all().items()}


@router.get("/papers/summary-md")
def summary_md():
    """vault 의 요약 파일 MD (만든 것만)."""
    out = {}
    for pid in summaries.load_all():
        md = summaries.markdown_of(pid)
        if md is not None:
            out[pid] = md
    return out


class SummaryMdBody(BaseModel):
    markdown: str | None = None


@router.put("/papers/{pid}/summary-md")
def put_summary_md(pid: str, body: SummaryMdBody):
    try:
        return summaries.save_markdown(pid, body.markdown)
    except summaries.SummaryError as exc:
        return _bad(exc)


class SummaryStart(BaseModel):
    model: str = ""


@router.post("/papers/{pid}/summary")
async def start_summary(pid: str, body: SummaryStart):
    """요약 만들기 — 시작만 하고 돌아온다. 화면이 GET 으로 물어본다."""
    try:
        return summaries.start(pid, model=body.model)
    except summaries.SummaryError as exc:
        return _bad(exc, 409)


@router.get("/papers/{pid}/summary")
def summary_job(pid: str):
    return summaries.job(pid)


@router.post("/papers/ask")
async def ask(body: AskBody):
    """라이브러리에 묻기 — 시작만 하고 바로 돌아온다. 화면이 GET /papers/ask/{id} 로 물어본다."""
    try:
        return library.start(body.question, body.history, model=body.model)
    except library.AskError as exc:
        return _bad(exc, 409 if "답하는 중" in str(exc) else 400)


@router.get("/papers/ask/{jid}")
def ask_job(jid: str):
    try:
        return library.job(jid)
    except library.AskError as exc:
        return _bad(exc, 404)


@router.get("/papers/collections")
def get_collections():
    return papers.collections()


@router.post("/papers/collections")
def new_collection(body: CollectionBody):
    try:
        return papers.add_collection(body.name)
    except papers.PapersError as exc:
        return _bad(exc)


@router.delete("/papers/collections/{name}")
def delete_collection(name: str):
    try:
        return papers.remove_collection(name)
    except papers.PapersError as exc:
        return _bad(exc, 404)


@router.post("/papers/collections/{name}/papers")
def collection_members(name: str, body: MembersBody):
    try:
        return papers.set_in_collection(name, body.ids, body.on)
    except papers.PapersError as exc:
        return _bad(exc)


@router.get("/papers/bibtex")
def get_bibtex(ids: str = ""):
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(papers.bibtex([i for i in ids.split(",") if i]), media_type="text/plain; charset=utf-8")


@router.post("/papers/reference")
def add_reference(body: ReferenceBody):
    """인용 카드의 "보관하기" — arXiv 번호가 있으면 arXiv 로, 없으면 메타만으로 노트를 만든다."""
    try:
        if body.arxiv.strip():
            return papers.add_arxiv(body.arxiv)
        return papers.add_reference(body.title, body.authors, body.year, body.venue)
    except papers.PapersError as exc:
        return _bad(exc)


@router.get("/papers/{pid}/annotations")
def get_annotations(pid: str):
    return annotations.list_for(pid)


@router.post("/papers/{pid}/annotations")
def add_annotation(pid: str, body: dict):
    try:
        return annotations.add(pid, body)
    except (annotations.AnnotationError, ValueError, TypeError) as exc:
        return _bad(exc)


class AnnotationText(BaseModel):
    text: str


@router.patch("/papers/{pid}/annotations/{aid}")
def edit_annotation(pid: str, aid: str, body: AnnotationText):
    try:
        return annotations.update(pid, aid, body.text)
    except annotations.AnnotationError as exc:
        return _bad(exc, 404)


@router.delete("/papers/{pid}/annotations/{aid}")
def delete_annotation(pid: str, aid: str):
    try:
        annotations.remove(pid, aid)
        return {"ok": True}
    except annotations.AnnotationError as exc:
        return _bad(exc, 404)


@router.put("/papers/{pid}/trash")
def trash(pid: str, body: TrashBody):
    try:
        return papers.set_trashed(pid, body.on)
    except papers.PapersError as exc:
        return _bad(exc, 404)


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
