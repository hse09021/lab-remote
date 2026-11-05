"""SQLite 연결과 스키마 이행의 단일 출처.

②의 상태는 전부 `server/data/lab.db` 하나에 있다. 큐·실험·지표·알림·승인이
같은 트랜잭션 안에서 움직여야 하고, 파일 여러 개로 쪼개면 "running 은 1건"
같은 불변식을 코드가 지켜야 하기 때문이다. 지금은 DB 가 지킨다
(`ux_jobs_running`).

**훅은 이 모듈을 import 하지 않는다.** 훅 경로는 표준 라이브러리 중에서도
`sqlite3` 를 쓰지 않는다 — 잠금 경쟁으로 훅이 느려지거나 멈추면 그게 바로
판정 지연이다. 훅이 보는 것은 `runstate` JSON 미러뿐이고,
`tests/test_stdlib_only.py` 가 이 규칙을 강제한다.

의존성은 표준 라이브러리뿐이다.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

from . import registry

__all__ = [
    "SCHEMA_VERSION",
    "DbError",
    "path",
    "schema_sql",
    "connect",
    "open_db",
    "migrate",
    "version",
    "now",
]

#: 이 코드가 아는 스키마 판. 올릴 때는 `MIGRATIONS` 에 줄을 더한다.
SCHEMA_VERSION = 4

#: 판을 올리는 SQL. `{이전 판: SQL 문자열}` — 판 1 은 schema.sql 통째다.
MIGRATIONS: dict[int, str] = {
    # 판 1 -> 2 · 앵커 (AI 가 못 쓰는 곳에 둔 기준값). T5 는 git HEAD,
    # S7 은 승인 로그 해시 체인을 같은 표에 담는다.
    # 판 2 -> 3 · 승인 내용의 출처를 적는다 (원칙 (나)).
    #   source='denials'  오케스트레이터가 자기 자식의 결과 JSON 에서 만든 것
    #   source='hook'     훅의 요청 파일에서 거울한 것 (참고용)
    # tool_summary 는 **본문 없는** 요약이다 (길이·해시). 비밀이 섞일 수 있어
    # 원본 tool_input 은 DB 에 넣지 않는다.
    # 판 3 -> 4 · Claude 호출의 사용량·시간 (9단계 검증표가 요구한다).
    #   `result.parse` 가 읽던 usage·cost·num_turns 를 버리지 않고 남긴다.
    3: """
CREATE TABLE IF NOT EXISTS agent_calls (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project      TEXT NOT NULL,
  loop_no      INTEGER,
  stage        TEXT NOT NULL,
  session_id   TEXT,
  resumed      INTEGER NOT NULL DEFAULT 0,
  model        TEXT,
  ok           INTEGER,
  stop_reason  TEXT,
  num_turns    INTEGER,
  wall_ms      INTEGER,
  session_ms   INTEGER,
  input_tokens         INTEGER,
  output_tokens        INTEGER,
  cache_read_tokens    INTEGER,
  cache_write_tokens   INTEGER,
  cost_usd     REAL,
  denials      INTEGER NOT NULL DEFAULT 0,
  at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_calls_loop ON agent_calls(project, loop_no, id);
CREATE INDEX IF NOT EXISTS ix_agent_calls_session ON agent_calls(session_id);
""",
    2: """
ALTER TABLE approvals ADD COLUMN source TEXT NOT NULL DEFAULT 'hook';
ALTER TABLE approvals ADD COLUMN tool_summary TEXT;
""",
    1: """
CREATE TABLE IF NOT EXISTS anchors (
  project    TEXT NOT NULL,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL DEFAULT '',
  value      TEXT NOT NULL,
  count      INTEGER,
  note       TEXT,
  at         TEXT NOT NULL,
  PRIMARY KEY (project, kind, key)
);
""",
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
    # isolation_level=None 으로 자동 커밋을 끄고 트랜잭션을 우리가 연다.
    # 큐 lease 에 BEGIN IMMEDIATE 가 꼭 필요하다.
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
    `DEFERRED` 로 두면 두 워커가 같은 작업을 집었다가 하나가
    `SQLITE_BUSY_SNAPSHOT` 으로 밀린다. 처음부터 쓰기 잠금을 잡는다.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
