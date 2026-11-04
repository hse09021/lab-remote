"""스키마와 이행.

DB 를 못 믿으면 큐를 돌리지 않는다. 특히 **앞으로 간 DB** 는 건드리지 않고
거절해야 한다 — 새 코드가 만든 표를 옛 코드가 반쯤 이해한 채로 쓰면 조용히
틀린 값이 쌓인다.
"""

import sqlite3

import pytest

from app import db


def test_빈_DB_가_판_1_로_올라간다(isolated_data):
    conn = db.connect()
    assert db.version(conn) == 0
    result = db.migrate(conn)
    assert result == {"from": 0, "to": db.SCHEMA_VERSION, "changed": True}
    assert db.version(conn) == db.SCHEMA_VERSION
    conn.close()


def test_두_번_이행해도_안_바뀐다(conn):
    again = db.migrate(conn)
    assert again["changed"] is False
    assert db.version(conn) == db.SCHEMA_VERSION


def test_앞으로_간_DB_는_거절한다(conn):
    conn.execute("UPDATE schema_meta SET value='99' WHERE key='version'")
    with pytest.raises(db.DbError) as exc:
        db.migrate(conn)
    assert "DB 가 이 코드보다 새로워요" in str(exc.value)


def test_판을_못_읽으면_거절한다(conn):
    conn.execute("UPDATE schema_meta SET value='알수없음' WHERE key='version'")
    with pytest.raises(db.DbError):
        db.version(conn)


def test_PRAGMA_가_맞다(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS


def test_표와_인덱스가_다_있다(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    for table in (
        "schema_meta",
        "projects",
        "loop_state",
        "jobs",
        "experiments",
        "metrics",
        "resources",
        "events",
        "approvals",
        "notifications",
        "commands",
        "usage_limits",
    ):
        assert table in names, table
    assert "ux_jobs_running" in names


def test_DB_경로는_데이터_폴더_안이다(isolated_data):
    assert db.path().startswith(str(isolated_data))


def test_LAB_DB_PATH_로_바꿀_수_있다(monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DB_PATH", str(tmp_path / "다른.db"))
    assert db.path() == str(tmp_path / "다른.db")


def test_immediate_는_예외에_되돌린다(conn):
    with pytest.raises(ValueError):
        with db.immediate(conn):
            conn.execute(
                "INSERT INTO events(project, at, kind, tone, text) "
                "VALUES('p', '지금', 'k', 'info', '넣었다가')"
            )
            raise ValueError("일부러")
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_running_슬롯은_전역_한_건(conn):
    """코드가 세는 게 아니라 DB 가 막는다."""
    now = db.now()
    for _ in range(2):
        conn.execute(
            "INSERT INTO jobs(project, kind, state, queued_at) "
            "VALUES('p', 'train', 'queued', ?)",
            (now,),
        )
    conn.execute("UPDATE jobs SET running_slot=0 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE jobs SET running_slot=0 WHERE id=2")
