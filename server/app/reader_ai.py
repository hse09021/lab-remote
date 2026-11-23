"""리더 AI — 누를 때만 Claude가 그 논문(노트 · PDF)을 읽기 전용으로 읽고 답한다.

세 가지:
- 설명 · 질문 (`explain`): 섹션 · 고른 글 · 질문에 대한 풀이. 대화창에 나온다.
- 번역 (`translate`): 고른 글을 한국어로.
- AI 분석 (`analyze`): 핵심 · 방법 · 결과 · 확인 필요 구절과 참고문헌. 데이터 폴더 `analysis/`에 저장.
  구절 자리는 화면이 PDF 글자 층에서 찾는다(여기서는 쪽 번호와 원문 구절만 받는다).

모두 작업으로 돌리고 화면이 상태를 물어본다. 작업은 메모리에만 둔다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid

from . import papers, registry

__all__ = ["ReaderAiError", "start", "job", "analysis"]

EXPLAIN = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "짧은 제목 (한국어)"},
        "paragraphs": {"type": "array", "items": {"type": "string"}, "description": "풀이 문단 1~4개 (한국어, 해요체)"},
        "questions": {"type": "array", "items": {"type": "string"}, "description": "이어서 물어볼 만한 질문 2~3개 (한국어)"},
    },
    "required": ["title", "paragraphs", "questions"],
}

TRANSLATE = {
    "type": "object",
    "properties": {
        "translation": {"type": "string", "description": "자연스러운 한국어 번역"},
        "note": {"type": "string", "description": "용어 · 맥락 한 줄 (없으면 빈 문자열)"},
    },
    "required": ["translation", "note"],
}

ANALYZE = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "description": "본문에서 그대로 옮긴 구절 8~20개",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["core", "method", "result", "check"]},
                    "quote": {"type": "string", "description": "PDF 본문 그대로 (한 문장 이하, 원문 언어)"},
                    "page": {"type": "integer"},
                    "note": {"type": "string", "description": "왜 중요한지 (한국어, 한 줄)"},
                },
                "required": ["category", "quote", "page", "note"],
            },
        },
        "references": {
            "type": "array",
            "description": "참고문헌 (번호 순, 많으면 앞 40개)",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "title": {"type": "string"},
                    "authors": {"type": "string"},
                    "year": {"type": "integer"},
                    "venue": {"type": "string"},
                    "arxiv": {"type": "string", "description": "arXiv 번호 (참고문헌에 적혀 있을 때만, 없으면 빈 문자열)"},
                    "why": {"type": "string", "description": "본문이 이 논문을 왜 인용했는지 (한국어, 한 줄)"},
                },
                "required": ["n", "title", "authors", "year", "venue", "arxiv", "why"],
            },
        },
    },
    "required": ["highlights", "references"],
}

KINDS = ("section", "selection", "ask", "translate", "analyze")
_jobs: dict[str, dict] = {}


class ReaderAiError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 실패 사유."""


def _paper(pid: str) -> dict:
    for p in papers.scan()["papers"]:
        if p["id"] == pid:
            return p
    raise ReaderAiError(f"없는 논문이에요: {pid}")


def _where(p: dict) -> str:
    pdf = papers.pdf_rel(p["id"])
    return f"논문 노트: {p['path']}\n원문 PDF: {pdf or '없음 (노트만 읽으세요)'}"


def _analysis_path(pid: str) -> str:
    return os.path.join(registry.data_dir(), "analysis", hashlib.sha1(pid.encode()).hexdigest()[:16] + ".json")


