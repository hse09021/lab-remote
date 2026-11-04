"""③(웹)이 ②에게 보내는 명령.

②에 HTTP 서버를 넣지 않는다. ③의 FastAPI 가 이 표에 INSERT 하면 ②의
워커가 1초마다 집어간다. 둘의 결합이 **파일 하나**뿐이라, ③이 없어도 ②가
돌고 ②가 죽어도 ③이 뜬다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import dumps, loads, row, rows

__all__ = ["KINDS", "push", "take", "done", "pending", "get"]

#: 쓸 수 있는 명령. 모르는 종류는 받지 않는다 — 웹에서 임의 문자열이
#: 들어와 오케스트레이터가 해석을 시도하는 길을 막는다.
KINDS = (
    "stop_experiment",
    "pause_loop",
    "resume_loop",
    "cancel_job",
    "queue_experiment",
    "reload_policy",
)


def push(conn: sqlite3.Connection, kind: str, *, project: str | None = None, payload=None) -> int:
    if kind not in KINDS:
        raise ValueError(f"모르는 명령이에요: {kind!r} · 쓸 수 있는 것: {', '.join(KINDS)}")
    cur = conn.execute(
        "INSERT INTO commands(project, kind, payload, state, created_at) "
        "VALUES(?,?,?, 'pending', ?)",
        (project, kind, dumps(payload), db.now()),
    )
    return int(cur.lastrowid)


def take(conn: sqlite3.Connection) -> dict | None:
    """대기 중인 명령 하나를 집어 `taken` 으로 바꾼다. 없으면 None."""
    with db.immediate(conn):
        found = row(
            conn.execute(
                "SELECT * FROM commands WHERE state='pending' ORDER BY id ASC LIMIT 1"
            ).fetchone()
        )
        if found is None:
            return None
        conn.execute("UPDATE commands SET state='taken' WHERE id=?", (found["id"],))
    found["payload"] = loads(found.get("payload"))
    found["state"] = "taken"
    return found


def done(conn: sqlite3.Connection, command_id: int, *, result=None, state: str = "done") -> dict | None:
    conn.execute(
        "UPDATE commands SET state=?, result=?, done_at=? WHERE id=?",
        (state, dumps(result), db.now(), command_id),
    )
    return get(conn, command_id)


def get(conn: sqlite3.Connection, command_id: int) -> dict | None:
    found = row(conn.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone())
    if found is not None:
        found["payload"] = loads(found.get("payload"))
        found["result"] = loads(found.get("result"))
    return found


def pending(conn: sqlite3.Connection) -> list[dict]:
    return rows(conn.execute("SELECT * FROM commands WHERE state='pending' ORDER BY id"))
