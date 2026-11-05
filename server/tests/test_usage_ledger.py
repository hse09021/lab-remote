"""📊 Claude 호출의 사용량·시간 장부 (`agent_calls`).

9단계 검증표가 *"루프 1회당 승인 요청 건수(행동 유형별)와 Claude 사용량·시간"*
을 요구한다. `result.parse` 는 그 숫자를 **읽고 버리고 있었다** — 이 시험이
"읽은 것을 남긴다" 를 고정한다.
"""

import os
import shutil

import pytest

from app import db as db_mod
from app import registry
from app.orchestrator.__main__ import once
from app.store import agent_calls as AC
from app.store import approvals as AP
from app.store import loops as LP

from test_orchestrator_loop import (  # noqa: F401  (픽스처를 그대로 쓴다)
    FAKE,
    FakeClaude,
    ctx_for,
    fake,
    healthy_gpu,
    plan_writes_run_json,
    ready,
    review_writes_journal,
    write_config,
)


# --- 판 올리기 ------------------------------------------------------------------


def test_판_3_에서_4_로_올라가며_표가_생긴다(tmp_path):
    """**이미 쓰고 있던** DB 가 깨지지 않아야 한다 — 이 기계의 `lab.db` 가
    판 3 이다."""
    path = str(tmp_path / "lab.db")
    conn = db_mod.connect(path)
    # 판 3 짜리 DB 를 흉내 낸다: 표는 다 있고 `agent_calls` 만 없다.
    conn.executescript(db_mod.schema_sql())
    conn.execute("DROP TABLE IF EXISTS agent_calls")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', '3')"
    )
    conn.commit()
    assert db_mod.version(conn) == 3
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "agent_calls" not in names

    got = db_mod.migrate(conn)
    assert got["to"] == db_mod.SCHEMA_VERSION == 4
    assert got["changed"] is True
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "agent_calls" in names


# --- 한 건 남기기 ---------------------------------------------------------------


def _result(**kw):
    out = {
        "ok": True,
        "model": "claude-opus-5",
        "stopReason": "end_turn",
        "numTurns": 7,
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 340,
            "cache_read_input_tokens": 90_000,
            "cache_creation_input_tokens": 1_500,
        },
        "costUsd": 0.1234,
        "denials": [{"tool_name": "Bash"}],
        "json": {"duration_ms": 8321},
    }
    out.update(kw)
    return out


def test_결과_JSON_의_사용량을_빠짐없이_남긴다(conn):
    LP.ensure(conn, "hook-sandbox")
    row = AC.record(
        conn, "hook-sandbox", "plan", _result(),
        loop_no=3, session_id="sess-1", wall_ms=9100,
    )
    assert row["stage"] == "plan"
    assert row["loop_no"] == 3
    assert row["model"] == "claude-opus-5"
    assert row["num_turns"] == 7
    assert row["input_tokens"] == 1200
    assert row["output_tokens"] == 340
    assert row["cache_read_tokens"] == 90_000
    assert row["cache_write_tokens"] == 1_500
    assert row["cost_usd"] == pytest.approx(0.1234)
    assert row["denials"] == 1
    # 시간은 **둘 다** 남는다 — 벽시계가 더 길면 띄우는 데 쓴 시간이다.
    assert row["wall_ms"] == 9100
    assert row["session_ms"] == 8321
    assert row["wall_ms"] > row["session_ms"]


def test_사용량을_못_읽어도_지어내지_않는다(conn):
    """한도에 걸려 JSON 이 안 오는 경우가 실제로 있다 — 그때 0 으로 적으면
    "안 썼다" 는 거짓이 된다. `NULL` 로 남긴다."""
    row = AC.record(
        conn, "hook-sandbox", "plan",
        {"ok": False, "raw": "무슨 오류", "usage": {}, "costUsd": None},
        loop_no=1, session_id="sess-x", wall_ms=120,
    )
    assert row["input_tokens"] is None
    assert row["cost_usd"] is None
    assert row["num_turns"] is None
    assert row["ok"] == 0
    assert row["wall_ms"] == 120


def test_합계가_못_읽은_것과_0_을_구별한다(conn):
    AC.record(conn, "p", "plan", _result(costUsd=None), loop_no=1, wall_ms=10)
    AC.record(conn, "p", "review", _result(costUsd=0.5), loop_no=1, wall_ms=20)
    use = AC.totals(AC.listing(conn, "p"))
    assert use["calls"] == 2
    assert use["wall_ms"] == 30
    assert use["cost_usd"] == pytest.approx(0.5)
    # 둘 중 하나만 비용을 읽었다 — 그 사실이 보여야 한다
    assert use["cost_usdKnown"] == 1
    assert use["num_turnsKnown"] == 2


# --- 루프별 묶음 + 행동 유형별 승인 요청 -----------------------------------------


