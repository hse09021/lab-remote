"""`~/.claude/settings.json` 병합 설치 시험.

사용자 설정을 건드리므로 **남의 설정을 망가뜨리지 않는 것**이 핵심이다.
"""

import json
import os

import pytest

from app.hooks import install


@pytest.fixture(autouse=True)
def fake_settings(tmp_path, monkeypatch):
    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"effortLevel": "high"}), encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(path))
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_덤프_모드_설치(fake_settings):
    info = install.install(mode="dump")
    data = read(fake_settings)

    assert data["effortLevel"] == "high"  # 남의 설정은 그대로
    assert set(data["hooks"]) == install.expected_events("dump")
    for entries in data["hooks"].values():
        cmd = entries[0]["hooks"][0]["command"]
        assert install.MARKER in cmd and "app.hooks.debug" in cmd
        # 덤프는 아무것도 막지 않는다
        assert entries[0]["hooks"][0]["onFailure"] == "continue"
    assert info["mode"] == "dump"


def test_enforce_설치(fake_settings):
    info = install.install(mode="enforce")
    data = read(fake_settings)

    assert data["effortLevel"] == "high"
    assert set(data["hooks"]) == install.expected_events("enforce")
    # 거부로 턴이 끊기면 Stop 이 안 돈다 — 이 훅이 빠지면 대기 건이 남는다
    assert "UserPromptSubmit" in data["hooks"]
    assert "app.hooks.userprompt" in data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    # 비밀 파일만 보려고 읽기 도구도 matcher 에 들어 있다
    assert "Read" in install.TOOL_MATCHER and "Grep" in install.TOOL_MATCHER
    pre = data["hooks"]["PreToolUse"][0]
    # 판정 훅이 깨지면 조용히 문이 열리면 안 된다
    assert pre["hooks"][0]["onFailure"] == "block"
    assert "app.hooks.pretooluse" in pre["hooks"][0]["command"]
    assert "MultiEdit" in pre["matcher"]  # 실측 안 됐어도 빼지 않는다
    assert "ToolSearch" not in pre["matcher"]  # 읽기 전용
    # 기록용 훅은 아무것도 막지 않는다
    for event in ("PostToolUse", "Stop", "SessionEnd"):
        assert data["hooks"][event][0]["hooks"][0]["onFailure"] == "continue"
    assert info["mode"] == "enforce"


def test_enforce_는_판정_모듈이_없으면_거절(fake_settings, monkeypatch, tmp_path):
    """pretooluse.py 가 생기기 전에 잘못 걸어 두지 못하게 하는 안전장치."""
    empty = tmp_path / "빈서버"
    (empty / "app" / "hooks").mkdir(parents=True)
    monkeypatch.setattr(install, "server_dir", lambda: str(empty))
    with pytest.raises(RuntimeError) as err:
        install.install(mode="enforce")
    assert "pretooluse" in str(err.value)


def test_백업_경로를_돌려준다(fake_settings):
    info = install.install(mode="dump")
    assert info["backup"] and os.path.exists(info["backup"])
    with open(info["backup"], encoding="utf-8") as fh:
        assert json.load(fh) == {"effortLevel": "high"}  # 설치 전 원본


def test_설정_파일이_없어도_설치된다(fake_settings):
    fake_settings.unlink()
    info = install.install(mode="dump")
    assert info["backup"] is None
    assert set(read(fake_settings)["hooks"]) >= {"PreToolUse"}


def test_두_번_설치해도_중복되지_않는다(fake_settings):
    install.install(mode="dump")
    info = install.install(mode="dump")
    data = read(fake_settings)
    assert info["replaced"] == len(install.DUMP_EVENTS)
    for entries in data["hooks"].values():
        assert len(entries) == 1


def test_사용자가_손으로_넣은_훅은_건드리지_않는다(fake_settings):
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo 내훅"}]}
    fake_settings.write_text(
        json.dumps({"effortLevel": "high", "hooks": {"PreToolUse": [mine]}}), encoding="utf-8"
    )
    install.install(mode="dump")
    entries = read(fake_settings)["hooks"]["PreToolUse"]
    assert mine in entries
    assert len(entries) == 2

    install.uninstall()
    data = read(fake_settings)
    assert data["hooks"]["PreToolUse"] == [mine]
    assert data["effortLevel"] == "high"


def test_uninstall_이_원래대로_되돌린다(fake_settings):
    before = read(fake_settings)
    install.install(mode="dump")
    info = install.uninstall()

    assert info["removed"] == len(install.DUMP_EVENTS)
    assert read(fake_settings) == before  # hooks 키까지 깨끗하게 사라짐
    assert info["previousBackup"] and os.path.exists(info["previousBackup"])


def test_uninstall_은_설치_안_됐어도_안전하다(fake_settings):
    before = read(fake_settings)
    info = install.uninstall()
    assert info["removed"] == 0
    assert read(fake_settings) == before


def test_command_가_래퍼의_절대_경로이고_실행_가능(fake_settings):
    install.install(mode="dump")
    cmd = read(fake_settings)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    wrapper = cmd.split('" ')[0].lstrip('"')
    assert os.path.isabs(wrapper)
    assert os.access(wrapper, os.X_OK)


def test_status_가_설치_상태를_읽는다(fake_settings):
    assert install.status()["installed"] == {}
    install.install(mode="dump")
    st = install.status()
    assert set(st["installed"]) == install.expected_events("dump")
    assert st["state"]["mode"] == "dump"
    install.uninstall()
    assert install.status()["installed"] == {}
    assert install.status()["state"] is None


def test_깨진_settings_는_고치라고_알려_준다(fake_settings):
    fake_settings.write_text("{ 깨진 JSON", encoding="utf-8")
    with pytest.raises(RuntimeError) as err:
        install.install(mode="dump")
    assert str(fake_settings) in str(err.value)


def test_모르는_모드는_거절():
    with pytest.raises(ValueError):
        install.install(mode="아무거나")


def test_설치_기록이_남는다(fake_settings):
    info = install.install(mode="dump")
    with open(install.state_path(), encoding="utf-8") as fh:
        assert json.load(fh) == info


def test_SubagentStop_도_등록된다(fake_settings):
    """서브에이전트 대기 건을 닫는 훅. 빠지면 승인창이 열린 채 기록이 어긋난다."""
    install.install(mode="enforce")
    data = read(fake_settings)
    assert "SubagentStop" in data["hooks"]
    cmd = data["hooks"]["SubagentStop"][0]["hooks"][0]["command"]
    assert "app.hooks.subagentstop" in cmd
    # 아무것도 막지 않는 기록용 훅이다
    assert data["hooks"]["SubagentStop"][0]["hooks"][0]["onFailure"] == "continue"


def test_덤프_모드도_SubagentStop_을_받아_적는다(fake_settings):
    """이 이벤트의 입력은 아직 실측 전이다."""
    install.install(mode="dump")
    assert "SubagentStop" in read(fake_settings)["hooks"]
