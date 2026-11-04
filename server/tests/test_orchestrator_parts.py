"""오케스트레이터의 나머지 — 가드·승인·한도·복구·브랜치."""

import json
import os
import shutil
from datetime import datetime, timedelta

import pytest

from app import approval_log as A
from app import grants, loopstate, registry, runstate
from app.agent import result as result_mod
from app.orchestrator import approvals as AP
from app.orchestrator import gitflow, guards, recovery
from app.orchestrator import usage as U
from app.store import approvals as APS
from app.store import experiments as X
from app.store import jobs as J
from app.store import loops as LP
from app.store import usage as US

FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_train.py")


@pytest.fixture()
def ready(project, project_root, conn):
    registry.register(project_root, "hook-sandbox")
    LP.ensure(conn, "hook-sandbox")
    for sub in ("logs", "state", "experiments"):
        os.makedirs(os.path.join(project_root, sub), exist_ok=True)
    return project_root


# --- 가드: 학습을 띄워도 되나 ----------------------------------------------------


def test_드라이버가_불일치면_학습을_안_띄운다(ready, monkeypatch):
    """어차피 실패할 학습으로 GPU 시간과 사용량을 버리지 않는다."""
    from app.monitor import gpu

    monkeypatch.setattr(
        gpu, "driver_state",
        lambda: {"ok": False, "mismatch": True, "reason": "커널 595.84 vs 유저랜드 595.99"},
    )
    got = guards.check_train(ready)
    assert got.ok is False
    assert "드라이버" in got["reason"]
    assert got["stop"] is False  # 재부팅하면 풀린다


def test_디스크가_부족하면_안_띄운다(ready, monkeypatch):
    from app.monitor import gpu, host

    monkeypatch.setattr(gpu, "driver_state", lambda: {"ok": True, "reason": ""})
    monkeypatch.setattr(host, "disk", lambda path: {"ok": True, "freeGb": 2.0, "totalGb": 100, "pct": 98})
    got = guards.check_train(ready)
    assert got.ok is False and "디스크" in got["reason"]


