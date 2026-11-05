"""③(웹)이 보낸 명령 — **집어가는 쪽**을 고정한다.

실측 2026-11-05: `store/commands.py` 는 다 만들어져 있었는데 **집어가는 쪽이
없었다.** 웹이 `pause_loop` 을 INSERT 해도 아무 일도 일어나지 않는다 —
화면에는 "멈췄어요" 라고 뜨고 루프는 계속 돈다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_orchestrator_loop import (  # noqa: E402
    FakeClaude,
    ctx_for,
    plan_writes_run_json,
    ready,  # noqa: F401
    review_writes_journal,
)

from app import runstate  # noqa: E402
from app.orchestrator import commands as cmd_mod  # noqa: E402
from app.orchestrator.__main__ import once  # noqa: E402
from app.store import commands as C  # noqa: E402
from app.store import events as E  # noqa: E402
from app.store import experiments as X  # noqa: E402
from app.store import jobs as J  # noqa: E402
from app.store import loops as LP  # noqa: E402


@pytest.fixture()
def fake(ready):  # noqa: F811
    got = FakeClaude(ready)
    got.on_plan = plan_writes_run_json
    got.on_review = review_writes_journal
    return got


def test_모르는_명령은_애초에_안_들어온다(conn):
    with pytest.raises(ValueError):
        C.push(conn, "rm -rf /", project="hook-sandbox")


def test_일시정지가_실제로_먹는다(conn, ready, fake):  # noqa: F811
    C.push(conn, "pause_loop", project="hook-sandbox", payload={"reason": "밥 먹으러"})
    got = cmd_mod.drain(conn)
    assert len(got) == 1 and got[0]["result"]["ok"] is True
    assert "밥 먹으러" in got[0]["result"]["note"]

    state = LP.get(conn, "hook-sandbox")
    assert state["paused"] == 1 and "밥 먹으러" in state["paused_reason"]

    # 루프가 **안 돈다**
    ran = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert ran["ok"] is False
    assert "사람이 멈춰 뒀어요" in ran["steps"][0]["reason"]
    assert fake.calls == [], "멈춰 뒀는데 Claude 를 띄웠어요"


def test_재개가_걸쇠까지_푼다(conn, ready, fake):  # noqa: F811
    LP.set_state(conn, "hook-sandbox", "stopped", stop_reason="최대 실행 횟수")
    LP.pause(conn, "hook-sandbox", reason="멈춤")
    C.push(conn, "resume_loop", project="hook-sandbox")
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is True
    assert "걸쇠도 풀었어요" in got[0]["result"]["note"]
    state = LP.get(conn, "hook-sandbox")
    assert state["paused"] == 0 and state["state"] == "idle"


def test_작업_취소(conn, ready):  # noqa: F811
    job_id = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    C.push(conn, "cancel_job", project="hook-sandbox", payload={"jobId": job_id})
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is True
    assert J.get(conn, job_id)["state"] == "cancelled"


def test_돌고_있는_작업은_취소로_지우지_않는다(conn, ready):  # noqa: F811
    """큐에서만 지우면 **프로세스가 고아로 남는다.**"""
    job_id = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn, "hook-sandbox", kinds=("train",))
    J.start(conn, job_id, pid=os.getpid(), pgid=os.getpid(), log_path="")
    C.push(conn, "cancel_job", project="hook-sandbox", payload={"jobId": job_id})
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is False
    assert "stop_experiment" in got[0]["result"]["note"]
    assert J.get(conn, job_id)["state"] == "running"


def test_학습_중단이_프로세스_그룹째로_끊는다(conn, ready, monkeypatch):  # noqa: F811
    killed = {}

    def fake_kill(pgid, *, grace_sec=120, poll_sec=None):
        killed["pgid"] = pgid
        killed["grace"] = grace_sec
        return "SIGTERM 으로 끝났어요"

    monkeypatch.setattr(cmd_mod.process_mod, "terminate_group", fake_kill)

    job_id = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn, "hook-sandbox", kinds=("train",))
    J.start(conn, job_id, pid=4242, pgid=4242, log_path="")
    X.upsert(conn, "hook-sandbox", "EXP-001", state="running")
    runstate.set_running("hook-sandbox", "EXP-001", pid=4242)

    C.push(
        conn, "stop_experiment",
        project="hook-sandbox", payload={"experimentId": "EXP-001"},
    )
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is True, got
    assert killed["pgid"] == 4242
    assert killed["grace"] == cmd_mod.STOP_GRACE_SEC

    assert J.get(conn, job_id)["state"] == "cancelled"
    assert X.get(conn, "hook-sandbox", "EXP-001")["state"] == "stopped"
    assert runstate.load("hook-sandbox").running is False
    assert LP.get(conn, "hook-sandbox")["state"] == "idle"
    texts = [r["text"] for r in E.recent(conn, "hook-sandbox", limit=10)]
    assert any("웹에서 EXP-001 을 중단했어요" in t for t in texts), texts


def test_다른_실험을_중단하라고_하면_안_끊는다(conn, ready, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        cmd_mod.process_mod, "terminate_group",
        lambda *a, **k: pytest.fail("엉뚱한 걸 끊었어요"),
    )
    job_id = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn, "hook-sandbox", kinds=("train",))
    J.start(conn, job_id, pid=4242, pgid=4242, log_path="")

    C.push(conn, "stop_experiment", project="hook-sandbox", payload={"experimentId": "EXP-999"})
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is False
    assert "EXP-001" in got[0]["result"]["note"]
    assert J.get(conn, job_id)["state"] == "running"


def test_등록_안_된_프로젝트는_거절한다(conn):
    C.push(conn, "pause_loop", project="없는프로젝트")
    got = cmd_mod.drain(conn)
    assert got[0]["result"]["ok"] is False
    assert "등록된 프로젝트가 아니에요" in got[0]["result"]["note"]


def test_처리하면_표에_결과가_남는다(conn, ready):  # noqa: F811
    cid = C.push(conn, "reload_policy", project="hook-sandbox")
    cmd_mod.drain(conn)
    row = C.get(conn, cid)
    assert row["state"] == "done"
    assert row["result"]["ok"] is True
    assert row["done_at"]


def test_한_건이_터져도_다음_건을_처리한다(conn, ready, monkeypatch):  # noqa: F811
    calls = {"n": 0}
    real = cmd_mod.apply_one

    def boom(conn_, command):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("뭔가 터졌어요")
        return real(conn_, command)

    monkeypatch.setattr(cmd_mod, "apply_one", boom)
    first = C.push(conn, "reload_policy", project="hook-sandbox")
    second = C.push(conn, "pause_loop", project="hook-sandbox")
    got = cmd_mod.drain(conn)
    assert len(got) == 2
    assert C.get(conn, first)["state"] == "failed"
    assert "뭔가 터졌어요" in str(C.get(conn, first)["result"])
    assert C.get(conn, second)["state"] == "done"


def test_한_바퀴에_처리하는_건수에_상한이_있다(conn, ready):  # noqa: F811
    for _ in range(5):
        C.push(conn, "reload_policy", project="hook-sandbox")
    got = cmd_mod.drain(conn, limit=2)
    assert len(got) == 2
    assert len(C.pending(conn)) == 3


# --- CLI (웹이 없을 때 사람이 이 경로를 확인할 수 있어야 한다) -----------------------


def test_CLI_로_넣고_볼_수_있다(conn, ready, capsys):  # noqa: F811
    from app import cli

    class Push:
        action = "push"
        name = "hook-sandbox"
        kind = "pause_loop"
        payload = '{"reason": "밥 먹으러"}'
        json = False

    assert cli.cmd_commands(Push()) == 0
    assert "명령을 넣었어요" in capsys.readouterr().out

    class List:
        action = "list"
        name = None
        kind = None
        payload = ""
        json = False

    assert cli.cmd_commands(List()) == 0
    out = capsys.readouterr().out
    assert "pause_loop" in out and "hook-sandbox" in out


def test_CLI_가_모르는_종류를_거절한다(conn, ready, capsys):  # noqa: F811
    from app import cli

    class Push:
        action = "push"
        name = "hook-sandbox"
        kind = "rm -rf /"
        payload = ""
        json = False

    assert cli.cmd_commands(Push()) == 2
    assert "모르는 명령이에요" in capsys.readouterr().err


def test_CLI_가_JSON_아닌_payload_를_거절한다(conn, ready, capsys):  # noqa: F811
    from app import cli

    class Push:
        action = "push"
        name = "hook-sandbox"
        kind = "pause_loop"
        payload = "밥 먹으러"
        json = False

    assert cli.cmd_commands(Push()) == 2
    assert "JSON 이 아니에요" in capsys.readouterr().err
