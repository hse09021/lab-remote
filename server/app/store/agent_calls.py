"""📊 Claude 호출의 **사용량과 시간** (`agent_calls` 표).

## 왜 필요한가

`agent/result.parse` 는 결과 JSON 에서 `usage`·`total_cost_usd`·`num_turns`·
`duration_ms` 를 이미 읽고 있었는데 **아무 데도 안 남기고 버렸습니다.** 루프가
끝나면 "이번 바퀴에 얼마나 썼나" 를 되살릴 방법이 없었습니다.

9단계 검증표가 *"루프 1회당 승인 요청 건수(행동 유형별)와 Claude 사용량·
시간"* 을 요구하므로, 호출 한 건마다 한 줄을 남깁니다.

## 시간을 두 개 적는 이유

| 열 | 누가 재나 | 무엇 |
|---|---|---|
| `wall_ms` | **우리** (`time.monotonic`) | 프로세스 띄우기 + 세션 + 끝내기 전부 |
| `session_ms` | 결과 JSON 의 `duration_ms` | 세션 안쪽만 |

둘이 크게 벌어지면 띄우는 데 시간을 쓰고 있다는 뜻입니다 — 우리가 고칠 수
있는 쪽입니다.

## 승인 요청은 어떻게 붙나

`approvals.session_id` 로 이 표에 붙입니다. `jobs` 에는 `loop_no` 가 없고
`loop_state.loop_no` 는 지금 값 하나뿐이라, 루프별로 가르려면 세션이 유일한
연결고리입니다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import rows

__all__ = ["record", "listing", "by_loop", "totals",
    "resumed_after", "approvals_by_action"]

#: 결과 JSON 의 `usage` 안 키 → 우리 열 이름. 이름이 판마다 흔들리므로
#: 여러 후보를 본다 (없으면 `None` 으로 남기고 지어내지 않는다).
_TOKEN_KEYS = {
    "input_tokens": ("input_tokens", "inputTokens"),
    "output_tokens": ("output_tokens", "outputTokens"),
    "cache_read_tokens": (
        "cache_read_input_tokens", "cacheReadInputTokens", "cache_read_tokens",
    ),
    "cache_write_tokens": (
        "cache_creation_input_tokens", "cacheCreationInputTokens",
        "cache_creation_tokens",
    ),
}


def _tokens(usage) -> dict:
    out = {name: None for name in _TOKEN_KEYS}
    if not isinstance(usage, dict):
        return out
    for name, candidates in _TOKEN_KEYS.items():
        for key in candidates:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                out[name] = int(value)
                break
    return out


def record(
    conn: sqlite3.Connection,
    project: str,
    stage: str,
    result,
    *,
    loop_no: int | None = None,
    session_id: str = "",
    resumed: bool = False,
    wall_ms: int | None = None,
) -> dict:
    """호출 한 건을 남긴다. **던지지 않는 쪽이 낫지만** 여기선 던진다 —
    부르는 자리(`loop._claude`)가 감싸서 루프를 멈추지 않게 한다."""
    got = result if isinstance(result, dict) else {}
    usage = got.get("usage")
    tokens = _tokens(usage)
    data = got.get("json") if isinstance(got.get("json"), dict) else {}
    session_ms = data.get("duration_ms")

    cur = conn.execute(
        "INSERT INTO agent_calls("
        " project, loop_no, stage, session_id, resumed, model, ok, stop_reason,"
        " num_turns, wall_ms, session_ms, input_tokens, output_tokens,"
        " cache_read_tokens, cache_write_tokens, cost_usd, denials, at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            project,
            loop_no,
            stage,
            session_id or got.get("sessionId") or "",
            1 if resumed else 0,
            got.get("model"),
            None if got.get("ok") is None else (1 if got.get("ok") else 0),
            got.get("stopReason"),
            got.get("numTurns"),
            wall_ms,
            int(session_ms) if isinstance(session_ms, (int, float)) else None,
            tokens["input_tokens"],
            tokens["output_tokens"],
            tokens["cache_read_tokens"],
            tokens["cache_write_tokens"],
            got.get("costUsd"),
            len(got.get("denials") or []),
            db.now(),
        ),
    )
    return listing(conn, project, call_id=cur.lastrowid)[0]


def listing(
    conn: sqlite3.Connection,
    project: str | None = None,
    *,
    loop_no: int | None = None,
    call_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    where, args = [], []
    if project:
        where.append("project=?")
        args.append(project)
    if loop_no is not None:
        where.append("loop_no=?")
        args.append(loop_no)
    if call_id is not None:
        where.append("id=?")
        args.append(call_id)
    sql = "SELECT * FROM agent_calls"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return rows(conn.execute(sql, args))


#: 합계에 넣을 열. `None` 은 0 으로 세지 않고 **빼** 센다 — 못 읽은 것과
#: 0 을 구별하려고 `…Known` 개수도 같이 돌려준다.
_SUMS = (
    "wall_ms", "session_ms", "num_turns",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "cost_usd",
)


def resumed_after(conn, project: str, session_id: str, since: str) -> bool:
    """그 세션을 `since` 뒤에 **이어 간 적이 있나.**

    설치 승인에는 요청 파일이 없다(훅이 만든 게 아니다). 그래서 "이미
    이어 갔다" 를 적어 둘 자리가 없는데, 장부에 이미 다 있다 — 같은
    `session_id` 로 `resumed=1` 인 호출이 결정 시각 뒤에 있으면 이어 간 거다.
    """
    if not session_id or not since:
        return False
    found = conn.execute(
        "SELECT 1 FROM agent_calls WHERE project=? AND session_id=? "
        "AND resumed=1 AND at>=? LIMIT 1",
        (project, session_id, since),
    ).fetchone()
    return found is not None


def totals(calls: list[dict]) -> dict:
    out = {"calls": len(calls), "denials": 0}
    for name in _SUMS:
        total = None
        known = 0
        for call in calls:
            value = call.get(name)
            if isinstance(value, (int, float)):
                total = (total or 0) + value
                known += 1
        out[name] = total
        out[f"{name}Known"] = known
    for call in calls:
        out["denials"] += int(call.get("denials") or 0)
    return out


def by_loop(conn: sqlite3.Connection, project: str, *, limit: int = 20) -> list[dict]:
    """루프별 묶음. 각 줄에 **Claude 사용량·시간** 과 **승인 요청 건수(행동
    유형별)** 를 같이 담는다 (9단계 검증표가 요구하는 모양).

    `loop_no` 가 `NULL` 인 호출(루프 밖 — 탐침 등)은 `loopNo=None` 한 줄로 모은다.
    """
    seen: dict = {}
    order: list = []
    for call in listing(conn, project, limit=2000):
        key = call.get("loop_no")
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(call)

    out = []
    for key in order[:limit]:
        calls = seen[key]
        sessions = {str(c.get("session_id") or "") for c in calls}
        sessions.discard("")
        row_out = {
            "loopNo": key,
            "stages": [c["stage"] for c in reversed(calls)],
            "usage": totals(calls),
            "approvals": approvals_by_action(conn, project, sessions),
            "at": calls[-1].get("at"),
        }
        out.append(row_out)
    return out


def approvals_by_action(conn: sqlite3.Connection, project: str, sessions) -> dict:
    """그 세션들에서 열린 승인 요청을 **행동 유형별로** 센다.

    `{"pkg": {"open": 1, "approved": 0, "denied": 1}, …, "_total": 2}`
    """
    out: dict = {"_total": 0}
    marks = list({str(s) for s in sessions if s})
    if not marks:
        return out
    holes = ",".join("?" for _ in marks)
    got = conn.execute(
        f"SELECT action_key, state, COUNT(*) AS n FROM approvals "
        f"WHERE project=? AND session_id IN ({holes}) "
        f"GROUP BY action_key, state",
        [project, *marks],
    ).fetchall()
    for line in got:
        action = str(line["action_key"] or "[미분류]")
        state = str(line["state"] or "open")
        count = int(line["n"])
        bucket = out.setdefault(action, {})
        bucket[state] = bucket.get(state, 0) + count
        out["_total"] += count
    return out
