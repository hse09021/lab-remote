"""논문 AI 요약 — 누를 때만 만든다 (2026-11-24 결정).

- 에이전트를 vault에서 읽기 전용으로 열어 논문 노트와 PDF를 읽게 하고, 정해진 모양
  (3줄 요약 · 쪽 번호 · 정보 칸 · 방법 · 결과 · 한계)으로 받는다.
- **vault에 새 파일** `Papers/<이름> 요약.md`를 만든다. 원래 노트는 고치지 않는다.
  앞쪽 메타의 `summary_of: "[[이름]]"`으로 라이브러리가 논문으로 세지 않는다.
- "정리된 보기" 용 구조 데이터는 데이터 폴더 `summaries/`에 둔다. 요약 MD를 사람이 고치면
  vault의 요약 파일만 고친다(구조 데이터는 그대로).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

from . import papers, registry

__all__ = ["SummaryError", "SCHEMA", "load_all", "markdown_of", "start", "job", "save_markdown", "running_ids"]

SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "description": "3줄 요약 — 정확히 세 개",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "한 줄 (한국어, 해요체 말고 명사형 끝맺음 가능, 짧게)"},
                    "page": {"type": "integer", "description": "근거가 있는 PDF 쪽 번호. 모르면 0"},
                },
                "required": ["text", "page"],
            },
        },
        "field": {"type": "string", "description": "분야 (예: NLP · 기계 번역)"},
        "baseModel": {"type": "string", "description": "쓴 기반 모델 · 크기. 없으면 빈 문자열"},
        "code": {"type": "string", "description": "코드 저장소 주소. 본문에 없으면 빈 문자열"},
        "method": {"type": "string", "description": "방법 한두 문장"},
        "methodPage": {"type": "integer"},
        "result": {"type": "string", "description": "주요 결과 (숫자 포함) 한두 문장"},
        "resultPage": {"type": "integer"},
        "limitation": {"type": "string", "description": "한계 · 주의할 점. 본문에 없으면 빈 문자열"},
    },
    "required": ["lines", "field", "baseModel", "code", "method", "methodPage", "result", "resultPage", "limitation"],
}

_jobs: dict[str, dict] = {}


class SummaryError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 실패 사유."""


def _dir() -> str:
    return os.path.join(registry.data_dir(), "summaries")


def _json_path(pid: str) -> str:
    return os.path.join(_dir(), hashlib.sha1(pid.encode()).hexdigest()[:16] + ".json")


def _paper(pid: str) -> dict:
    for p in papers.scan()["papers"]:
        if p["id"] == pid:
            return p
    raise SummaryError(f"없는 논문이에요: {pid}")


def _ours(pid: str, path: str) -> bool:
    """그 자리의 파일을 lab.remote가 만들었나 — 없거나, 표시가 있거나, 우리 기록이 있으면."""
    if not os.path.exists(path):
        return True
    if os.path.exists(_json_path(pid)):
        return True
    with open(path, encoding="utf-8", errors="replace") as fh:
        return "summary_of:" in fh.read(400)


def _summary_file(p: dict) -> str:
    """vault의 요약 파일 경로 (노트 옆 `<이름> 요약.md`)."""
    note = os.path.join(papers.vault_path(), p["path"])
    stem = os.path.splitext(os.path.basename(note))[0]
    return os.path.join(os.path.dirname(note), f"{stem} 요약.md")


