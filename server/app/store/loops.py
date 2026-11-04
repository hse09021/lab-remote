"""프로젝트별 루프 상태 (`loop_state` 표).

**종료 조건 판정은 시스템이 한다**(spec III-4). 그 판정이 보는 누적치가
여기 있고, 사람이 보는 "루프 3회차 · 실행 중" 문구도 여기서 나온다.
AI 가 쓰는 `state/State.yaml` 과는 다른 것이다 — 어긋나면 `doctor` 가 알린다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["STATES", "ensure", "get", "set_state", "pause", "resume", "bump_loop", "listing"]

STATES = (
    "idle",
    "planning",
    "running",
    "reviewing",
    "waiting_approval",
    "usage_limited",
    "paused",
    "blocked",
    "stopped",
    "done",
)


def ensure(conn: sqlite3.Connection, project: str) -> dict:
    conn.execute(
        "INSERT INTO loop_state(project, state, updated_at) VALUES(?, 'idle', ?) "
        "ON CONFLICT(project) DO NOTHING",
        (project, db.now()),
    )
    return get(conn, project)  # type: ignore[return-value]


def get(conn: sqlite3.Connection, project: str) -> dict | None:
    return row(
        conn.execute("SELECT * FROM loop_state WHERE project=?", (project,)).fetchone()
    )


def set_state(
    conn: sqlite3.Connection,
    project: str,
    state: str,
    *,
    current_job_id: int | None = None,
    stop_reason: str | None = None,
) -> dict:
    if state not in STATES:
        raise ValueError(f"모르는 루프 상태예요: {state!r}")
    ensure(conn, project)
    conn.execute(
        "UPDATE loop_state SET state=?, current_job_id=?, "
        "stop_reason=COALESCE(?, stop_reason), updated_at=? WHERE project=?",
        (state, current_job_id, stop_reason, db.now(), project),
    )
    return get(conn, project)  # type: ignore[return-value]


def pause(conn: sqlite3.Connection, project: str, *, reason: str, until: str | None = None) -> dict:
    """루프를 멈춘다. **돌고 있는 학습은 건드리지 않는다** (spec V)."""
    ensure(conn, project)
    conn.execute(
        "UPDATE loop_state SET paused=1, paused_reason=?, paused_until=?, updated_at=? "
        "WHERE project=?",
        (reason, until, db.now(), project),
    )
    return get(conn, project)  # type: ignore[return-value]


def resume(conn: sqlite3.Connection, project: str) -> dict:
    ensure(conn, project)
    conn.execute(
        "UPDATE loop_state SET paused=0, paused_reason=NULL, paused_until=NULL, "
        "updated_at=? WHERE project=?",
        (db.now(), project),
    )
    return get(conn, project)  # type: ignore[return-value]


def bump_loop(conn: sqlite3.Connection, project: str) -> int:
    """루프 회차를 1 올린다. 종료 조건 `max_runs` 가 이 값을 본다."""
    ensure(conn, project)
    conn.execute(
        "UPDATE loop_state SET loop_no=loop_no+1, updated_at=? WHERE project=?",
        (db.now(), project),
    )
    return int((get(conn, project) or {}).get("loop_no") or 0)


def listing(conn: sqlite3.Connection) -> list[dict]:
    return rows(conn.execute("SELECT * FROM loop_state ORDER BY project"))
