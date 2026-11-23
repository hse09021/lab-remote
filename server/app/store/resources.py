"""GPU·CPU·RAM·디스크 표본.

**조회 실패가 정상 경로다.** 드라이버 불일치로 `nvidia-smi` 가 죽어 있어도
표본은 들어와야 한다 (`gpu_available=0` + `note`에 사유). 그래야 화면이
"조회 불가" 를 보여 주고, 언제부터 그랬는지도 남는다.
"""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["add", "latest", "recent", "prune"]


def add(
    conn: sqlite3.Connection,
    *,
    gpu_available: bool,
    gpu_util: float | None = None,
    gpu_mem_used_mb: int | None = None,
    gpu_temp_c: float | None = None,
    cpu_pct: float | None = None,
    ram_pct: float | None = None,
    disk_free_gb: float | None = None,
    note: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO resources(at, gpu_available, gpu_util, gpu_mem_used_mb, "
        "gpu_temp_c, cpu_pct, ram_pct, disk_free_gb, note) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            db.now(),
            1 if gpu_available else 0,
            gpu_util,
            gpu_mem_used_mb,
            gpu_temp_c,
            cpu_pct,
            ram_pct,
            disk_free_gb,
            note,
        ),
    )
    return int(cur.lastrowid)


def latest(conn: sqlite3.Connection) -> dict | None:
    return row(conn.execute("SELECT * FROM resources ORDER BY id DESC LIMIT 1").fetchone())


def recent(conn: sqlite3.Connection, limit: int = 120) -> list[dict]:
    return rows(
        conn.execute("SELECT * FROM resources ORDER BY id DESC LIMIT ?", (int(limit),))
    )


def prune(conn: sqlite3.Connection, keep: int = 20000) -> int:
    """5초마다 쌓이니 오래된 표본은 버린다. 지운 줄 수를 돌려준다."""
    cur = conn.execute(
        "DELETE FROM resources WHERE id <= "
        "(SELECT MAX(id) - ? FROM resources)",
        (int(keep),),
    )
    return int(cur.rowcount or 0)
