"""사용량 한도로 **보이는** 실패의 원문.

한도에 걸릴 때 `claude -p` 가 무엇을 내놓는지 아직 못 봤다. 그래서 원인을
가르지 않고 **원문과 종료코드를 그대로 쌓는다.** 나중에 실제로 걸리면 그
문구로 "한도 대기" 를 구분한다 (`~/.config/labremote/usage_patterns.json`).

**추가 결제·API 키 전환은 어떤 경우에도 하지 않는다.** 여기 있는 건
"언제부터 막혔고 언제 다시 해 볼까" 뿐이다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["record", "latest", "open_wait", "mark_resumed", "mark_notified", "recent"]


def record(
    conn: sqlite3.Connection,
    *,
    project: str | None,
    raw: str,
    exit_code: int | None = None,
    detected_by: str = "backoff",
    resume_at: str | None = None,
) -> int:
    """실패 한 건을 그대로 보관한다. 자르지 않는다 — 나중에 패턴을 뽑을 원본이다."""
    cur = conn.execute(
        "INSERT INTO usage_limits(project, at, detected_by, exit_code, raw, resume_at) "
        "VALUES(?,?,?,?,?,?)",
        (project, db.now(), detected_by, exit_code, raw, resume_at),
    )
    return int(cur.lastrowid)


def latest(conn: sqlite3.Connection, project: str | None = None) -> dict | None:
    sql = "SELECT * FROM usage_limits"
    args: list = []
    if project:
        sql += " WHERE project=?"
        args.append(project)
    sql += " ORDER BY id DESC LIMIT 1"
    return row(conn.execute(sql, args).fetchone())


def open_wait(conn: sqlite3.Connection, project: str | None = None) -> dict | None:
    """아직 안 풀린 대기. 있으면 "기다리는 중" 알림을 또 보내지 않는다."""
    sql = "SELECT * FROM usage_limits WHERE resumed_at IS NULL"
    args: list = []
    if project:
        sql += " AND project=?"
        args.append(project)
    sql += " ORDER BY id ASC LIMIT 1"
    return row(conn.execute(sql, args).fetchone())


def mark_resumed(conn: sqlite3.Connection, usage_id: int) -> dict | None:
    conn.execute(
        "UPDATE usage_limits SET resumed_at=? WHERE id=?", (db.now(), usage_id)
    )
    return row(
        conn.execute("SELECT * FROM usage_limits WHERE id=?", (usage_id,)).fetchone()
    )


def mark_notified(conn: sqlite3.Connection, usage_id: int) -> None:
    """알림을 보냈다고 적는다. 대기 알림은 **한 번만** 보낸다."""
    conn.execute(
        "UPDATE usage_limits SET notified_at=? WHERE id=?", (db.now(), usage_id)
    )


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return rows(
        conn.execute("SELECT * FROM usage_limits ORDER BY id DESC LIMIT ?", (int(limit),))
    )
