"""`lab.db` 접근 계층. 화면·오케스트레이터가 SQL 을 직접 쓰지 않게 모은다.

규약 세 가지.

1. 모든 함수가 **첫 인자로 연결(`conn`)을 받는다.** 한 트랜잭션 안에서
   여러 표를 고쳐야 하는 일(작업을 끝내고 실험 상태도 바꾸는 등)이 많아서,
   함수가 각자 연결을 열면 그게 안 된다.
2. 돌려주는 값은 **`dict`** 다. `sqlite3.Row` 를 그대로 내보내면 호출부가
   DB 모양에 묶이고 JSON으로 바로 못 나간다.
3. 시각은 전부 `db.now()` (ISO8601 현지 시각).
"""

from __future__ import annotations

import json

__all__ = ["row", "rows", "dumps", "loads"]


def row(cursor_row) -> dict | None:
    return dict(cursor_row) if cursor_row is not None else None


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor]


def dumps(value) -> str | None:
    """payload·result 칸에 넣을 JSON. None 은 None으로 둔다."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value):
    """payload 칸을 읽는다. 깨졌으면 원문 문자열을 그대로 돌려준다."""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value
