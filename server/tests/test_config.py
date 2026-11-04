"""`~/.config/labremote/` 읽기.

웹훅 주소와 **허가 서명 키**가 여기 있다. 프로젝트 폴더 밖이고 이미
`SECRET_FILES` 라 Claude 가 읽기까지 막힌다.
"""

import json
import os

from app import config, notify


def write_toml(folder, body):
    path = os.path.join(str(folder), "config.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def test_설정이_없으면_빈_dict(isolated_config):
    assert config.load() == {}
    assert config.discord_webhook() == ""


def test_깨진_toml_도_던지지_않는다(isolated_config):
    write_toml(isolated_config, "[discord\n이건 toml 이 아니에요")
    assert config.load() == {}
    assert config.discord_webhook() == ""


def test_웹훅을_읽는다(isolated_config):
    write_toml(isolated_config, '[discord]\nwebhook = "https://discord.test/기본"\n')
    assert config.discord_webhook() == "https://discord.test/기본"


def test_종류별_채널이_기본보다_먼저(isolated_config):
    write_toml(
        isolated_config,
        '[discord]\nwebhook = "https://discord.test/기본"\n'
        '[discord.routes]\napproval = "https://discord.test/승인"\n',
    )
    assert config.discord_webhook("approval") == "https://discord.test/승인"
    assert config.discord_webhook("failure") == "https://discord.test/기본"


def test_환경_변수가_설정_파일을_이긴다(isolated_config, monkeypatch):
    """①의 동작과 기존 시험을 그대로 두기 위한 우선순위다."""
    write_toml(isolated_config, '[discord]\nwebhook = "https://discord.test/파일"\n')
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.test/환경")
    assert config.discord_webhook() == "https://discord.test/환경"
    assert config.discord_webhook("approval") == "https://discord.test/환경"
    assert notify.webhook_url() == "https://discord.test/환경"


def test_notify_도_설정_파일을_본다(isolated_config, monkeypatch):
    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    write_toml(
        isolated_config,
        '[discord.routes]\nfailure = "https://discord.test/실패"\n',
    )
    assert notify.webhook_url("failure") == "https://discord.test/실패"
    assert notify.webhook_url("start") == ""


def test_쿨다운_기본값과_덮어쓰기(isolated_config):
    assert config.cooldown_sec("approval") == 0  # 승인은 묵히지 않는다
    assert config.cooldown_sec("failure") == 300
    assert config.cooldown_sec("처음보는종류") == 300
    write_toml(isolated_config, "[notify.cooldown_sec]\nfailure = 60\n")
    assert config.cooldown_sec("failure") == 60


def test_쿨다운이_불리언이면_기본값(isolated_config):
    """TOML 의 true 를 1초로 읽으면 알림이 쏟아진다."""
    write_toml(isolated_config, "[notify.cooldown_sec]\nfailure = true\n")
    assert config.cooldown_sec("failure") == 300


# --- 허가 서명 키 ------------------------------------------------------------


def test_서명_키가_없으면_None(isolated_config):
    assert config.grant_key() is None


def test_서명_키는_0600_으로_만든다(isolated_config):
    path = config.ensure_grant_key()
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert config.is_private(path)
    assert config.grant_key()


def test_서명_키를_다시_만들지_않는다(isolated_config):
    path = config.ensure_grant_key()
    before = config.grant_key()
    assert config.ensure_grant_key() == path
    assert config.grant_key() == before


def test_권한이_넓으면_좁혀_준다(isolated_config):
    path = config.ensure_grant_key()
    os.chmod(path, 0o644)
    assert config.is_private(path) is False
    config.ensure_grant_key()
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_한도_패턴은_비어_있는_게_기본(isolated_config):
    """실측 전까지 비워 둔다. 틀린 패턴은 다른 오류를 한도로 오인한다."""
    assert config.usage_patterns() == []


def test_한도_패턴을_읽는다(isolated_config):
    path = os.path.join(str(isolated_config), "usage_patterns.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"patterns": ["usage limit reached", "5-hour limit"]}, fh)
    assert config.usage_patterns() == ["usage limit reached", "5-hour limit"]


def test_한도_패턴_파일이_깨져도_던지지_않는다(isolated_config):
    path = os.path.join(str(isolated_config), "usage_patterns.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{이건 JSON 이 아니에요")
    assert config.usage_patterns() == []
