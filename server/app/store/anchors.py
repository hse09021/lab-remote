"""📌 앵커 — **AI 가 못 쓰는 곳에 둔 기준값** (`anchors` 표).

프로젝트 안의 기록은 샌드박스에서 쓰기 가능하다(M4). `.git` 의 refs·objects
도 마찬가지라 브랜치를 지우거나 이전 커밋을 바꿔치기해서 실험 기록을 위조할
수 있다. 승인 로그 CSV 도 같다.

그래서 오케스트레이터가 **자기가 한 일**의 기준값을 `lab.db` 에 적고 나중에
대조한다. `lab.db` 는 `server/data/` 아래라 샌드박스 안에서 쓰기가
실패한다(M1b) — 그게 이 표가 기준이 될 수 있는 유일한 이유다.

`kind` 로 여러 종류를 담는다.

| kind | key | value | count |
|---|---|---|---|
| `git_head` | 브랜치 이름 | 커밋 해시 | — |
| `approval_log` | `csv` | 마지막 해시 체인 값 | 줄 수 |
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["put", "get", "listing", "drop"]


def put(
    conn: sqlite3.Connection,
    project: str,
    kind: str,
    value: str,
    *,
    key: str = "",
    count: int | None = None,
    note: str = "",
) -> dict:
    """기준값을 적는다(덮어쓴다). 같은 `(project, kind, key)` 는 하나다."""
    conn.execute(
        "INSERT INTO anchors(project, kind, key, value, count, note, at) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(project, kind, key) DO UPDATE SET "
        "value=excluded.value, count=excluded.count, note=excluded.note, at=excluded.at",
        (project, kind, key, str(value), count, note, db.now()),
    )
    conn.commit()
    return get(conn, project, kind, key=key) or {}


def get(conn: sqlite3.Connection, project: str, kind: str, *, key: str = "") -> dict | None:
    return row(
        conn.execute(
            "SELECT * FROM anchors WHERE project=? AND kind=? AND key=?",
            (project, kind, key),
        ).fetchone()
    )


def listing(conn: sqlite3.Connection, project: str, kind: str = "") -> list[dict]:
    if kind:
        cur = conn.execute(
            "SELECT * FROM anchors WHERE project=? AND kind=? ORDER BY key",
            (project, kind),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM anchors WHERE project=? ORDER BY kind, key", (project,)
        )
    return rows(cur)


def drop(conn: sqlite3.Connection, project: str, kind: str, *, key: str = "") -> int:
    cur = conn.execute(
        "DELETE FROM anchors WHERE project=? AND kind=? AND key=?", (project, kind, key)
    )
    conn.commit()
    return cur.rowcount
