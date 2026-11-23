"""예약 — 다음 시각 · GPU 기다리기 · 놓침 · 명령/에이전트 · API."""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import inbox, main, schedules

H = {"X-Lab-Remote": "1"}


def ts(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi).timestamp()


def test_다음_시각():
    at = ts(2026, 11, 23, 14)  # 월요일 14:00
    assert schedules.next_after(at, "once", ts(2026, 11, 23, 9)) == at
    assert schedules.next_after(at, "once", ts(2026, 11, 23, 15)) is None
    assert schedules.next_after(at, "daily", ts(2026, 11, 23, 15)) == ts(2026, 11, 24, 14)
    assert schedules.next_after(at, "daily", ts(2026, 11, 26, 13, 59)) == ts(2026, 11, 26, 14)
    assert schedules.next_after(at, "weekly", ts(2026, 11, 23, 15)) == ts(2026, 11, 30, 14)
    assert datetime.fromtimestamp(schedules.next_after(at, "weekly", ts(2026, 12, 10, 0))).weekday() == 0


def _job(**kw):
    base = {"name": "r32 학습", "kind": "command", "project": "demo", "command": "python train.py", "at": 0, "repeat": "once"}
    return {**base, **kw}


def test_만들기_검사(conn, project):
    now = ts(2026, 11, 23, 9)
    with pytest.raises(schedules.ScheduleError, match="지난 시각"):
        schedules.create(conn, _job(at=ts(2026, 11, 23, 8)), now=now)
    with pytest.raises(schedules.ScheduleError, match="명령"):
        schedules.create(conn, _job(at=ts(2026, 11, 23, 14), command=" "), now=now)
    with pytest.raises(schedules.ScheduleError, match="요청"):
        schedules.create(conn, _job(at=ts(2026, 11, 23, 14), kind="agent"), now=now)
    with pytest.raises(Exception):
        schedules.create(conn, _job(at=ts(2026, 11, 23, 14), project="nope"), now=now)
    got = schedules.create(conn, _job(at=ts(2026, 11, 23, 14), repeat="weekly"), now=now)
    assert got["nextAt"] == ts(2026, 11, 23, 14) and got["repeatLabel"] == "매주 월"


def run(coro):
    return asyncio.run(coro)


def test_GPU_가_바쁘면_기다렸다가_한_번만_알리고_시작(conn, project):
    at = ts(2026, 11, 23, 14)
    job = schedules.create(conn, _job(at=at), now=at - 60)
    started = []
    busy = {"v": True}

    def start(j):
        started.append(j["id"])
        return {"id": "EXP-001"}

    assert run(schedules.tick(conn, now=at + 1, busy=lambda: busy["v"], start_run=start)) == [{"id": job["id"], "did": "waiting"}]
    assert run(schedules.tick(conn, now=at + 30, busy=lambda: busy["v"], start_run=start))[0]["did"] == "waiting"
    # 한참 기다려도 "놓침"이 아니다 — 기다리는 중이니까
    busy["v"] = False
    got = run(schedules.tick(conn, now=at + 3600, busy=lambda: busy["v"], start_run=start))
    assert got == [{"id": job["id"], "did": "started", "run": "EXP-001"}]
    assert started == [job["id"]]
    titles = [i["title"] for i in inbox.items(conn)]
    assert titles.count("예약 · r32 학습 기다리는 중") == 1 and "예약 · r32 학습 시작" in titles
    after = schedules.get(conn, job["id"])
    assert after["nextAt"] is None and after["lastResult"] == "EXP-001 시작"
    assert after["enabled"] is False  # 한 번짜리는 돌고 나면 꺼진다
    assert run(schedules.tick(conn, now=at + 3700, busy=lambda: False, start_run=start)) == []  # 한 번짜리는 끝


def test_서버가_꺼져_있던_사이_지난_예약은_놓침(conn, project):
    at = ts(2026, 11, 23, 3)
    job = schedules.create(conn, _job(at=at, repeat="daily", name="야간 평가"), now=at - 60)
    got = run(schedules.tick(conn, now=at + 3 * 3600, busy=lambda: False, start_run=lambda j: {"id": "X"}))
    assert got == [{"id": job["id"], "did": "missed"}]
    after = schedules.get(conn, job["id"])
    assert "놓쳤어요" in after["lastResult"] and after["nextAt"] == ts(2026, 11, 24, 3)


def test_꺼둔_예약은_안_돈다(conn, project):
    at = ts(2026, 11, 23, 14)
    job = schedules.create(conn, _job(at=at, repeat="daily"), now=at - 60)
    schedules.update(conn, job["id"], {"enabled": False}, now=at - 30)
    assert run(schedules.tick(conn, now=at + 1, busy=lambda: False, start_run=lambda j: {"id": "X"})) == []


def test_에이전트_예약은_세션을_연다(conn, project):
    at = ts(2026, 11, 23, 10)
    job = schedules.create(conn, _job(at=at, kind="agent", prompt="이번 주 결과를 정리해 줘", command=""), now=at - 60)
    opened = []

    async def open_session(j):
        opened.append(j["prompt"])
        return {"id": "s-0000000001"}

    got = run(schedules.tick(conn, now=at + 1, busy=lambda: True, start_session=open_session))
    assert got == [{"id": job["id"], "did": "session", "session": "s-0000000001"}]  # GPU 바빠도 기다리지 않는다
    assert opened == ["이번 주 결과를 정리해 줘"]


def test_시작에_실패하면_처리할_것으로(conn, project):
    at = ts(2026, 11, 23, 14)
    schedules.create(conn, _job(at=at), now=at - 60)

    def boom(j):
        raise RuntimeError("conda 환경이 없어요")

    got = run(schedules.tick(conn, now=at + 1, busy=lambda: False, start_run=boom))
    assert got[0]["did"] == "error" and inbox.badge(conn) == 1


def test_API(project, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    at = (datetime.now() + timedelta(hours=2)).timestamp()
    r = client.post("/api/schedules", json=_job(at=at, repeat="daily"), headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert client.post("/api/schedules", json=_job(at=at - 86400), headers=H).status_code == 400
    assert client.put(f"/api/schedules/{sid}", json={"enabled": False}, headers=H).json()["enabled"] is False
    assert [x["id"] for x in client.get("/api/schedules").json()["schedules"]] == [sid]
    assert client.get("/api/schedules/clock").json()["interval"] == 15
    assert client.delete(f"/api/schedules/{sid}", headers=H).json() == {"ok": True}