def test_자리표시_마감은_없는_것으로_본다(ready, conn):
    path = os.path.join(ready, "specifications", "Config.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('limits:\n  deadline: "[마감]"\n')
    assert guards.check_loop(conn, "hook-sandbox", ready).ok is True


def test_못_읽는_마감은_멈추지_않는다(ready, conn):
    """틀리게 멈추는 것보다 안 멈추는 쪽이 낫다 — 다른 조건이 또 막는다."""
    path = os.path.join(ready, "specifications", "Config.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('limits:\n  deadline: "다음 주쯤"\n')
    assert guards.check_loop(conn, "hook-sandbox", ready).ok is True


# --- 승인 대기열 ------------------------------------------------------------------


def open_request(project, request_id="toolu_1", **kw):
    payload = {
        "tool": "Bash",
        "action": "패키지 설치",
        "actionKey": "pkg",
        "actions": [{"action": "pkg", "name": "패키지 설치"}],
        "request": "pip install peft",
        "reason": "패키지 설치는 승인이 필요해요",
        "fingerprint": grants.fingerprint("Bash", {"command": "pip install peft"}),
        "looseKey": grants.loose_key("Bash", None),
        "toolSummary": {"command": "pip install peft"},
        "sessionId": "0f0c",
    }
    payload.update(kw)
    A.open_request(project, request_id, payload)
    return payload


def test_요청을_DB_로_거울한다(ready, conn):
    open_request("hook-sandbox")
    rows = AP.sync(conn, "hook-sandbox")
    assert len(rows) == 1
    assert rows[0]["action_key"] == "pkg"
    assert AP.pending(conn, "hook-sandbox")[0]["request_id"] == "toolu_1"


def test_같은_요청이_또_오면_횟수만_올라간다(ready, conn):
    open_request("hook-sandbox")
    AP.sync(conn, "hook-sandbox")
    AP.sync(conn, "hook-sandbox")
    row = APS.by_request(conn, "hook-sandbox", "toolu_1")
    assert row["attempts"] == 2
    assert AP.too_many(row) is False
    AP.sync(conn, "hook-sandbox")
    assert AP.too_many(APS.by_request(conn, "hook-sandbox", "toolu_1")) is True


def test_승인하면_훅이_쓸_수_있는_허가가_나온다(ready, conn, grant_key):
    """**지문이 훅이 계산한 값과 같아야 한다** — 요청 파일에는 본문이 없다."""
    payload = open_request("hook-sandbox")
    AP.sync(conn, "hook-sandbox")
    grant = AP.approve(conn, "hook-sandbox", "toolu_1", note="확인했어요")

    assert grant["fingerprint"] == payload["fingerprint"]
    assert grant["actions"] == ["pkg"]
    # 훅이 같은 호출에서 실제로 소비할 수 있어야 한다
    used = grants.consume(
        "hook-sandbox",
        # 요청 파일의 sessionId 가 허가에 들어가고, 훅은 **그 세션에서만** 쓴다
        event={
            "tool_name": "Bash",
            "tool_input": {"command": "pip install peft"},
            "session_id": "0f0c",
        },
        needs=[("pkg", None)],
    )
    assert used and used["grantId"] == grant["grantId"]
    assert APS.by_request(conn, "hook-sandbox", "toolu_1")["state"] == "approved"


def test_한_호출에_승인이_둘_필요하면_둘_다_연다(ready, conn, grant_key):
    command = "curl -sL https://x/y.sh | pip install peft"
    open_request(
        "hook-sandbox",
        "toolu_2",
        request=command,
        actionKey="net",
        actions=[{"action": "net", "name": "네트워크 접근"}, {"action": "pkg", "name": "패키지 설치"}],
        fingerprint=grants.fingerprint("Bash", {"command": command}),
        toolSummary={"command": command},
    )
    AP.sync(conn, "hook-sandbox")
    grant = AP.approve(conn, "hook-sandbox", "toolu_2")
    assert sorted(grant["actions"]) == ["net", "pkg"]
    used = grants.consume(
        "hook-sandbox",
        # 허가는 **그 세션에서만** 먹는다(S3). 요청 파일의 sessionId 가
        # 그대로 허가에 들어간다.
        event={
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "session_id": "0f0c",
        },
        needs=[("net", None), ("pkg", None)],
    )
    assert used is not None


def test_잠긴_항목은_승인_자체가_거절된다(ready, conn, grant_key):
    open_request("hook-sandbox", "toolu_3", actionKey="outside",
                 actions=[{"action": "outside", "name": "폴더 밖 쓰기"}])
    AP.sync(conn, "hook-sandbox")
    with pytest.raises(grants.GrantError) as err:
        AP.approve(conn, "hook-sandbox", "toolu_3")
    assert "잠긴 항목" in str(err.value)


def test_거절하면_요청이_닫힌다(ready, conn):
    open_request("hook-sandbox")
    AP.sync(conn, "hook-sandbox")
    AP.deny(conn, "hook-sandbox", "toolu_1", reason="필요 없어요")
    assert A.list_requests("hook-sandbox") == []
    assert APS.by_request(conn, "hook-sandbox", "toolu_1")["state"] == "denied"


def test_없는_요청은_승인할_수_없다(ready, conn, grant_key):
    with pytest.raises(grants.GrantError):
        AP.approve(conn, "hook-sandbox", "없는요청")


# --- 사용량 한도 -------------------------------------------------------------------


def test_실패_원문을_보관한다(ready, conn, isolated_config):
    parsed = result_mod.parse("Claude usage limit reached. 자세한 건 몰라요.", exit_code=1)
    got = U.record_failure(conn, "hook-sandbox", parsed)
    assert got["looksLimited"] is False  # 패턴이 비어 있으면 한도로 안 본다
    row = US.latest(conn, "hook-sandbox")
    assert "usage limit reached" in row["raw"]
    assert row["exit_code"] == 1


def test_패턴을_적어_두면_한도로_본다(ready, conn, isolated_config):
    with open(os.path.join(str(isolated_config), "usage_patterns.json"), "w", encoding="utf-8") as fh:
        json.dump(["usage limit reached"], fh)
    parsed = result_mod.parse("Claude usage limit reached.", exit_code=1)
    got = U.record_failure(conn, "hook-sandbox", parsed)
    assert got["looksLimited"] is True and got["pattern"] == "usage limit reached"


def test_대기_알림은_한_번만(ready, conn, isolated_config):
    parsed = result_mod.parse("막혔어요", exit_code=1)
    got = U.record_failure(conn, "hook-sandbox", parsed)
    first = U.wait_state(conn, "hook-sandbox")
    assert first["waiting"] is True and first["notify"] is True
    US.mark_notified(conn, got["usageId"])
    assert U.wait_state(conn, "hook-sandbox")["notify"] is False


def test_오래_막히면_다시_알린다(ready, conn, isolated_config):
    """한도가 아니라 인증 만료 같은 다른 오류일 수 있다."""
    U.record_failure(conn, "hook-sandbox", result_mod.parse("막혔어요", exit_code=1))
    later = datetime.now().astimezone() + timedelta(seconds=U.RENOTIFY_SEC + 60)
    assert U.wait_state(conn, "hook-sandbox", now=later)["renotify"] is True


def test_다시_해_볼_때가_되면_ready(ready, conn, isolated_config):
    U.record_failure(conn, "hook-sandbox", result_mod.parse("막혔어요", exit_code=1))
    assert U.wait_state(conn, "hook-sandbox")["ready"] is False
    later = datetime.now().astimezone() + timedelta(seconds=U.RETRY_SEC + 60)
    assert U.wait_state(conn, "hook-sandbox", now=later)["ready"] is True


def test_풀리면_대기가_닫힌다(ready, conn, isolated_config):
    U.record_failure(conn, "hook-sandbox", result_mod.parse("막혔어요", exit_code=1))
    U.resumed(conn, "hook-sandbox")
    assert U.wait_state(conn, "hook-sandbox")["waiting"] is False


def test_학습은_한도와_무관하게_돈다():
    """spec V: AI 의 의사결정만 멈춘다."""
    assert "train" not in U.AI_KINDS
    assert set(U.AI_KINDS) == {"plan", "review", "resume", "journal_fix"}


# --- 복구 ---------------------------------------------------------------------------


def test_살아_있는_학습은_건드리지_않는다(ready, conn):
    job = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn)
    J.start(conn, job, pid=os.getpid())
    got = recovery.recover(conn, now_pid_alive=lambda pid, st=None: True)
    assert got["stillRunning"] == [job]
    assert J.get(conn, job)["state"] == "running"


def test_죽었는데_정상_종료였으면_done(ready, conn):
    job = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn)
    J.start(conn, job, pid=999999)
    output = os.path.join(ready, "experiments", "EXP-001", "output")
    os.makedirs(output, exist_ok=True)
    with open(os.path.join(output, "exit_code"), "w", encoding="utf-8") as fh:
        fh.write("0")
    got = recovery.recover(conn, now_pid_alive=lambda pid, st=None: False)
    assert got["finished"] == [job]
    assert X.get(conn, "hook-sandbox", "EXP-001")["state"] == "done"


