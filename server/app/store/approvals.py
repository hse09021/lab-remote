"""승인 요청의 거울.

진실은 **파일**이다 — 훅이 `data/requests/<프로젝트>/` 에 남기고, 허가는
`data/grants/` 의 서명된 파일이다. 이 표는 사람과 화면이 보는 사본이고,
"같은 요청이 몇 번 반복됐나"(`attempts`)를 세는 자리다. 훅은 이 표를
읽지 않는다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["STATES", "open_request", "get", "by_request", "decide", "bump", "pending"]

#: `stale` — 요청 파일이 사라졌는데 DB 행만 `open` 으로 남은 것을 **사람이**
#: 정리한 상태다. `denied` 로 적으면 "사람이 거절했다" 는 거짓이 된다
#: (거절은 판단이고, 이건 정리다). `labremote approvals prune` 이 쓴다.
STATES = (
    "open", "approved", "denied", "expired", "consumed", "blocked", "stale",
)


def open_request(
    conn: sqlite3.Connection,
    project: str,
    request_id: str,
    *,
    job_id: int | None = None,
    session_id: str = "",
    tool: str = "",
    action_key: str = "",
    rel: str | None = None,
    request: str = "",
    reason: str = "",
    fingerprint: str = "",
    loose_key: str = "",
    source: str = "hook",
    tool_summary=None,
) -> dict:
    """요청을 올린다. 같은 요청이 또 오면 `attempts` 만 올린다.

    `UNIQUE(project, request_id)` 가 중복을 막는다 — 오케스트레이터가
    `requests/` 를 여러 번 훑어도 줄이 늘지 않는다.
    """
    from . import dumps

    conn.execute(
        "INSERT INTO approvals(project, request_id, job_id, session_id, tool, "
        "action_key, rel, request, reason, fingerprint, loose_key, source, "
        "tool_summary, state, opened_at, attempts) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?, 1) "
        # ⚠ **`attempts` 를 여기서 올리지 않는다.** 전에는 올렸고, 그래서
        # 거울(`sync`·`sync_from_result`)을 부를 때마다 횟수가 늘어 **한 번의
        # 거절이 3회**가 됐다(S9 e2e 가 잡았다). 상한이 2라 정상 요청이
        # 막힐 수 있었다. 진짜 재시도는 `bump()` 로 센다.
        "ON CONFLICT(project, request_id) DO UPDATE SET "
        # 🔑 `denials` 출처가 `hook` 출처를 **덮는다.** 반대는 안 된다 —
        # 오케스트레이터가 자기 자식에게서 직접 받은 값이 더 믿을 만하다.
        "source=CASE WHEN excluded.source='denials' THEN 'denials' ELSE source END, "
        "fingerprint=CASE WHEN excluded.source='denials' AND excluded.fingerprint<>'' "
        "            THEN excluded.fingerprint ELSE fingerprint END, "
        "tool_summary=COALESCE(excluded.tool_summary, tool_summary), "
        "tool=CASE WHEN excluded.source='denials' THEN excluded.tool ELSE tool END, "
        # 사유는 훅만 안다 (`permission_denials` 에 사유 칸이 없다 — M2)
        "reason=CASE WHEN excluded.reason<>'' THEN excluded.reason ELSE reason END, "
        # 🔑 **비어 있던 칸만 채운다.** `permission_denials` 에는 행동 유형·
        # 상대경로가 없다(M2) — 그건 훅만 안다. S9 e2e 가 이걸 잡았다:
        # `denials` 행이 먼저 생기면 훅의 `action_key` 가 영원히 못 닿았다.
        # 이미 값이 있으면 **덮지 않는다** (나중 쓰기가 좋은 값을 지우면 안 된다).
        "action_key=CASE WHEN COALESCE(action_key,'')='' "
        "           THEN excluded.action_key ELSE action_key END, "
        "rel=COALESCE(rel, excluded.rel), "
        "loose_key=CASE WHEN COALESCE(loose_key,'')='' "
        "          THEN excluded.loose_key ELSE loose_key END, "
        "session_id=CASE WHEN COALESCE(session_id,'')='' "
        "           THEN excluded.session_id ELSE session_id END, "
        "job_id=COALESCE(job_id, excluded.job_id)",
        (
            project,
            request_id,
            job_id,
            session_id,
            tool,
            action_key,
            rel,
            request,
            reason,
            fingerprint,
            loose_key,
            source,
            dumps(tool_summary),
            db.now(),
        ),
    )
    return by_request(conn, project, request_id)  # type: ignore[return-value]


def get(conn: sqlite3.Connection, approval_id: int) -> dict | None:
    return row(
        conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    )


def by_request(conn: sqlite3.Connection, project: str, request_id: str) -> dict | None:
    return row(
        conn.execute(
            "SELECT * FROM approvals WHERE project=? AND request_id=?",
            (project, request_id),
        ).fetchone()
    )


def decide(
    conn: sqlite3.Connection,
    project: str,
    request_id: str,
    state: str,
    *,
    grant_id: str | None = None,
    by: str = "cli",
) -> dict:
    if state not in STATES:
        raise ValueError(f"모르는 승인 상태예요: {state!r}")
    conn.execute(
        "UPDATE approvals SET state=?, grant_id=COALESCE(?, grant_id), "
        "decided_at=?, decided_by=? WHERE project=? AND request_id=?",
        (state, grant_id, db.now(), by, project, request_id),
    )
    found = by_request(conn, project, request_id)
    if found is None:
        raise ValueError(f"그런 승인 요청이 없어요: {request_id}")
    return found


def bump(conn: sqlite3.Connection, project: str, request_id: str) -> int:
    """같은 요청이 또 왔다. 상한을 넘으면 호출부가 루프를 멈춘다."""
    conn.execute(
        "UPDATE approvals SET attempts=attempts+1 WHERE project=? AND request_id=?",
        (project, request_id),
    )
    found = by_request(conn, project, request_id)
    return int((found or {}).get("attempts") or 0)


def pending(conn: sqlite3.Connection, project: str | None = None) -> list[dict]:
    sql = "SELECT * FROM approvals WHERE state='open'"
    args: list = []
    if project:
        sql += " AND project=?"
        args.append(project)
    sql += " ORDER BY id ASC"
    return rows(conn.execute(sql, args))
