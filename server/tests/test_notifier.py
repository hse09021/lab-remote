"""Discord 알림 — 임베드·중복 제거·재시도.

평문 1900자 자르기 대신 임베드 필드로 보내 **긴 내용이 안 잘리게** 한다.
그리고 **전송 실패가 호출부를 멈추지 않는다.**
"""

import pytest

from app import notifier
from app.store import notifications as N


class Poster:
    """보낸 것을 기록하는 가짜 전송기."""

    def __init__(self, *results):
        self.results = list(results) or [{"sent": True, "status": 204}]
        self.calls = []

    def __call__(self, payload, kind=""):
        self.calls.append((payload, kind))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


@pytest.fixture()
def slept():
    out = []
    return out


# --- 임베드 ------------------------------------------------------------------


def test_임베드_모양():
    payload = notifier.build(
        "approval",
        project="hook-sandbox",
        title="승인이 필요해요",
        body="패키지 설치는 승인이 필요해요: pip install peft",
        fields=[("훅 사유", "길지 않은 사유"), ("승인", "labremote approve …")],
    )
    embed = payload["embeds"][0]
    assert embed["title"] == "승인이 필요해요 · hook-sandbox"
    assert embed["color"] == notifier.COLORS["approval"]
    assert [f["name"] for f in embed["fields"]] == ["훅 사유", "승인"]


def test_모르는_종류는_거절한다():
    with pytest.raises(ValueError):
        notifier.build("그런알림없음", title="x")


def test_긴_사유는_잘리지_않고_나뉜다():
    """①의 숙제. 평문 1900자 자르기로는 사유가 잘렸다."""
    reason = "사" * 3000
    payload = notifier.build("approval", title="승인", fields=[("훅 사유", reason)])
    fields = payload["embeds"][0]["fields"]
    assert len(fields) == 3  # 1024자씩 나뉜다
    assert "".join(f["value"] for f in fields) == reason


# --- 보내기 ------------------------------------------------------------------


def test_보내면_sent_로_적힌다(conn, monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster()
    result = notifier.send(
        conn, "failure", project="p", title="EXP-001 이 실패했어요", poster=poster
    )
    assert result["sent"] is True
    assert N.get(conn, result["id"])["state"] == "sent"
    assert len(poster.calls) == 1


def test_쿨다운_안에서는_한_번만_보낸다(conn, monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster()
    kw = dict(project="p", subject="EXP-001", title="EXP-001 이 실패했어요", poster=poster)
    first = notifier.send(conn, "failure", now_ts=1000.0, **kw)
    second = notifier.send(conn, "failure", now_ts=1001.0, **kw)
    assert first["sent"] is True
    assert second["suppressed"] is True
    assert len(poster.calls) == 1  # 두 번째는 전송 자체를 안 한다


def test_승인_알림은_묵히지_않는다(conn, monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster()
    kw = dict(project="p", subject="toolu_1", title="승인이 필요해요", poster=poster)
    assert notifier.send(conn, "approval", now_ts=1000.0, **kw)["sent"] is True
    assert notifier.send(conn, "approval", now_ts=1000.5, **kw)["sent"] is True
    assert len(poster.calls) == 2


def test_웹훅이_없으면_보내지_않고_실패로_적는다(conn, monkeypatch):
    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    result = notifier.send(conn, "failure", project="p", title="x")
    assert result["sent"] is False
    assert N.get(conn, result["id"])["state"] == "failed"


# --- 재시도 ------------------------------------------------------------------


def test_429_는_Retry_After_만큼_기다린다(conn, monkeypatch, slept):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster(
        {"sent": False, "status": 429, "retryAfter": "2"}, {"sent": True, "status": 204}
    )
    result = notifier.send(
        conn, "failure", project="p", title="x", poster=poster, sleep=slept.append
    )
    assert result["sent"] is True
    assert slept == [2.0]


def test_5xx_는_점점_길게_기다리고_포기한다(conn, monkeypatch, slept):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster({"sent": False, "status": 503, "reason": "서버가 아파요"})
    result = notifier.send(
        conn, "failure", project="p", title="x", poster=poster, sleep=slept.append
    )
    assert result["sent"] is False
    assert len(poster.calls) == notifier.MAX_ATTEMPTS
    assert slept == list(notifier.BACKOFF_SEC[: notifier.MAX_ATTEMPTS - 1])
    assert N.get(conn, result["id"])["http_status"] == 503


def test_4xx_는_다시_시도하지_않는다(conn, monkeypatch, slept):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster({"sent": False, "status": 404, "reason": "웹훅이 없어요"})
    notifier.send(conn, "failure", project="p", title="x", poster=poster, sleep=slept.append)
    assert len(poster.calls) == 1
    assert slept == []


def test_터무니없는_Retry_After_에_안_잡힌다(conn, monkeypatch, slept):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")
    poster = Poster({"sent": False, "status": 429, "retryAfter": "99999"})
    notifier.send(conn, "failure", project="p", title="x", poster=poster, sleep=slept.append)
    assert all(wait <= 60 for wait in slept), slept


def test_전송이_터져도_큐를_멈추지_않는다(conn, monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/x")

    def boom(payload, kind=""):
        raise RuntimeError("그물이 끊겼어요")

    result = notifier.send(conn, "failure", project="p", title="x", poster=boom)
    assert result["sent"] is False
    assert "그물이 끊겼어요" in result["reason"]


def test_종류별_채널로_보낸다(conn, monkeypatch):
    from app import config

    config.save({"webhook": "https://discord.test/기본", "routes": {"approval": "https://discord.test/승인"}})
    poster = Poster()
    result = notifier.send(conn, "approval", project="p", title="승인", poster=poster)
    assert result["sent"] is True
    assert poster.calls[0][1] == "approval"
    # 🔑 DB 에는 **채널 이름만** — 웹훅 주소는 0600 파일에만 둔다 (PLAN 1.7)
    row = N.get(conn, result["id"])
    assert row["route"] == "routes.approval"
    assert "discord.test" not in str(dict(row))


# --- 🔑 Discord 가 파이썬 기본 User-Agent 를 막는다 (실측 2026-11-05) --------


def test_고정_User_Agent_를_보낸다(monkeypatch):
    """같은 URL 에 `curl` 은 204 인데 `urllib` 기본값은 403 이었다.

    `HTTP Error 403: Forbidden` 때문에 **승인 알림이 한 건도 안 갔다.**
    배관은 돌고 있었고(훅이 전송을 시도하고 결과를 기록했다) 헤더만
    문제였다 — 조용한 실패였다.
    """
    from app import notify

    seen = {}

    class FakeResp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout=None):
        seen["headers"] = dict(request.headers)
        seen["url"] = request.full_url
        return FakeResp()

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    got = notify.send_payload({"content": "x"})

    assert got["sent"] is True and got["status"] == 204
    # urllib 은 헤더 이름을 Title-Case 로 바꾼다
    assert seen["headers"].get("User-agent") == notify.USER_AGENT
    assert seen["headers"].get("Content-type") == "application/json"


def test_User_Agent_에_개인_정보가_없다():
    """웹훅은 Discord 서버로 나가는 요청이다. 이메일·호스트 이름을 싣지 않는다."""
    import os
    import socket

    from app import notify

    text = notify.USER_AGENT
    assert text == "lab.remote-notifier/1.0"
    for leak in (os.path.expanduser("~"), socket.gethostname(), "@", "hse09021"):
        assert leak not in text, leak