def test_루프별로_묶고_승인_요청을_행동_유형별로_센다(conn):
    LP.ensure(conn, "hook-sandbox")
    AC.record(conn, "hook-sandbox", "plan", _result(), loop_no=1, session_id="s1", wall_ms=100)
    AC.record(conn, "hook-sandbox", "review", _result(), loop_no=1, session_id="s2", wall_ms=200)
    AC.record(conn, "hook-sandbox", "plan", _result(), loop_no=2, session_id="s3", wall_ms=50)

    AP.open_request(conn, "hook-sandbox", "toolu_a", action_key="pkg", session_id="s1", tool="Bash")
    AP.open_request(conn, "hook-sandbox", "toolu_b", action_key="net", session_id="s1", tool="WebFetch")
    AP.open_request(conn, "hook-sandbox", "toolu_c", action_key="pkg", session_id="s2", tool="Bash")
    AP.open_request(conn, "hook-sandbox", "toolu_d", action_key="del", session_id="s3", tool="Bash")

    loops = AC.by_loop(conn, "hook-sandbox")
    first = [item for item in loops if item["loopNo"] == 1][0]
    assert first["stages"] == ["plan", "review"]
    assert first["usage"]["calls"] == 2
    assert first["usage"]["wall_ms"] == 300
    assert first["approvals"]["_total"] == 3
    assert first["approvals"]["pkg"]["open"] == 2
    assert first["approvals"]["net"]["open"] == 1

    second = [item for item in loops if item["loopNo"] == 2][0]
    assert second["approvals"]["_total"] == 1
    assert "del" in second["approvals"]
    # 1회차 승인 요청이 2회차로 새지 않는다
    assert "pkg" not in second["approvals"]


def test_루프_밖_호출도_따로_보인다(conn):
    AC.record(conn, "hook-sandbox", "probe", _result(), loop_no=None, session_id="sp", wall_ms=5)
    loops = AC.by_loop(conn, "hook-sandbox")
    assert [item["loopNo"] for item in loops] == [None]


# --- 루프가 실제로 남기나 (가짜 Claude) ------------------------------------------


class UsageClaude(FakeClaude):
    """가짜 Claude 가 **진짜 모양의 결과** 를 돌려준다."""

    def __call__(self, made):
        got = super().__call__(made)
        got.update(
            model="claude-opus-5",
            numTurns=4,
            usage={
                "input_tokens": 300,
                "output_tokens": 120,
                "cache_read_input_tokens": 40_000,
                "cache_creation_input_tokens": 800,
            },
            costUsd=0.0456,
            json={"duration_ms": 1234},
        )
        return got


@pytest.fixture()
def usage_fake(ready):
    claude = UsageClaude(ready)
    claude.on_plan = plan_writes_run_json
    claude.on_review = review_writes_journal
    return claude


def test_루프_한_바퀴가_호출_두_건을_남긴다(conn, ready, usage_fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, usage_fake))

    calls = AC.listing(conn, "hook-sandbox")
    assert [c["stage"] for c in reversed(calls)] == ["plan", "review"]
    assert {c["loop_no"] for c in calls} == {1}
    assert all(c["model"] == "claude-opus-5" for c in calls)
    # 벽시계는 **우리가** 재니까 항상 있다
    assert all(isinstance(c["wall_ms"], int) for c in calls)
    assert all(c["session_ms"] == 1234 for c in calls)

    use = AC.totals(calls)
    assert use["calls"] == 2
    assert use["input_tokens"] == 600
    assert use["cost_usd"] == pytest.approx(0.0912)
    # 세션 ID 가 비어 있으면 승인 요청을 붙일 수 없다
    assert all(c["session_id"] for c in calls)


def test_기록이_실패해도_루프는_간다(conn, ready, usage_fake, monkeypatch):
    """장부는 **보조**다. 여기서 던져 루프를 멈추면 안 된다."""
    def boom(*a, **kw):
        raise RuntimeError("장부가 깨졌어요")

    monkeypatch.setattr(AC, "record", boom)
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, usage_fake))
    assert got["ok"] is True, got


# --- CLI ------------------------------------------------------------------------


def test_usage_명령이_루프별로_찍는다(conn, ready, usage_fake, capsys):
    from app import cli

    once(conn, "hook-sandbox", ready, **ctx_for(ready, usage_fake))
    capsys.readouterr()
    assert cli.main(["usage", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "루프 1회차" in out
    assert "Claude 호출 2건" in out
    assert "plan → review" in out
    assert "승인 요청 없음" in out
    assert "$0.0912" in out


def test_usage_명령이_기록이_없으면_안내만_한다(conn, ready, capsys):
    from app import cli

    assert cli.main(["usage", "hook-sandbox"]) == 0
    assert "아직 Claude 를 띄운 기록이 없어요" in capsys.readouterr().out


def test_usage_명령이_등록_안_된_프로젝트를_거부한다(conn, capsys):
    from app import cli

    assert cli.main(["usage", "없는-프로젝트"]) == 2
