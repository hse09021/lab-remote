"""작업 큐.

GPU 가 1개라 **동시 실행은 0건 또는 1건**이다. 그걸 코드가 아니라 **DB 가**
보장한다 — `running_slot` 은 `running` 일 때만 `0` 이고 그 밖에는 `NULL` 이며,
`ux_jobs_running` 이 UNIQUE 다. SQLite 는 UNIQUE 에서 NULL 중복을 허용하므로
"`running` 은 전역 1건" 이 된다. 워커가 둘 떠도 두 번째 UPDATE 가 깨진다.

상태 전이도 표로 못박는다. `done` 인 작업이 다시 `running` 이 되는 식의
되돌림은 기록을 거짓으로 만든다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import dumps, loads, row, rows

__all__ = [
    "KINDS",
    "STATES",
    "TRANSITIONS",
    "SlotBusy",
    "StateError",
    "add",
    "get",
    "lease",
    "start",
    "heartbeat",
    "finish",
    "requeue",
    "cancel",
    "block",
    "wait_approval",
    "set_state",
    "running",
    "listing",
    "stale",
    "counts",
]

#: 작업 종류. plan·review·resume 은 Claude 를 띄우고, train 은 오케스트레이터가
#: 직접 돌린다 (학습을 Claude 의 Bash 로 돌리지 않는다).
KINDS = ("plan", "train", "review", "resume", "journal_fix")

STATES = (
    "queued",
    "leased",
    "running",
    "waiting_approval",
    "done",
    "failed",
    "timeout",
    "cancelled",
    "blocked",
)

#: 갈 수 있는 다음 상태. 여기 없는 전이는 `StateError` 다.
TRANSITIONS: dict[str, set[str]] = {
    "queued": {"leased", "cancelled", "blocked"},
    # lease 만 하고 못 띄운 경우가 있다 — 큐로 되돌린다.
    "leased": {"running", "queued", "failed", "cancelled", "blocked"},
    "running": {
        "done",
        "failed",
        "timeout",
        "cancelled",
        "blocked",
        "waiting_approval",
    },
    # 승인을 기다리다 허가가 생기면 다시 큐로. 거부면 blocked.
    "waiting_approval": {"queued", "cancelled", "blocked", "failed"},
    # 끝난 작업은 되돌리지 않는다. 재시도는 **새 작업**으로 넣는다.
    "done": set(),
    "cancelled": set(),
    # 실패·타임아웃은 재시도 상한 안에서만 큐로 돌아간다.
    "failed": {"queued"},
    "timeout": {"queued"},
    "blocked": {"queued", "cancelled"},
}

#: `running` 일 때 넣는 값. 전역 1건을 만드는 자리.
RUNNING_SLOT = 0


class SlotBusy(RuntimeError):
    """이미 돌고 있는 작업이 있다. GPU 가 1개라 두 번째는 못 띄운다."""


class StateError(ValueError):
    """허락되지 않은 상태 전이."""


def add(
    conn: sqlite3.Connection,
    project: str,
    kind: str,
    *,
    experiment_id: str | None = None,
    payload=None,
    priority: int = 0,
    max_attempts: int = 3,
    timeout_sec: int | None = None,
    session_id: str | None = None,
    parent_job_id: int | None = None,
    log_path: str | None = None,
) -> int:
    if kind not in KINDS:
        raise StateError(f"모르는 작업 종류예요: {kind!r} · 쓸 수 있는 것: {', '.join(KINDS)}")
    cur = conn.execute(
        "INSERT INTO jobs(project, kind, experiment_id, parent_job_id, priority, "
        "state, payload, max_attempts, timeout_sec, session_id, log_path, queued_at) "
        "VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?)",
        (
            project,
            kind,
            experiment_id,
            parent_job_id,
            int(priority),
            dumps(payload),
            int(max_attempts),
            timeout_sec,
            session_id,
            log_path,
            db.now(),
        ),
    )
    return int(cur.lastrowid)


def get(conn: sqlite3.Connection, job_id: int) -> dict | None:
    found = row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    if found is not None:
        found["payload"] = loads(found.get("payload"))
    return found


def _require(conn, job_id: int) -> dict:
    found = get(conn, job_id)
    if found is None:
        raise StateError(f"그런 작업이 없어요: id={job_id}")
    return found


def _check(before: str, after: str) -> None:
    if after not in STATES:
        raise StateError(f"모르는 상태예요: {after!r}")
    if after not in TRANSITIONS.get(before, set()):
        raise StateError(f"{before} -> {after} 로는 갈 수 없어요")


def lease(
    conn: sqlite3.Connection,
    project: str | None = None,
    kinds: tuple[str, ...] | None = None,
) -> dict | None:
    """큐에서 하나를 집어 `leased` 로 바꾼다. 없으면 None.

    `BEGIN IMMEDIATE` 안에서 읽고 쓴다 — 두 워커가 같은 작업을 집는 걸
    막는다. 우선순위가 높은 것, 같으면 먼저 들어온 것이 먼저다.
    """
    sql = "SELECT * FROM jobs WHERE state='queued'"
    args: list = []
    if project:
        sql += " AND project=?"
        args.append(project)
    if kinds:
        sql += " AND kind IN (" + ",".join("?" * len(kinds)) + ")"
        args.extend(kinds)
    sql += " ORDER BY priority DESC, id ASC LIMIT 1"

    with db.immediate(conn):
        found = row(conn.execute(sql, args).fetchone())
        if found is None:
            return None
        _check(found["state"], "leased")
        conn.execute(
            "UPDATE jobs SET state='leased', attempt=attempt+1, heartbeat_at=? WHERE id=?",
            (db.now(), found["id"]),
        )
    return get(conn, found["id"])


def start(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    pid: int | None = None,
    pgid: int | None = None,
    log_path: str | None = None,
    session_id: str | None = None,
) -> dict:
    """`leased` -> `running`. 슬롯을 잡는다.

    이미 다른 작업이 돌고 있으면 `SlotBusy` 다 — **DB 의 UNIQUE 인덱스가**
    막아 주는 것이고, 코드가 세어 보는 게 아니다.
    """
    before = _require(conn, job_id)
    _check(before["state"], "running")
    now = db.now()
    try:
        conn.execute(
            "UPDATE jobs SET state='running', running_slot=?, pid=?, pgid=?, "
            "log_path=COALESCE(?, log_path), session_id=COALESCE(?, session_id), "
            "started_at=COALESCE(started_at, ?), heartbeat_at=? WHERE id=?",
            (RUNNING_SLOT, pid, pgid, log_path, session_id, now, now, job_id),
        )
    except sqlite3.IntegrityError as exc:
        busy = running(conn)
        raise SlotBusy(
            "이미 돌고 있는 작업이 있어요"
            + (f" (id={busy['id']}, {busy['kind']})" if busy else "")
            + " · GPU 가 1개라 순서대로 돌려요."
        ) from exc
    return _require(conn, job_id)


def heartbeat(conn: sqlite3.Connection, job_id: int) -> None:
    """살아 있다는 표시. 끊기면 복구가 "죽었다" 고 본다."""
    conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (db.now(), job_id))


def set_state(
    conn: sqlite3.Connection,
    job_id: int,
    state: str,
    *,
    exit_code: int | None = None,
    error: str | None = None,
    model_used: str | None = None,
    keep_slot: bool = False,
) -> dict:
    """상태를 바꾸고 슬롯을 정리한다. 전이표에 없으면 `StateError`."""
    before = _require(conn, job_id)
    _check(before["state"], state)
    ended = state in ("done", "failed", "timeout", "cancelled", "blocked")
    slot = RUNNING_SLOT if (state == "running" or keep_slot) else None
    conn.execute(
        "UPDATE jobs SET state=?, running_slot=?, exit_code=COALESCE(?, exit_code), "
        "error=COALESCE(?, error), model_used=COALESCE(?, model_used), "
        "ended_at=CASE WHEN ? THEN ? ELSE ended_at END WHERE id=?",
        (state, slot, exit_code, error, model_used, 1 if ended else 0, db.now(), job_id),
    )
    return _require(conn, job_id)


def finish(
    conn: sqlite3.Connection,
    job_id: int,
    state: str = "done",
    *,
    exit_code: int | None = None,
    error: str | None = None,
    model_used: str | None = None,
) -> dict:
    """끝났다고 적고 **슬롯을 놓는다.** 다음 작업이 돌 수 있게."""
    if state not in ("done", "failed", "timeout"):
        raise StateError(f"finish 로 갈 수 있는 상태가 아니에요: {state!r}")
    return set_state(
        conn, job_id, state, exit_code=exit_code, error=error, model_used=model_used
    )


def requeue(conn: sqlite3.Connection, job_id: int, *, error: str | None = None) -> dict:
    """다시 큐로. 재시도 상한은 **호출부(오케스트레이터)가** 센다 —
    훅처럼 단순하게 둬야 할 곳이 아니라서 여기서 막지 않는다."""
    return set_state(conn, job_id, "queued", error=error)


def cancel(conn: sqlite3.Connection, job_id: int, *, error: str | None = None) -> dict:
    return set_state(conn, job_id, "cancelled", error=error)


def block(conn: sqlite3.Connection, job_id: int, *, error: str) -> dict:
    """사람이 봐야 멈춤이 풀리는 상태. 같은 요청이 반복될 때 쓴다."""
    return set_state(conn, job_id, "blocked", error=error)


def wait_approval(conn: sqlite3.Connection, job_id: int, *, error: str | None = None) -> dict:
    """승인 대기. **슬롯을 놓는다** — 사람을 기다리는 동안 GPU 를 잡고 있으면
    다른 작업이 한 발짝도 못 나간다."""
    return set_state(conn, job_id, "waiting_approval", error=error)


def running(conn: sqlite3.Connection) -> dict | None:
    """지금 돌고 있는 작업. 0건 또는 1건이다."""
    return row(
        conn.execute("SELECT * FROM jobs WHERE running_slot IS NOT NULL").fetchone()
    )


def listing(
    conn: sqlite3.Connection,
    project: str | None = None,
    states: tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[dict]:
    sql = "SELECT * FROM jobs WHERE 1=1"
    args: list = []
    if project:
        sql += " AND project=?"
        args.append(project)
    if states:
        sql += " AND state IN (" + ",".join("?" * len(states)) + ")"
        args.extend(states)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return rows(conn.execute(sql, args))


def stale(conn: sqlite3.Connection, older_than_sec: int) -> list[dict]:
    """심장이 멈춘 `leased`·`running` 작업. 복구가 이걸 보고 이어받는다.

    ⚠ **양쪽을 UTC 로 맞춰 비교한다.** `heartbeat_at` 은 시간대 꼬리표가
    붙은 ISO8601(`+09:00`)이고 SQLite 의 `datetime()` 은 그걸 UTC 로 바꿔
    준다. 그래서 `datetime('now')`(이것도 UTC)와 비교해야 한다.
    `'localtime'` 을 섞으면 시간대 차이만큼(여기선 9시간) 전부 "멈춘 것" 으로
    보인다 — 돌고 있는 학습을 복구가 가로채는 사고가 된다.
    """
    cutoff = "datetime('now', '-" + str(int(older_than_sec)) + " seconds')"
    return rows(
        conn.execute(
            "SELECT * FROM jobs WHERE state IN ('leased','running') AND "
            f"(heartbeat_at IS NULL OR datetime(heartbeat_at) < {cutoff}) ORDER BY id"
        )
    )


def counts(conn: sqlite3.Connection, project: str | None = None) -> dict[str, int]:
    sql = "SELECT state, COUNT(*) AS n FROM jobs"
    args: list = []
    if project:
        sql += " WHERE project=?"
        args.append(project)
    sql += " GROUP BY state"
    return {r["state"]: int(r["n"]) for r in conn.execute(sql, args)}
