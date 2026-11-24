"""알림 규칙 · 조용한 시간 · Inbox · 웹훅 주소가 새지 않는지."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import alerts, config, inbox, main

URL = "https://discord.com/api/webhooks/123/secret-token"
H = {"X-Lab-Remote": "1"}


def ok_poster(payload, kind=""):
    return {"sent": True, "status": 204}


def test_조용한_시간(conn):
    q = {"on": True, "start": "23:00", "end": "07:00"}
    assert alerts.in_quiet(q, datetime(2026, 1, 1, 2, 0))
    assert not alerts.in_quiet(q, datetime(2026, 1, 1, 12, 0))
    assert not alerts.in_quiet({**q, "on": False}, datetime(2026, 1, 1, 2, 0))
    assert alerts.in_quiet({"on": True, "start": "09:00", "end": "10:00"}, datetime(2026, 1, 1, 9, 30))


def test_규칙대로_보낸다(conn):
    config.set_webhook(URL)
    noon = datetime(2026, 1, 1, 12, 0)
    night = datetime(2026, 1, 1, 3, 0)
    assert alerts.post(conn, "run", "done", "a 완료", poster=ok_poster, now=noon)["sent"] == "Discord 보냄"
    # 조용한 시간에는 실패만
    assert alerts.post(conn, "run", "done", "b 완료", poster=ok_poster, now=night)["sent"] == "보내지 않음 · 조용한 시간"
    assert alerts.post(conn, "run", "fail", "c 실패", act=True, poster=ok_poster, now=night)["sent"] == "Discord 보냄"
    alerts.save_rules({"done": False})
    assert alerts.post(conn, "run", "done", "d 완료", poster=ok_poster, now=noon)["sent"] == "보내지 않음 · 비활성화된 알림"
    # 규칙이 없으면 Inbox에만
    assert alerts.post(conn, "run", None, "e 중지함", poster=ok_poster)["sent"] == ""
    assert inbox.badge(conn) == 1
    assert inbox.counts(conn)["run"] == {"total": 5, "unread": 5}


def test_주소가_없으면_조용히_Inbox_에만(conn):
    # 낮 시각으로 고정 — 밤(조용한 시간)에 돌리면 그 사유가 먼저 나와요
    got = alerts.post(conn, "sys", "sys", "VRAM", poster=ok_poster, now=datetime(2026, 1, 1, 12, 0))
    assert got["sent"] == ""
    assert inbox.items(conn)[0]["title"] == "VRAM"


@pytest.mark.parametrize(
    "bad",
    ["http://discord.com/api/webhooks/1/x", "https://evil.example/api/webhooks/1/x",
     "https://discord.com/other", "https://u:p@discord.com/api/webhooks/1/x", ""],
)
def test_웹훅_주소_검사(bad):
    with pytest.raises(ValueError) as err:
        config.set_webhook(bad)
    assert "evil" not in str(err.value) and "u:p" not in str(err.value)


def test_읽음(conn):
    a = inbox.add(conn, "run", "a", act=True)
    inbox.add(conn, "sys", "b")
    assert inbox.mark_read(conn, [a]) == 1
    assert inbox.badge(conn) == 0
    assert inbox.mark_read(conn) == 1
    assert inbox.items(conn, unread=True) == []


def test_API_는_주소를_내보내지_않는다(tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    assert client.put("/api/notify/webhook", json={"url": "https://evil.example/x"}, headers=H).status_code == 400
    r = client.put("/api/notify/webhook", json={"url": URL}, headers=H)
    assert r.status_code == 200
    body = json.dumps(r.json()) + json.dumps(client.get("/api/notify").json())
    assert "secret-token" not in body and "123" not in body
    assert r.json()["webhook"]["set"] is True and r.json()["webhook"]["masked"] == "https://discord.com/••••"
    assert r.json()["webhook"]["private"] is True
    r = client.put("/api/notify/rules", json={"rules": {"pr": True}}, headers=H)
    assert [x["on"] for x in r.json()["rules"] if x["key"] == "pr"] == [True]
    assert client.put("/api/notify/quiet", json={"on": True, "start": "25:00", "end": "07:00"}, headers=H).status_code == 400
    assert client.delete("/api/notify/webhook", headers=H).json()["webhook"]["set"] is False
    assert client.post("/api/notify/test", headers=H).status_code == 400


def test_Inbox_와_Dashboard_API(tmp_path, project):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    from app import db

    with db.open_db() as c:
        inbox.add(c, "run", "EXP-001 실패", act=True, project="demo")
        inbox.add(c, "sys", "VRAM")
    body = client.get("/api/inbox").json()
    assert body["badge"] == 1 and len(body["items"]) == 2
    assert client.get("/api/inbox", params={"kind": "sys"}).json()["items"][0]["title"] == "VRAM"
    assert client.get("/api/inbox", params={"kind": "nope"}).status_code == 400
    assert client.post("/api/inbox/read", json={}, headers=H).json() == {"changed": 2}
    assert client.get("/api/inbox/badge").json() == {"badge": 0}
    dash = client.get("/api/dashboard").json()
    assert dash["projects"] == 1 and dash["runs"]["running"] == [] and dash["agents"] is None


def test_PR_리뷰가_바뀌면_알려요(conn):
    from app import inbox, watch

    def feed(state):
        return lambda: {"available": True, "items": [
            {"project": "demo", "number": 7, "title": "lr 낮추기", "branch": "exp/lr", "state": state, "ci": "", "url": "https://github.com/me/demo/pull/7"},
        ]}

    # 처음 본 PR은 기억만
    assert watch.check_prs(conn, feed=feed("리뷰 기다림")) == []
    assert watch.check_prs(conn, feed=feed("리뷰 기다림")) == []
    got = watch.check_prs(conn, feed=feed("변경 요청"))
    assert [x["number"] for x in got] == [7]
    items = inbox.items(conn, kind="pr")
    assert items[0]["title"].startswith("PR #7 변경 요청")
    # 같은 상태는 다시 알리지 않아요
    assert watch.check_prs(conn, feed=feed("변경 요청")) == []
    # gh가 없으면 아무것도 안 해요
    assert watch.check_prs(conn, feed=lambda: {"available": False, "items": []}) == []
