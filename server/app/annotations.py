"""리더의 내 하이라이트 · 주석 — 데이터 폴더 `annotations.json`에 논문별로 둔다.

예전에는 브라우저(localStorage)에만 있어서 휴대폰과 데스크톱이 따로 놀았다. vault 노트는
고치지 않는다(PDF 좌표 · HTML 앵커는 lab.remote 리더만 쓰는 값이라).
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid

from . import registry

__all__ = ["AnnotationError", "list_for", "add", "update", "remove"]

KINDS = ("highlight", "note")
MAX_TEXT = 5000
MAX_BOXES = 200
_lock = threading.Lock()


class AnnotationError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def _path() -> str:
    return os.path.join(registry.data_dir(), "annotations.json")


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_for(pid: str) -> list[dict]:
    rows = _load().get(pid) or []
    return sorted(rows, key=lambda r: -(r.get("createdAt") or 0))


def _clean(pid: str, raw: dict) -> dict:
    kind = raw.get("kind")
    if kind not in KINDS:
        raise AnnotationError("하이라이트나 주석만 저장해요.")
    text = str(raw.get("text") or "")
    if not text.strip() or len(text) > MAX_TEXT:
        raise AnnotationError("내용이 비어 있거나 너무 길어요.")
    boxes = raw.get("boxes")
    if boxes is not None:
        if not isinstance(boxes, list) or len(boxes) > MAX_BOXES:
            raise AnnotationError("위치 정보가 올바르지 않아요.")
        boxes = [[float(v) for v in b] for b in boxes if isinstance(b, list) and len(b) == 4]
    anchor = raw.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, dict):
            raise AnnotationError("위치 정보가 올바르지 않아요.")
        anchor = {"blockId": str(anchor.get("blockId") or "")[:200], "start": int(anchor.get("start") or 0), "end": int(anchor.get("end") or 0)}
    return {
        "paperId": pid,
        "kind": kind,
        "text": text,
        "source": str(raw.get("source") or "")[:MAX_TEXT],
        "sectionId": str(raw.get("sectionId") or "")[:100],
        "page": int(raw.get("page") or 0),
        "anchor": anchor,
        "boxes": boxes,
    }


def add(pid: str, raw: dict) -> dict:
    """새로 만든다. `id` · `createdAt`이 있으면 되돌리기라 그대로 되살린다."""
    row = _clean(pid, raw)
    rid = str(raw.get("id") or "")
    row["id"] = rid if rid and len(rid) <= 64 else f"u-{uuid.uuid4().hex[:12]}"
    row["createdAt"] = raw.get("createdAt") if isinstance(raw.get("createdAt"), (int, float)) else int(time.time() * 1000)
    with _lock:
        data = _load()
        rows = [r for r in data.get(pid) or [] if r.get("id") != row["id"]]
        data[pid] = [row, *rows]
        registry.write_json(_path(), data)
    return row


def update(pid: str, aid: str, text: str) -> dict:
    if not str(text or "").strip() or len(text) > MAX_TEXT:
        raise AnnotationError("내용이 비어 있거나 너무 길어요.")
    with _lock:
        data = _load()
        for r in data.get(pid) or []:
            if r.get("id") == aid:
                r["text"] = text
                registry.write_json(_path(), data)
                return r
    raise AnnotationError("없는 주석이에요.")


def remove(pid: str, aid: str) -> None:
    with _lock:
        data = _load()
        rows = data.get(pid) or []
        left = [r for r in rows if r.get("id") != aid]
        if len(left) == len(rows):
            raise AnnotationError("없는 주석이에요.")
        data[pid] = left
        registry.write_json(_path(), data)
