"""`~/.claude/settings.json` 병합 설치 시험.

사용자 설정을 건드리므로 **남의 설정을 망가뜨리지 않는 것**이 핵심이다.
"""

import json
import os

import pytest

from app.hooks import install

#: matcher 가 이 중 하나면 **모든 도구**에 매치된다 (번들 바이너리의 비교 코드:
#: `if (!matcher || matcher === "*") return true`, 그리고 `".*"`·`""` 도 전부).
MATCH_ALL = (None, "", "*", ".*")


def _matches(matcher, tool: str) -> bool:
    """번들의 판정을 그대로 흉내 낸다 — 이름 나열은 **정확 문자열 비교**다."""
    import re

    if matcher in MATCH_ALL:
        return True
    if any(ch in str(matcher) for ch in "|()[]*+?^$\\"):
        return re.fullmatch(str(matcher), tool) is not None
    return str(matcher) == tool


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
    pre = data["hooks"]["PreToolUse"][0]
    # 판정 훅이 깨지면 조용히 문이 열리면 안 된다
    assert pre["hooks"][0]["onFailure"] == "block"
    assert "app.hooks.pretooluse" in pre["hooks"][0]["command"]
    # 🔑 **설치된** matcher 가 match-all 이다. 이름을 나열하면 정확 문자열
    # 비교라 목록에 없는 도구는 훅이 아예 안 뜬다.
    assert pre["matcher"] in MATCH_ALL, pre["matcher"]
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


# --- 🔑 S5 · matcher 가 모든 도구를 덮나 ------------------------------------
#
# 번들 바이너리의 비교 코드: matcher 가 **없음·`""`·`"*"`·`".*"`** 이면 전부
# 매치이고, 이름을 나열하면 **정확 문자열 비교**다. 전에는 이름을 나열해서
# `Glob`·`TodoWrite`·`Task`·`NotebookRead`·`mcp__*` 에 훅이 **아예 안 떴다** —
# 그런데 테스트는 "막힌다" 고 단정했다(거짓 초록불).


def _installed_matchers(path, event="PreToolUse"):
    data = read(path)
    return [entry.get("matcher") for entry in data["hooks"][event]]


def test_설치된_matcher_가_모든_도구를_덮는다(fake_settings):
    install.install(mode="enforce")
    for event in ("PreToolUse", "PostToolUse"):
        got = _installed_matchers(fake_settings, event)
        assert got and all(m in MATCH_ALL for m in got), (event, got)


def test_classify_의_도구_이름이_전부_matcher_에_걸린다(fake_settings):
    """판정 코드가 이름을 아는 도구는 **하나도 빠짐없이** 훅이 떠야 한다.

    전에는 `classify` 가 `Glob` 을 `SECRET_READ_TOOLS` 에 넣어 `~/.ssh` 훑기를
    막도록 써 뒀는데 matcher 에 없어서 훅이 안 떴다.
    """
    from app.hooks import classify

    install.install(mode="enforce")
    matchers = _installed_matchers(fake_settings)

    names = set(classify.WRITE_TOOLS) | set(classify.NET_TOOLS)
    names |= set(classify.READ_ONLY_TOOLS) | set(classify.SECRET_READ_TOOLS)
    names |= {"Bash", "Task", "NotebookRead", "mcp__x__y", "모르는도구"}
    assert "Glob" in names and "TodoWrite" in names and "ToolSearch" in names

    for tool in sorted(names):
        assert any(_matches(m, tool) for m in matchers), tool


def test_덤프_모드도_같은_matcher_를_쓴다(fake_settings):
    install.install(mode="dump")
    for event in ("PreToolUse", "PostToolUse"):
        assert all(m in MATCH_ALL for m in _installed_matchers(fake_settings, event))


def test_판정할_것이_없는_allow_는_기록하지_않는다(ctx, hook_event, monkeypatch):
    """matcher 가 모든 도구가 되면서(S5) 훅이 도구 호출마다 뜬다. 그 줄
    대부분은 `Read`·`Glob`·`TodoWrite` 이고 판정할 것이 없다 — 남기면
    `hook_events.jsonl` 이 폭증한다.

    **승인 로그 CSV 에는 그대로 남는다** — 거기가 기록 의무의 대상이다.
    """
    from app import approval_log as A
    from app.hooks import emit, pretooluse

    logged: list[dict] = []
    rows: list[dict] = []
    monkeypatch.setattr(A, "log_event", lambda path, obj: logged.append(obj))
    monkeypatch.setattr(A, "append_row", lambda path, **kw: rows.append(kw))
    monkeypatch.setattr(A, "remember_denied", lambda *a, **k: None)
    monkeypatch.setattr(A, "open_pending", lambda *a, **k: None)

    def record(decision):
        logged.clear()
        rows.clear()
        pretooluse._record(ctx, hook_event("Glob", {"pattern": "*"}), [], decision)

    # 1. 조용한 allow → hook_events 에 안 남는다
    for action in sorted(pretooluse.QUIET_ACTIONS):
        record(emit.ALLOW("", label="읽기", action=action))
        assert logged == [], action

    # 2. 막힌 것은 남는다
    record(emit.DENY("막았어요", label="프로젝트 폴더 밖", action="outside", rel="x"))
    assert [e["decision"] for e in logged] == ["deny"]

    # 3. 물은 것도 남는다
    record(emit.ASK("승인이 필요해요", label="패키지 설치", action="pkg"))
    assert [e["decision"] for e in logged] == ["ask"]

    # 4. 허가로 통과한 것도 남는다 (meta 가 있다)
    record(emit.ALLOW("", label="읽기", action="toolAllowed", meta={"grant": "g-1"}))
    assert [e["decision"] for e in logged] == ["allow"]

    # 5. 분류 안 된 allow 도 남는다 (QUIET_ACTIONS 가 아니다)
    record(emit.ALLOW("", label="코드 수정", action="code"))
    assert [e["decision"] for e in logged] == ["allow"]


def test_막는_행동은_조용한_목록에_없다():
    """실수로 `outside` 를 넣으면 잠금이 기록 없이 지나간다."""
    from app.hooks import decide, pretooluse

    for action in decide.LOCK_ACTIONS:
        assert action not in pretooluse.QUIET_ACTIONS, action
    for action in ("secret", "selfProtect", "hardProtect", "outputProtect"):
        assert action not in pretooluse.QUIET_ACTIONS, action
