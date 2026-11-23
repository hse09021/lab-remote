"""보낸 알림과 **중복 제거**.

같은 실패가 5초마다 반복되면 휴대폰이 못 쓰게 된다. 그래서 종류별 쿨다운
동안은 한 번만 보낸다. 방법은 코드가 세는 게 아니라 **`dedupe_key` 의
UNIQUE 제약**이다 — INSERT 가 실패하면 그게 "이미 보냈다" 다. 프로세스가
둘이어도, 재시작해도 같은 답이 나온다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["STATES", "dedupe_key", "claim", "mark_sent", "mark_failed", "get", "recent"]

STATES = ("pending", "sent", "failed", "suppressed")


def dedupe_key(project: str, kind: str, subject: str, cooldown_sec: int, *, now_ts: float | None = None) -> str:
    """쿨다운 구간을 키에 넣는다.

    `floor(now / cooldown)` 이라 같은 구간 안에서는 같은 키가 되고, 구간이
    바뀌면 다시 보낼 수 있다. 쿨다운이 0 이면 묵히지 않는다(승인 알림).

    알려진 한계: 구간 경계에서 1초 차이로 두 번 갈 수 있다. "마지막 전송
    시각으로부터"로 바꾸면 없어지지만, 그러면 읽고 쓰는 경쟁이 생겨
    프로세스가 둘일 때 답이 흔들린다. 소음 몇 건보다 그게 나쁘다.
    """
    import time

    stamp = now_ts if now_ts is not None else time.time()
    if cooldown_sec <= 0:
        bucket = f"{stamp:.3f}"
    else:
        bucket = str(int(stamp // cooldown_sec))
    return f"{project or '-'}:{kind}:{subject}:{bucket}"


def claim(
    conn: sqlite3.Connection,
    key: str,
    *,
    project: str | None,
    kind: str,
    title: str = "",
    body: str = "",
    route: str = "",
) -> dict | None:
    """보낼 자리를 잡는다. 이미 있으면 None (= 보내지 않는다).

    None 을 받은 쪽은 **아무것도 하지 않는다.** 소음을 줄이는 게 목적이라
    "눌렸다" 는 사실도 따로 알리지 않는다.
    """
    try:
        cur = conn.execute(
            "INSERT INTO notifications(dedupe_key, project, kind, route, title, body, "
            "state, first_at) VALUES(?,?,?,?,?,?, 'pending', ?)",
            (key, project, kind, route, title, body, db.now()),
        )
    except sqlite3.IntegrityError:
        return None
    return get(conn, int(cur.lastrowid))


def mark_sent(conn: sqlite3.Connection, notification_id: int, status: int | None = None) -> dict | None:
    conn.execute(
        "UPDATE notifications SET state='sent', http_status=?, last_at=?, "
        "attempt=attempt+1 WHERE id=?",
        (status, db.now(), notification_id),
    )
    return get(conn, notification_id)


def mark_failed(
    conn: sqlite3.Connection,
    notification_id: int,
    *,
    error: str,
    status: int | None = None,
) -> dict | None:
    """실패를 적는다. **큐를 멈추지 않는다** — 알림은 곁가지다."""
    conn.execute(
        "UPDATE notifications SET state='failed', error=?, http_status=?, last_at=?, "
        "attempt=attempt+1 WHERE id=?",
        (error, status, db.now(), notification_id),
    )
    return get(conn, notification_id)


def get(conn: sqlite3.Connection, notification_id: int) -> dict | None:
    return row(
        conn.execute(
            "SELECT * FROM notifications WHERE id=?", (notification_id,)
        ).fetchone()
    )


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    return rows(
        conn.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (int(limit),)
        )
    )