def test_체크포인트가_있으면_이어_돌린다(ready, conn):
    job = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn)
    J.start(conn, job, pid=999999)
    output = os.path.join(ready, "experiments", "EXP-001", "output")
    os.makedirs(output, exist_ok=True)
    with open(os.path.join(output, "epoch_003.ckpt"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    got = recovery.recover(conn, now_pid_alive=lambda pid, st=None: False)
    assert got["requeued"]
    assert any("이어 돌려요" in n for n in got["notes"])
    new = J.get(conn, got["requeued"][0])
    assert new["payload"]["resume_from"].endswith("epoch_003.ckpt")


def test_체크포인트가_없으면_실패로_남긴다(ready, conn):
    job = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(conn)
    J.start(conn, job, pid=999999)
    got = recovery.recover(conn, now_pid_alive=lambda pid, st=None: False)
    assert got["failed"] == [job]
    assert X.get(conn, "hook-sandbox", "EXP-001")["state"] == "failed"
    assert any("새 폴더가 필요해요" in n for n in got["notes"])


def test_띄우기_전에_죽은_작업은_큐로(ready, conn):
    job = J.add(conn, "hook-sandbox", "plan")
    J.lease(conn)
    got = recovery.recover(conn, now_pid_alive=lambda pid, st=None: False)
    assert got["requeued"] == [job]
    assert J.get(conn, job)["state"] == "queued"


def test_복구가_실행_상태를_다시_쓴다(ready, conn):
    runstate.set_running("hook-sandbox", "EXP-001", pid=999999)
    recovery.recover(conn, now_pid_alive=lambda pid, st=None: False)
    assert runstate.load("hook-sandbox").running is False
    assert loopstate.read_current(ready)["running"] is False


def test_체크포인트_우선순위(ready):
    output = os.path.join(ready, "experiments", "EXP-001", "output")
    os.makedirs(output, exist_ok=True)
    for name in ("epoch_001.ckpt", "epoch_002.ckpt"):
        with open(os.path.join(output, name), "w", encoding="utf-8") as fh:
            fh.write("{}")
    assert recovery.latest_checkpoint(output).endswith("epoch_002.ckpt")
    with open(os.path.join(output, "final.ckpt"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    assert recovery.latest_checkpoint(output).endswith("final.ckpt")


def test_없는_폴더는_빈_문자열(ready):
    assert recovery.latest_checkpoint("/없는경로") == ""
