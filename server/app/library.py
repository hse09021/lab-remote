"""라이브러리에 묻기 — vault를 **읽기만** 해서 답한다 (2026-11-24 결정).

- 사람이 보내기를 눌렀을 때만 돈다. 에이전트를 vault 폴더에서 계획 모드로, 도구는 읽기만
  (`Read` · `Glob` · `Grep`) 열고, 정해진 JSON 모양(답 + 근거 논문)으로 답하게 한다.
  Scenario와 같은 방식이다. 파일을 고치거나 명령을 돌리지 못한다.
- 답은 오래 걸릴 수 있어서 작업으로 돌리고 화면은 상태를 물어본다. 작업은 메모리에만 둔다
  (대화를 저장하지 않는다). 한 번에 하나만.
- 근거는 vault에 실제로 있는 논문만 남긴다 (지어낸 이름은 버린다).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from . import papers

__all__ = ["AskError", "start", "job", "SCHEMA"]

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "질문에 대한 답 (한국어, 해요체). vault에서 찾은 내용만"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper": {"type": "string", "description": "근거 논문 노트의 파일 이름(확장자 없이, Papers/ 아래)"},
                    "why": {"type": "string", "description": "이 논문에서 무엇을 근거로 썼는지 (한국어, 짧게)"},
                },
                "required": ["paper", "why"],
            },
        },
    },
    "required": ["answer", "sources"],
}

READ_TOOLS = ["Read", "Glob", "Grep"]
MAX_TURNS = 30
MAX_QUESTION = 2000
MAX_HISTORY = 6

_jobs: dict[str, dict] = {}


class AskError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def _prompt(question: str, history: list[dict], listing: list[dict]) -> str:
    lines = [
        "이 폴더는 연구자의 논문 vault(Obsidian)예요. Papers/*.md가 논문 노트(앞쪽 메타 + 초록 · 메모),",
        "Papers/pdf/*.pdf가 원문이고, 나머지 MD는 연구자의 메모예요.",
        "",
        "규칙:",
        "- vault의 파일을 읽어서 확인한 내용으로만 답하세요. 모르면 모른다고 하세요. 지어내지 마세요.",
        "- 먼저 노트(MD)를 보고, 필요할 때만 PDF를 읽으세요.",
        "- 파일을 고치거나 명령을 돌리지 말고 읽기만 하세요.",
        "- 답은 한국어 해요체로 짧고 분명하게. 근거로 쓴 논문은 sources에 노트 파일 이름으로 적으세요.",
        "",
        "vault의 논문 (파일 이름 · 제목):",
    ]
    lines += [f"- {p['id']} · {p['title']}" for p in listing[:300]]
    if history:
        lines += ["", "앞선 대화:"]
        for h in history[-MAX_HISTORY:]:
            who = "질문" if h.get("role") == "user" else "답"
            lines.append(f"[{who}] {str(h.get('text') or '')[:1500]}")
    lines += ["", f"질문: {question}"]
    return "\n".join(lines)


async def _ask_agent(root: str, prompt: str, model: str, *, query_fn=None) -> tuple[dict, str]:
    from .agents.readonly import ReadOnlyError, ask

    try:
        data, used = await ask(root, prompt, SCHEMA, model=model, max_turns=MAX_TURNS, query_fn=query_fn)
    except ReadOnlyError as exc:
        raise AskError(str(exc)) from None
    if not isinstance(data.get("answer"), str):
        raise AskError("지정한 형식(JSON)으로 답을 받지 못했어요.")
    return data, used


def _sources(raw: list, listing: list[dict]) -> list[dict]:
    """근거를 vault의 실제 논문으로 — 파일 이름 · 제목 · 경로로 적어도 찾는다. 없는 건 버린다."""
    alias: dict[str, dict] = {}
    for p in listing:
        for key in (p["id"], p["title"], os.path.basename(str(p.get("path") or "")).removesuffix(".md")):
            if key:
                alias[key.strip().lower()] = p
    out, seen = [], set()
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("paper") or "").strip()
        name = os.path.basename(name).removesuffix(".md").strip()
        hit = alias.get(name.lower())
        if hit and hit["id"] not in seen:
            seen.add(hit["id"])
            out.append({"paperId": hit["id"], "label": hit["title"], "why": str(s.get("why") or "")[:200]})
    return out[:8]


async def _work(jid: str, question: str, history: list[dict], model: str, query_fn) -> None:
    rec = _jobs[jid]
    try:
        listing = await asyncio.to_thread(papers.list_papers)
        root = papers.vault_path()
        data, used = await _ask_agent(root, _prompt(question, history, listing), model, query_fn=query_fn)
        rec.update(
            state="done",
            answer=str(data.get("answer") or "")[:8000],
            sources=_sources(data.get("sources") or [], listing),
            model=used,
        )
    except Exception as exc:  # 사람에게 보여 줄 사유
        rec.update(state="failed", error=str(exc)[:500])
    finally:
        rec["endedAt"] = time.time()


def start(question: str, history: list | None = None, *, model: str = "", query_fn=None) -> dict:
    """질문을 받아 작업을 시작한다. 이미 답하는 중이면 거절."""
    question = (question or "").strip()
    if not question:
        raise AskError("질문을 적어 주세요.")
    if len(question) > MAX_QUESTION:
        raise AskError("질문이 너무 길어요.")
    if not os.path.isdir(papers.vault_path()):
        raise AskError("vault 폴더가 없어요 — 사이드바의 'vault 위치'에서 정해 주세요.")
    if any(j["state"] == "running" for j in _jobs.values()):
        raise AskError("앞 질문에 답하는 중이에요. 끝나면 다시 보내 주세요.")
    clean = [
        {"role": "user" if h.get("role") == "user" else "assistant", "text": str(h.get("text") or "")}
        for h in (history or [])
        if isinstance(h, dict)
    ]
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "state": "running", "question": question, "startedAt": time.time(), "answer": "", "sources": [], "error": ""}
    # 오래된 작업은 버린다 (메모리에만)
    for old in sorted(_jobs, key=lambda k: _jobs[k]["startedAt"])[:-20]:
        _jobs.pop(old, None)
    asyncio.get_running_loop().create_task(_work(jid, question, clean, model, query_fn), name=f"library-ask-{jid}")
    return dict(_jobs[jid])


def job(jid: str) -> dict:
    found = _jobs.get(jid)
    if not found:
        raise AskError("없는 질문이에요 (서버를 다시 시작하면 사라져요).")
    return dict(found)