def analysis(pid: str) -> dict | None:
    try:
        with open(_analysis_path(pid), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _prompt(kind: str, p: dict, req: dict) -> tuple[str, dict]:
    base = [f"이 폴더는 연구자의 논문 vault예요. 아래 논문을 읽고 답해 주세요. 파일을 고치지 말고 읽기만 하세요.", _where(p), ""]
    text = str(req.get("text") or "")[:3000]
    page = int(req.get("page") or 0)
    hist = [f"[{'질문' if h.get('role') == 'user' else '답'}] {str(h.get('text') or '')[:1200]}" for h in (req.get("history") or [])[-6:] if isinstance(h, dict)]
    if kind == "section":
        base += [f"이 논문의 '{req.get('section') or text}' 부분({page}쪽 근처)을 처음 읽는 사람에게 풀어서 설명해 주세요."]
        return "\n".join(base), EXPLAIN
    if kind == "selection":
        base += [f"{page}쪽의 이 구절을 풀어서 설명해 주세요:", f"\"{text}\""]
        return "\n".join(base), EXPLAIN
    if kind == "ask":
        if text:
            base += [f"맥락 ({page}쪽): \"{text}\""]
        if hist:
            base += ["앞선 대화:", *hist]
        base += [f"질문: {str(req.get('question') or '')[:2000]}", "답은 paragraphs에, 제목은 짧게."]
        return "\n".join(base), EXPLAIN
    if kind == "translate":
        return "\n".join([f"이 구절을 한국어로 번역해 주세요. 필요하면 {_where(p)}를 읽어 맥락을 확인하세요.", f"\"{text}\""]), TRANSLATE
    base += [
        "이 논문 PDF를 읽고:",
        "1. 본문에서 핵심 주장(core) · 방법(method) · 결과(result) · 확인이 필요한 곳(check: 숫자가 안 맞거나 근거가 약한 곳) 구절을 그대로 옮겨 적으세요. 쪽 번호도.",
        "2. 참고문헌 목록을 번호 순으로 적고, 본문이 왜 인용했는지 한 줄씩.",
        "구절은 PDF에 있는 글자 그대로여야 해요 (화면이 그 글자를 찾아 칠해요).",
    ]
    return "\n".join(base), ANALYZE


async def _work(jid: str, kind: str, pid: str, req: dict, model: str, query_fn) -> None:
    rec = _jobs[jid]
    try:
        from .agents.readonly import ReadOnlyError, ask

        p = await asyncio.to_thread(_paper, pid)
        prompt, schema = _prompt(kind, p, req)
        try:
            data, used = await ask(papers.vault_path(), prompt, schema, model=model, max_turns=40, query_fn=query_fn)
        except ReadOnlyError as exc:
            raise ReaderAiError(str(exc)) from None
        if kind == "analyze":
            hl = [h for h in data.get("highlights") or [] if isinstance(h, dict) and h.get("category") in ("core", "method", "result", "check") and str(h.get("quote") or "").strip()]
            refs = [r for r in data.get("references") or [] if isinstance(r, dict) and str(r.get("title") or "").strip()]
            out = {"id": pid, "model": used, "createdAt": time.time(), "highlights": hl[:40], "references": refs[:80]}
            os.makedirs(os.path.dirname(_analysis_path(pid)), exist_ok=True)
            registry.write_json(_analysis_path(pid), out)
            rec.update(state="done", result={"highlights": len(out["highlights"]), "references": len(out["references"])})
        else:
            rec.update(state="done", result=data, model=used)
    except Exception as exc:
        rec.update(state="failed", error=str(exc)[:500])
    finally:
        rec["endedAt"] = time.time()


def start(pid: str, kind: str, req: dict | None = None, *, model: str = "", query_fn=None) -> dict:
    if kind not in KINDS:
        raise ReaderAiError("모르는 요청이에요.")
    _paper(pid)
    req = req or {}
    if kind in ("selection", "translate") and not str(req.get("text") or "").strip():
        raise ReaderAiError("고른 글이 없어요.")
    if kind == "ask" and not str(req.get("question") or "").strip():
        raise ReaderAiError("질문을 적어 주세요.")
    running = [j for j in _jobs.values() if j["state"] == "running"]
    if len(running) >= 3:
        raise ReaderAiError("앞 요청에 답하는 중이에요. 끝나면 다시 해 주세요.")
    if kind == "analyze" and any(j["kind"] == "analyze" and j["paper"] == pid for j in running):
        raise ReaderAiError("이미 분석하는 중이에요.")
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "kind": kind, "paper": pid, "state": "running", "startedAt": time.time(), "result": None, "error": ""}
    for old in sorted(_jobs, key=lambda k: _jobs[k]["startedAt"])[:-40]:
        _jobs.pop(old, None)
    asyncio.get_running_loop().create_task(_work(jid, kind, pid, req, model, query_fn), name=f"reader-ai-{jid}")
    return dict(_jobs[jid])


def job(jid: str) -> dict:
    found = _jobs.get(jid)
    if not found:
        raise ReaderAiError("없는 요청이에요 (서버를 다시 켰으면 사라져요).")
    return dict(found)


def running_analysis(pid: str) -> bool:
    return any(j["kind"] == "analyze" and j["paper"] == pid and j["state"] == "running" for j in _jobs.values())
