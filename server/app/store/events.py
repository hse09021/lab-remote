"""사람이 보는 사건 기록. `web/src/api/types.ts` 의 `EventEntry` 모양이다.

승인 로그(CSV)와 다르다 — CSV 는 훅이 소유하는 감사 기록이고, 이 표는
화면의 "최근 일어난 일" 이다. 문구를 **서버가 한국어 해요체로** 만든다
(목업 계약).
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import rows

__all__ = ["TONES", "add", "recent"]

#: 목업의 tone 어휘
TONES = ("info", "good", "attention", "bad")


def add(
    conn: sqlite3.Connection,
    project: str,
    kind: str,
    text: str,
    *,
    tone: str = "info",
    ref: str | None = None,
) -> int:
    if tone not in TONES:
        raise ValueError(f"모르는 tone 이에요: {tone!r}")
    cur = conn.execute(
        "INSERT INTO events(project, at, kind, tone, text, ref) VALUES(?,?,?,?,?,?)",
        (project, db.now(), kind, tone, text, ref),
    )
    return int(cur.lastrowid)


def recent(conn: sqlite3.Connection, project: str, limit: int = 50) -> list[dict]:
    return rows(
        conn.execute(
            "SELECT * FROM events WHERE project=? ORDER BY id DESC LIMIT ?",
            (project, int(limit)),
        )
    )
