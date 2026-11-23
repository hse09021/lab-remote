"""SQLite 연결과 스키마 이행의 단일 출처.

lab.remote 의 상태(지표·자원 표본·사건·보낸 알림)는 데이터 폴더의 `lab.db`
하나에 있다. 위치는 `registry.data_dir()` 를 따른다.

의존성은 표준 라이브러리뿐이다.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from . import registry

__all__ = [
    "SCHEMA_VERSION",
    "V3_BASE",
    "DbError",
    "path",
    "schema_sql",
    "connect",
    "open_db",
    "migrate",
    "version",
    "now",
]

#: 이 코드가 아는 스키마 판. 올릴 때는 `MIGRATIONS`에 줄을 더한다.
#:
#: 판 5 는 **v3 의 첫 판**이다. v1 은 판 1~4 를 썼다. 판 6에서 Inbox, 판 7에서 예약이 생겼다.
SCHEMA_VERSION = 7

#: v3 가 시작하는 판. 이보다 낮은 판은 **v1 DB** 다.
V3_BASE = 5

#: 판을 올리는 SQL. `{이전 판: SQL 문자열}`. v3에서 판을 올릴 때 여기에 더한다.
#:
#: v1 판(1~4)에서 오는 이행은 **두지 않는다.** v1 표(승인·큐·루프·앵커…)를
#: 지우는 이행은 되돌릴 수 없어서, 조용히 하지 않고 `migrate` 가 거절한다.
MIGRATIONS: dict[int, str] = {
    # 판 7 — 예약 (v3 5단계)
    6: '''
-- 예약 — 사람이 시각으로 건 것만 돈다(PLAN 1.4). 연쇄 예약 없음.
-- kind: command(명령 실행) · agent(세션을 열고 첫 요청만 보냄)
-- repeat: once · daily · weekly. 시각은 epoch 초(서버의 현지 시간대로 계산).
CREATE TABLE IF NOT EXISTS schedules (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  project       TEXT NOT NULL,
  tree          TEXT NOT NULL DEFAULT '',
  command       TEXT NOT NULL DEFAULT '',
  env           TEXT NOT NULL DEFAULT '',
  prompt        TEXT NOT NULL DEFAULT '',
  mode          TEXT NOT NULL DEFAULT 'manual',
  model         TEXT NOT NULL DEFAULT '',
  effort        TEXT NOT NULL DEFAULT '',
  at            REAL NOT NULL,
  repeat        TEXT NOT NULL DEFAULT 'once',
  enabled       INTEGER NOT NULL DEFAULT 1,
  next_at       REAL,
  last_at       REAL,
  last_result   TEXT NOT NULL DEFAULT '',
  last_ref      TEXT,
  waiting_since REAL,
  created_at    TEXT NOT NULL
);
''',
    # 판 6 — Inbox (v3 2단계)
    5: '''
-- Inbox — 사람이 보는 알림. Discord로 보냈는지는 `sent`에 사람 말로 남긴다
-- (주소는 남기지 않는다). `act` 가 1 이면 "내가 처리해야 하는 것" 이라
-- 헤더 배지에 센다(답 필요 · 실행 실패 · 끊김).
CREATE TABLE IF NOT EXISTS inbox (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  at         TEXT NOT NULL,
  kind       TEXT NOT NULL,
  title      TEXT NOT NULL,
  where_text TEXT NOT NULL DEFAULT '',
  body       TEXT NOT NULL DEFAULT '',
  project    TEXT,
  ref        TEXT,
  act        INTEGER NOT NULL DEFAULT 0,
  read_at    TEXT,
  sent       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_inbox_kind ON inbox(kind, id);
''',
}


_SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

#: 잠금 경쟁에서 기다릴 시간. 학습 로그를 쓰는 모니터와 겹칠 수 있다.
BUSY_TIMEOUT_MS = 5000


class DbError(RuntimeError):
    """DB 를 믿을 수 없을 때. 큐를 돌리지 않고 멈춘다."""


def now() -> str:
    """ISO8601 현지 시각. 사람이 읽는 로그와 같은 모양으로 둔다."""
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def path() -> str:
    """`LAB_DB_PATH` 가 있으면 그것, 없으면 `<데이터 폴더>/lab.db`."""
    override = os.environ.get("LAB_DB_PATH")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(registry.data_dir(), "lab.db")


def schema_sql() -> str:
    with open(_SCHEMA_FILE, encoding="utf-8") as fh:
        return fh.read()


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """PRAGMA 를 맞춘 연결. 이행은 하지 않는다 (`open_db` 가 한다)."""
    target = db_path or path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    # isolation_level=None으로 자동 커밋을 끄고 트랜잭션을 우리가 연다.
    # 큐 lease에 BEGIN IMMEDIATE 가 꼭 필요하다.
    conn = sqlite3.connect(target, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def version(conn: sqlite3.Connection) -> int:
    """스키마 판. 표가 아예 없으면 0."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        raise DbError(f"스키마 판을 읽을 수 없어요: {row['value']!r}") from None


def migrate(conn: sqlite3.Connection) -> dict:
    """판을 지금 코드의 판까지 올린다. 이미 같으면 아무것도 하지 않는다.

    **앞으로 간 DB 는 건드리지 않고 거절한다.** 새 코드가 만든 표를 옛 코드가
    반쯤 이해한 채로 쓰면 조용히 틀린 값을 쓴다.
    """
    before = version(conn)
    if before > SCHEMA_VERSION:
        raise DbError(
            f"DB 가 이 코드보다 새로워요 (DB 판 {before}, 코드 판 {SCHEMA_VERSION}). "
            "코드를 올리거나 데이터를 백업하고 지워 주세요: " + path()
        )
    if before == SCHEMA_VERSION:
        return {"from": before, "to": before, "changed": False}
    if 0 < before < V3_BASE:
        raise DbError(
            f"v1 의 DB 예요 (판 {before}). v3 는 v1 표를 옮기지 않아요 — "
            "필요하면 백업해 두고 이 파일을 치운 뒤 다시 띄워 주세요: " + path()
        )

    if before == 0:
        conn.executescript(schema_sql())
        after = SCHEMA_VERSION
    else:
        after = before
        while after < SCHEMA_VERSION:
            step = MIGRATIONS.get(after)
            if step is None:  # pragma: no cover - 판을 올릴 때 같이 넣는다
                raise DbError(f"판 {after} -> {after + 1} 이행 SQL 이 없어요")
            conn.executescript(step)
            after += 1

    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(after),),
    )
    return {"from": before, "to": after, "changed": True}


@contextmanager
def open_db(db_path: str | None = None):
    """이행까지 끝난 연결. 블록을 벗어나면 닫는다.

        with db.open_db() as conn:
            conn.execute(...)
    """
    conn = connect(db_path)
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()


@contextmanager
def immediate(conn: sqlite3.Connection):
    """`BEGIN IMMEDIATE` 트랜잭션. 쓰기 잠금을 바로 잡는다.

    큐에서 작업 하나를 집어가는 동작(lease)은 읽고 나서 쓰기 때문에,
    `DEFERRED`로 두면 두 워커가 같은 작업을 집었다가 하나가
    `SQLITE_BUSY_SNAPSHOT`으로 밀린다. 처음부터 쓰기 잠금을 잡는다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
