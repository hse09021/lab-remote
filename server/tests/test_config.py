"""데이터 폴더의 Discord 설정 (`<data>/discord.json`, 권한 0600).

v3는 데이터 폴더 밖(`~/.config/labremote/`)에 설정을 두지 않는다
(PLAN 1장 · 3장). 웹훅 주소는 **어디에도 원문으로 나가지 않는다.**
"""

import json
import os

import pytest

from app import config, notify

URL = "https://discord.com/api/webhooks/123/abc"


def test_설정이_없으면_빈_dict():
    assert config.load() == {}
    assert config.discord_webhook() == ""
    assert config.route_label() == ""


def test_깨진_파일도_던지지_않는다():
    path = config.discord_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("깨진 JSON")
    assert config.load() == {}


def test_데이터_폴더_안에_있다(isolated_data):
    assert config.discord_path() == os.path.join(str(isolated_data), "discord.json")


def test_웹훅을_넣으면_0600_으로_쓴다():
    """만들 때부터 0600 이어야 한다 — 쓰고 나서 chmod 하면 그 사이가 열린다."""
    old = os.umask(0o000)  # umask가 느슨해도
    try:
        path = config.set_webhook(URL)
    finally:
        os.umask(old)
    assert config.mode_of(path) == 0o600
    assert config.is_private(path)
    assert config.discord_webhook() == URL
    assert config.route_label() == "default"


def test_빈_주소는_거절한다():
    with pytest.raises(ValueError):
        config.set_webhook("   ")


def test_끊으면_주소만_지운다():
    config.save({"webhook": URL, "cooldownSec": {"failure": 60}})
    config.clear_webhook()
    assert config.discord_webhook() == ""
    assert config.cooldown_sec("failure") == 60  # 다른 칸은 그대로
    assert config.is_private(config.discord_path())


def test_가린_주소에_비밀이_없다():
    config.set_webhook(URL)
    masked = config.masked_webhook()
    assert masked == "https://discord.com/••••"
    assert "123" not in masked and "abc" not in masked
    assert config.masked_webhook("") == ""
    assert config.masked_webhook("주소가-아님") == "••••"


def test_종류별_채널이_기본보다_먼저():
    config.save({"webhook": URL, "routes": {"approval": "https://discord.test/승인"}})
    assert config.discord_webhook("approval") == "https://discord.test/승인"
    assert config.discord_webhook("failure") == URL
    assert config.route_label("approval") == "routes.approval"
    assert config.route_label("failure") == "default"


def test_환경_변수가_설정_파일을_이긴다(monkeypatch):
    config.set_webhook(URL)
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/env")
    assert config.discord_webhook() == "https://discord.test/env"
    assert config.route_label() == "env"


def test_notify_도_설정_파일을_본다():
    config.set_webhook(URL)
    assert notify.webhook_url() == URL


def test_쿨다운_기본값과_덮어쓰기():
    assert config.cooldown_sec("approval") == 0
    assert config.cooldown_sec("모르는-종류") == 300
    config.save({"cooldownSec": {"failure": 10, "gpu": True}})
    assert config.cooldown_sec("failure") == 10
    # true를 1로 읽지 않는다
    assert config.cooldown_sec("gpu") == config.COOLDOWN_DEFAULTS["gpu"]


def test_v1_서명_키와_한도_패턴은_없다():
    for name in ("grant_key", "ensure_grant_key", "usage_patterns", "tokens", "config_dir"):
        assert not hasattr(config, name), name


def test_전송_실패_사유에_주소가_안_섞인다(monkeypatch):
    """`URLError`의 메시지에는 주소가 섞일 수 있다 — 이름만 싣는다."""
    import urllib.error
    import urllib.request

    def boom(*a, **k):
        raise urllib.error.URLError(f"cannot reach {URL}")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    got = notify.send_payload({"content": "x"}, url=URL)
    assert got["sent"] is False
    assert URL not in json.dumps(got, ensure_ascii=False)
