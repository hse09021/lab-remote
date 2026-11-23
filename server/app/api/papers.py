"""/api/papers — vault를 읽어 라이브러리 목록 · 지식그래프 · PDF · AI 요약 · 리더 AI."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .. import annotations, library, paperhtml, papers, reader_ai, summaries

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
    """vault의 요약 파일 MD (만든 것만)."""
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
    """요약 만들기 — 시작만 하고 돌아온다. 화면이 GET으로 물어본다."""
    try:
        return summaries.start(pid, model=body.model)
    except summaries.SummaryError as exc:
        return _bad(exc, 409)


@router.get("/papers/{pid}/summary")
def summary_job(pid: str):
    return summaries.job(pid)


class ReaderAiBody(BaseModel):
    kind: str
    text: str = ""
    section: str = ""
    page: int = 0
    question: str = ""
    history: list[dict] = []
    model: str = ""


@router.post("/papers/{pid}/ai")
async def reader_ai_start(pid: str, body: ReaderAiBody):
    """리더 AI (설명 · 질문 · 번역 · 분석) — 시작만 하고 돌아온다. GET /papers/ai/{id}로 물어본다."""
    try:
        return reader_ai.start(pid, body.kind, body.model_dump(), model=body.model)
    except reader_ai.ReaderAiError as exc:
        return _bad(exc, 409 if "중이에요" in str(exc) else 400)


@router.get("/papers/ai/{jid}")
def reader_ai_job(jid: str):
    try:
        return reader_ai.job(jid)
    except reader_ai.ReaderAiError as exc:
        return _bad(exc, 404)


@router.get("/papers/{pid}/analysis")
def reader_analysis(pid: str):
    """AI 분석 결과 (하이라이트 구절 · 참고문헌). 없으면 null."""
    return {"analysis": reader_ai.analysis(pid), "running": reader_ai.running_analysis(pid)}


@router.post("/papers/ask")
async def ask(body: AskBody):
    """라이브러리에 묻기 — 시작만 하고 바로 돌아온다. 화면이 GET /papers/ask/{id}로 물어본다."""
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
    """인용 카드의 "보관하기" — arXiv 번호가 있으면 arXiv로, 없으면 메타만으로 노트를 만든다."""
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
    """arXiv 링크로 논문 추가 — vault에 새 노트(+ PDF)만 쓴다. arXiv HTML은 뒤에서 데이터 폴더로 받는다."""
    try:
        made = papers.add_arxiv(body.url)
    except papers.PapersError as exc:
        return _bad(exc)
    try:
        if paperhtml.state(made["id"]) in ("missing", "error"):
            made["html"] = paperhtml.start(made["id"])
    except papers.PapersError:
        pass
    return made


# 받은 본문을 주소로 바로 열어도 페이지로 그려지지 않게 — 화면은 글로 받아 DOMPurify로 걸러요
_NO_RUN = {"Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'", "X-Content-Type-Options": "nosniff"}


@router.get("/papers/{pid}/html")
def get_html(pid: str):
    """arXiv HTML 본문 (데이터 폴더에 받아 둔 것)"""
    try:
        return PlainTextResponse(paperhtml.html_of(pid), headers=_NO_RUN)
    except papers.PapersError as exc:
        return _bad(exc, 404)


@router.post("/papers/{pid}/html")
def fetch_html(pid: str):
    """arXiv HTML 받기 (뒤에서) — 예전에 넣은 arXiv 논문을 리더에서 처음 열 때"""
    try:
        return {"state": paperhtml.start(pid)}
    except papers.PapersError as exc:
        return _bad(exc, 404)


@router.get("/papers/{pid}/html/state")
def html_state(pid: str):
    try:
        paperhtml.arxiv_of(pid)
    except papers.PapersError as exc:
        return _bad(exc, 404)
    return {"state": paperhtml.state(pid)}


@router.get("/papers/{pid}/html/assets/{name}")
def html_asset(pid: str, name: str):
    try:
        return FileResponse(paperhtml.asset_of(pid, name), headers={**_NO_RUN, "Cache-Control": "max-age=86400"})
    except papers.PapersError as exc:
        return _bad(exc, 404)


@router.put("/papers/pdf")
async def add_pdf(request: Request, name: str = ""):
    """PDF 올리기 — 본문 그대로가 파일 내용이다."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > papers.MAX_PDF:
            return _bad(papers.PapersError("PDF가 너무 커요 (100MB까지)."))
    try:
        return await asyncio.to_thread(papers.add_pdf, name, bytes(data))
    except papers.PapersError as exc:
        return _bad(exc)


class TargetBody(BaseModel):
    target: str
    index: int = 0


@router.put("/papers/{pid}/discrepancy")
def choose_target(pid: str, body: TargetBody):
    """재현 목표 고르기 (AI 분석이 찾은 수치 불일치)"""
    try:
        return reader_ai.choose_target(pid, body.index, body.target)
    except reader_ai.ReaderAiError as exc:
        return _bad(exc)


@router.post("/papers/{pid}/pdf/fetch")
async def fetch_pdf(pid: str):
    """노트에 PDF가 없는 arXiv 논문 — arXiv에서 받아 데이터 폴더에 (vault는 그대로)"""
    try:
        return await asyncio.to_thread(papers.fetch_pdf, pid)
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
