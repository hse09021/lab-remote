"""사용량 한도 대기 — **연결**을 고정한다.

실측 2026-11-05: `app/orchestrator/usage.py` 는 다 만들어져 있었는데
**아무도 안 불렀다.** `record_failure`·`wait_state`·`resumed` 전부 미사용이고
`loop_state` 의 `usage_limited` 도 라벨로만 있었다. 그러면 한도에 걸렸을 때
루프가 `IDLE_SEC`(10초)마다 Claude 를 다시 띄우고, 실패 원문만 쌓이고 알림은
한 번도 안 간다 — **자리를 비운 사이에 조용히 망가진다.**
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_orchestrator_loop import (  # noqa: E402
    FakeClaude,
    ctx_for,
    plan_writes_run_json,
    ready,  # noqa: F401  — 가짜 학습까지 갖춘 프로젝트
    review_writes_journal,
)

from app.orchestrator import usage as usage_mod  # noqa: E402
from app.orchestrator.__main__ import once, stop_reason  # noqa: E402
from app.store import loops as LP  # noqa: E402
from app.store import usage as U  # noqa: E402


@pytest.fixture()
def fake(ready):
    got = FakeClaude(ready)
    got.on_plan = plan_writes_run_json
    got.on_review = review_writes_journal
    return got


def failing(text="Claude usage limit reached"):
    def run(made):
        return {"ok": False, "text": text, "stopReason": "error", "raw": text, "exitCode": 1}

    return run


def test_한_번_실패하면_대기에_들어간다(conn, ready, fake):
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))
    assert got["stoppedAt"] == "usage", got
    assert "추가 결제 없이 기다려요" in stop_reason(got)
    assert LP.get(conn, "hook-sandbox")["state"] == "usage_limited"

    row = U.open_wait(conn, "hook-sandbox")
    assert row is not None
    assert row["raw"], "실패 원문을 안 남겼어요"
    assert row["resume_at"], "다음 시도 시각이 없어요"


def test_기다리는_동안_Claude_를_안_띄운다(conn, ready):
    calls = {"n": 0}

    def count(made):
        calls["n"] += 1
        return {"ok": False, "text": "막혔어요", "stopReason": "error", "raw": "x", "exitCode": 1}

    once(conn, "hook-sandbox", ready, **ctx_for(ready, count))
    assert calls["n"] == 1

    # 다음 세 바퀴는 **한 번도 안 띄운다** — 30분 뒤에나 다시 해 본다
    for _ in range(3):
        got = once(conn, "hook-sandbox", ready, **ctx_for(ready, count))
        assert got["stoppedAt"] == "usage"
    assert calls["n"] == 1, "기다리는 중인데 또 띄웠어요"


def test_다시_해_볼_때가_되면_띄운다(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))
    row = U.open_wait(conn, "hook-sandbox")

    # 시간을 되돌린다 (30분이 지난 셈)
    past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE usage_limits SET resume_at=? WHERE id=?", (past, row["id"]))

    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is True, got
    # 풀렸으니 대기가 닫힌다
    assert U.open_wait(conn, "hook-sandbox") is None
    assert LP.get(conn, "hook-sandbox")["state"] != "usage_limited"


def test_또_실패하면_백오프가_다시_길어진다(conn, ready):
    """🔑 행이 쌓이는 동안 **첫 행의 `resume_at` 은 계속 과거**다.

    `ready` 를 그 행으로 재면 10초마다 Claude 를 때린다 — 백오프 무효.
    """
    calls = {"n": 0}

    def count(made):
        calls["n"] += 1
        return {"ok": False, "text": "막혔어요", "stopReason": "error", "raw": "x", "exitCode": 1}

    once(conn, "hook-sandbox", ready, **ctx_for(ready, count))
    first = U.open_wait(conn, "hook-sandbox")
    past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE usage_limits SET resume_at=? WHERE id=?", (past, first["id"]))

    # 때가 돼서 다시 해 보고 또 실패한다
    once(conn, "hook-sandbox", ready, **ctx_for(ready, count))
    assert calls["n"] == 2

    # 이제 **또 기다린다** — 첫 행이 과거여도 최근 실패를 본다
    state = usage_mod.wait_state(conn, "hook-sandbox")
    assert state["waiting"] is True and state["ready"] is False
    assert state["row"]["id"] == first["id"], "언제부터는 가장 오래된 행이에요"
    assert state["newest"]["id"] != first["id"], "다음 시도는 최근 행이에요"

    once(conn, "hook-sandbox", ready, **ctx_for(ready, count))
    assert calls["n"] == 2, "또 때렸어요"


def test_풀리면_쌓인_대기를_전부_닫는다(conn, ready, fake):
    """하나만 닫으면 `open_wait` 이 다음 행을 내놔서 영원히 기다린다."""
    for _ in range(3):
        U.record(conn, project="hook-sandbox", raw="막혔어요", resume_at="2000-01-01T00:00:00+09:00")
    assert U.open_wait(conn, "hook-sandbox") is not None

    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is True, got
    assert U.open_wait(conn, "hook-sandbox") is None


def test_알림은_대기에_들어갈_때_한_번만(conn, ready):
    """소음이 되면 사람이 안 본다. 들어갈 때 1회 (그리고 4시간 뒤 1회)."""
    for _ in range(3):
        once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))

    rows = conn.execute(
        "SELECT title, state FROM notifications WHERE kind='usage_limit'"
    ).fetchall()
    assert len(rows) == 1, [tuple(r) for r in rows]
    assert "막혔어요" in rows[0][0]

    row = U.open_wait(conn, "hook-sandbox")
    assert row["notified_at"], "보냈다고 적어 두지 않으면 또 보내요"


def test_오래_막혀_있으면_한_번_더_알린다(conn, ready):
    """한도가 아니라 인증 만료 같은 다른 오류일 수 있어요."""
    once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))
    row = U.open_wait(conn, "hook-sandbox")

    # 4시간 전부터 막혀 있는 셈으로 둔다
    old = (datetime.now().astimezone() - timedelta(hours=5)).isoformat(timespec="seconds")
    conn.execute("UPDATE usage_limits SET at=? WHERE id=?", (old, row["id"]))

    state = usage_mod.wait_state(conn, "hook-sandbox")
    assert state["renotify"] is True and state["notify"] is False

    once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))
    titles = [
        r[0] for r in conn.execute("SELECT title FROM notifications WHERE kind='usage_limit'")
    ]
    assert any("한도가 아닐 수 있어요" in t for t in titles), titles


def test_학습은_건드리지_않는다(conn, ready):
    """spec V — 멈추는 건 AI 의 의사결정뿐이에요."""
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, failing()))
    assert got["stoppedAt"] == "usage"
    # 루프를 `stopped` 로 만들지 않는다 — 기다리면 풀린다
    assert LP.get(conn, "hook-sandbox")["state"] == "usage_limited"
    assert LP.get(conn, "hook-sandbox")["paused"] == 0


def test_usage_화면이_기다리는_중을_먼저_보여_준다(conn, ready, capsys):
    """사용량 화면을 보는 이유는 보통 "왜 안 도나" 예요."""
    from app import cli

    once(conn, "hook-sandbox", ready, **ctx_for(ready, failing("usage limit reached")))

    class Args:
        name = "hook-sandbox"
        limit = 20
        json = False

    assert cli.cmd_usage(Args()) == 0
    out = capsys.readouterr().out
    assert "응답이 막혀서 기다려요" in out
    assert "다음 시도" in out
    assert "usage limit reached" in out
    assert "돌고 있는 학습은 건드리지 않아요" in out
    # 기다림 안내가 사용량 표보다 **먼저** 나온다
    assert out.index("기다려요") < out.index("Claude 호출")
