"""학습 지표. 출처는 `experiments/EXP-NNN/result.csv` 다 (W&B 는 ② 범위 밖).

**NaN·Inf 는 `value` 를 NULL 로 두고 `flag` 에 적는다.** SQLite 의 REAL 에
NaN 을 넣으면 왕복이 깨지고(비교가 전부 거짓이 된다) 그래프가 조용히 틀어진다.
NaN 자체가 "즉시 중단" 신호라서 잃어버려서는 안 되는 값이다.
"""

from __future__ import annotations

import math
import sqlite3

from .. import db
from . import rows

__all__ = ["FLAGS", "add", "series", "last", "has_flag"]

#: 숫자로 못 적는 값의 사유
FLAGS = ("nan", "inf", "-inf")


def _split(value) -> tuple[float | None, str | None]:
    """(저장할 값, 깃발). 숫자가 아니면 값은 None 이다."""
    if value is None:
        return None, None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, "nan"
    if math.isnan(number):
        return None, "nan"
    if math.isinf(number):
        return None, "inf" if number > 0 else "-inf"
    return number, None


def add(
    conn: sqlite3.Connection,
    project: str,
    exp_id: str,
    name: str,
    value,
    *,
    step: int | None = None,
    epoch: int | None = None,
) -> int:
    stored, flag = _split(value)
    cur = conn.execute(
        "INSERT INTO metrics(project, exp_id, step, epoch, name, value, flag, at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (project, exp_id, step, epoch, name, stored, flag, db.now()),
    )
    return int(cur.lastrowid)


def series(
    conn: sqlite3.Connection, project: str, exp_id: str, name: str, limit: int = 2000
) -> list[dict]:
    """학습 곡선용. 들어온 순서를 지킨다(step 이 없을 수도 있다)."""
    return rows(
        conn.execute(
            "SELECT * FROM metrics WHERE project=? AND exp_id=? AND name=? "
            "ORDER BY id ASC LIMIT ?",
            (project, exp_id, name, int(limit)),
        )
    )


def last(
    conn: sqlite3.Connection, project: str, exp_id: str, name: str
) -> dict | None:
    found = conn.execute(
        "SELECT * FROM metrics WHERE project=? AND exp_id=? AND name=? "
        "ORDER BY id DESC LIMIT 1",
        (project, exp_id, name),
    ).fetchone()
    return dict(found) if found else None


def has_flag(conn: sqlite3.Connection, project: str, exp_id: str) -> list[dict]:
    """NaN·Inf 가 한 번이라도 있었나. 있으면 즉시 중단 신호다 (spec III-4)."""
    return rows(
        conn.execute(
            "SELECT * FROM metrics WHERE project=? AND exp_id=? AND flag IS NOT NULL "
            "ORDER BY id ASC",
            (project, exp_id),
        )
    )
