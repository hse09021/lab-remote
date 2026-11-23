"""Inbox — 사람이 보는 알림 목록 (lab.db의 `inbox` 표).

종류: `ask` 답 필요 · `run` 실행 · `sched` 예약 · `pr` PR·머지 · `sys` 시스템.
`act`는 "내가 처리해야 하는 것"(답 필요 · 실행 실패·끊김) — 헤더 배지는
안 읽은 것 중 이것만 센다(사람이 고른 규칙, 2026-11-23).
"""

from __future__ import annotations

import sqlite3

from . import db
from .store import dumps, loads, rows

__all__ = ["KINDS", "add", "items", "counts", "badge", "mark_read", "set_sent"]

KINDS = ("ask", "run", "sched", "pr", "sys")


def add(
    conn: sqlite3.Connection,
    kind: str,
    title: str,
    *,
    where: str = "",
    body: str = "",
    project: str | None = None,
    ref: dict | None = None,
    act: bool = False,
    read: bool = False,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"모르는 알림 종류예요: {kind!r}")
    now = db.now()
    cur = conn.execute(
        "INSERT INTO inbox(at, kind, title, where_text, body, project, ref, act, read_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (now, kind, title, where, body, project, dumps(ref), 1 if act else 0, now if read else None),
    )
    return int(cur.lastrowid)


def _view(row: dict) -> dict:
    return {
        "id": row["id"],
        "at": row["at"],
        "kind": row["kind"],
        "title": row["title"],
        "where": row["where_text"],
        "body": row["body"],
        "project": row["project"],
        "ref": loads(row["ref"]) or {},
        "act": bool(row["act"]),
        "unread": row["read_at"] is None,
        "sent": row["sent"],
    }


def items(conn: sqlite3.Connection, *, kind: str = "", unread: bool = False, limit: int = 200) -> list[dict]:
    where, args = [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if unread:
        where.append("read_at IS NULL")
    sql = "SELECT * FROM inbox" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 1000)))
    return [_view(r) for r in rows(conn.execute(sql, args))]


def counts(conn: sqlite3.Connection) -> dict:
    out = {k: {"total": 0, "unread": 0} for k in KINDS}
    for kind, total, unread in conn.execute(
        "SELECT kind, COUNT(*), SUM(read_at IS NULL) FROM inbox GROUP BY kind"
    ):
        if kind in out:
            out[kind] = {"total": int(total), "unread": int(unread or 0)}
    return out


def badge(conn: sqlite3.Connection) -> int:
    (n,) = conn.execute("SELECT COUNT(*) FROM inbox WHERE read_at IS NULL AND act = 1").fetchone()
    return int(n)


def mark_read(conn: sqlite3.Connection, ids: list[int] | None = None) -> int:
    """`ids`가 없으면 전부."""
    if ids is None:
        cur = conn.execute("UPDATE inbox SET read_at = ? WHERE read_at IS NULL", (db.now(),))
    else:
        clean = [int(i) for i in ids][:1000]
        if not clean:
            return 0
        marks = ",".join("?" * len(clean))
        cur = conn.execute(
            f"UPDATE inbox SET read_at = ? WHERE read_at IS NULL AND id IN ({marks})", (db.now(), *clean)
        )
    return cur.rowcount


def set_sent(conn: sqlite3.Connection, item_id: int, text: str) -> None:
    conn.execute("UPDATE inbox SET sent = ? WHERE id = ?", (text, item_id))