def load_all() -> dict[str, dict]:
    """id → 화면의 PaperSummary 모양 (만든 것만)."""
    out = {}
    for p in papers.scan()["papers"]:
        try:
            with open(_json_path(p["id"]), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        out[p["id"]] = data.get("summary") or {}
    return out


def markdown_of(pid: str) -> str | None:
    try:
        p = _paper(pid)
    except SummaryError:
        return None
    path = _summary_file(p)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def running_ids() -> set[str]:
    return {pid for pid, j in _jobs.items() if j["state"] == "running"}


def _ref(page: int) -> str:
    return f"p.{page}" if isinstance(page, int) and page > 0 else "p.[쪽]"


def _shape(p: dict, data: dict) -> dict:
    pdf = papers.pdf_rel(p["id"])
    authors = ", ".join(p.get("authorList") or []) or p["authors"]
    fields = [
        ("Field", str(data.get("field") or "")),
        ("Base Model", str(data.get("baseModel") or "")),
        ("Paper URL", f"arxiv.org/abs/{p['arxiv']}" if p.get("arxiv") else ""),
        ("Code", str(data.get("code") or "")),
    ]
    lines = [{"text": str(x.get("text") or "")[:300], "ref": _ref(x.get("page"))} for x in (data.get("lines") or [])[:3] if isinstance(x, dict)]
    return {
        "path": "vault/" + os.path.relpath(_summary_file(p), papers.vault_path()).replace(os.sep, "/"),
        "file": os.path.basename(pdf) if pdf else os.path.basename(p["path"]),
        "html": False,
        "authors": authors,
        "venue": p.get("venue") or "",
        "title": p["title"],
        "meta": " · ".join(x for x in (authors, p.get("venue") or "", "PDF" if pdf else "노트") if x),
        "lines": lines,
        "fields": [{"label": k, "value": v} for k, v in fields if v],
        "method": str(data.get("method") or "")[:800],
        "result": str(data.get("result") or "")[:800],
        "limitation": str(data.get("limitation") or "")[:800],
        "_pages": {"method": data.get("methodPage") or 0, "result": data.get("resultPage") or 0},
    }


def _markdown(p: dict, s: dict) -> str:
    """Obsidian 용 요약 MD — 근거 쪽은 PDF 링크로."""
    pdf = papers.pdf_rel(p["id"])

    def cite(ref: str) -> str:
        if not pdf or ref == "p.[쪽]":
            return f" ({ref})"
        return f" ([[{pdf}#page={ref[2:]}|{ref}]])"

    pages = s.get("_pages") or {}
    out = [
        "---",
        f'summary_of: "[[{os.path.splitext(os.path.basename(p["path"]))[0]}]]"',
        f"title: {json.dumps(s['title'], ensure_ascii=False)}",
        f"authors: {json.dumps(s['authors'], ensure_ascii=False)}",
        f"venue: {json.dumps(s['venue'], ensure_ascii=False)}",
    ]
    for f in s["fields"]:
        out.append(f"{f['label'].lower().replace(' ', '_')}: {json.dumps(f['value'], ensure_ascii=False)}")
    out += ["source: pdf" if pdf else "source: note", f"made_by: lab.remote ({time.strftime('%Y-%m-%d')})", "---", "", "## 3줄 요약"]
    out += [f"{i + 1}. {line['text']}{cite(line['ref'])}" for i, line in enumerate(s["lines"])]
    out += ["", "## Method", s["method"] + cite(_ref(pages.get("method") or 0)), "", "## Result", s["result"] + cite(_ref(pages.get("result") or 0))]
    if s["limitation"]:
        out += ["", "## Limitation", s["limitation"]]
    return "\n".join(out) + "\n"


def _prompt(p: dict) -> str:
    pdf = papers.pdf_rel(p["id"])
    return "\n".join([
        "이 폴더는 연구자의 논문 vault예요. 아래 논문을 읽고 요약해 주세요.",
        f"- 논문 노트: {p['path']}",
        f"- 원문 PDF: {pdf}" if pdf else "- 원문 PDF: 없음 (노트만 읽으세요)",
        "",
        "규칙:",
        "- 읽은 내용으로만 쓰세요. 없는 숫자 · 주소는 지어내지 말고 빈 문자열이나 0으로 두세요.",
        "- 3줄 요약은 정확히 세 줄, 각 줄마다 근거가 있는 PDF 쪽 번호를 적으세요.",
        "- 한국어로 짧게. 파일을 고치거나 명령을 돌리지 말고 읽기만 하세요.",
    ])


async def _work(pid: str, model: str, query_fn) -> None:
    rec = _jobs[pid]
    try:
        from .agents.readonly import ReadOnlyError, ask

        p = await asyncio.to_thread(_paper, pid)
        try:
            data, used = await ask(papers.vault_path(), _prompt(p), SCHEMA, model=model, max_turns=40, query_fn=query_fn)
        except ReadOnlyError as exc:
            raise SummaryError(str(exc)) from None
        shaped = _shape(p, data)
        # vault에 요약 파일 — 우리 요약 파일이면 새로 만든 것으로 바꾸고, 같은 이름의 다른 파일은 덮지 않는다
        path = _summary_file(p)
        if not _ours(pid, path):
            raise SummaryError(f"같은 이름의 다른 파일이 있어 요약 파일을 쓰지 못했어요: {os.path.basename(path)}")
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(_markdown(p, shaped))
        os.replace(tmp, path)
        os.makedirs(_dir(), exist_ok=True)
        registry.write_json(_json_path(pid), {"id": pid, "model": used, "createdAt": time.time(), "summary": shaped})
        rec.update(state="done", model=used)
    except Exception as exc:
        rec.update(state="failed", error=str(exc)[:500])
    finally:
        rec["endedAt"] = time.time()


def start(pid: str, *, model: str = "", query_fn=None) -> dict:
    _paper(pid)
    if _jobs.get(pid, {}).get("state") == "running":
        raise SummaryError("이 논문은 이미 요약하는 중이에요.")
    if len(running_ids()) >= 2:
        raise SummaryError("요약을 두 편까지만 같이 만들어요. 끝나면 다시 눌러 주세요.")
    _jobs[pid] = {"id": pid, "state": "running", "startedAt": time.time(), "error": ""}
    asyncio.get_running_loop().create_task(_work(pid, model, query_fn), name=f"summary-{pid}")
    return dict(_jobs[pid])


def job(pid: str) -> dict:
    return dict(_jobs.get(pid) or {"id": pid, "state": "idle", "error": ""})


def save_markdown(pid: str, markdown: str | None) -> dict:
    """요약 MD 수정 — vault의 **요약 파일만** 고친다. None 이면 구조 데이터로 다시 만든다."""
    p = _paper(pid)
    path = _summary_file(p)
    if markdown is None:
        try:
            with open(_json_path(pid), encoding="utf-8") as fh:
                markdown = _markdown(p, json.load(fh)["summary"])
        except (OSError, KeyError, json.JSONDecodeError):
            raise SummaryError("되돌릴 요약이 없어요.") from None
    if len(markdown) > 200_000:
        raise SummaryError("요약이 너무 길어요.")
    if not _ours(pid, path):
        raise SummaryError("같은 이름의 다른 파일이 있어 저장하지 않았어요.")
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    os.replace(tmp, path)
    return {"id": pid, "path": "vault/" + os.path.relpath(path, papers.vault_path()).replace(os.sep, "/")}
