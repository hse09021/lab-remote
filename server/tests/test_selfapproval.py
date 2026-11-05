"""자기 승인 차단 (계획 0-1).

②가 `labremote approve` 같은 명령을 만드는 순간, Claude 의 Bash 가 그걸 불러
**자기 요청을 스스로 승인**할 수 있다. 그러면 1회용 허가 설계 전체가
무의미해진다. 이름으로 막는 것(`denyCommands`)과 이름만으로는 안 되는 것
(`bashparse` 규칙) 둘 다 고정한다.
"""

import os

import pytest

from app.hooks import bashparse
from app.hooks import decide as D


def actions(ctx, command):
    return sorted(f.action for f in bashparse.classify_with_coverage(command, ctx))


def verdict(ctx, command, *, headless=True):
    found = bashparse.classify_with_coverage(command, ctx)
    ctx.headless = headless
    ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    return D.resolve(found, ctx).kind


# --- 이름으로 막는 것 ---------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "labremote approve hook-sandbox toolu_1",
        "labremote deny hook-sandbox toolu_1",
        "labremote queue add hook-sandbox",
        "labremote service status",
        "sqlite3 server/data/lab.db \"UPDATE jobs SET state='done'\"",
        "systemctl --user stop labremote-orchestrator",
        "systemd-run --user /bin/true",
        "loginctl disable-linger",
        "kill 4821",
        "pkill -f orchestrator",
        "killall python",
        "bwrap --dev-bind / / /bin/sh",
        "unshare -r /bin/sh",
        "nsenter -t 1 -m /bin/sh",
        "chroot /tmp/x /bin/sh",
        "strace -p 4821",
        "ltrace -p 4821",
        "gdb -p 4821",
        "docker run -v /:/host alpine",
        "podman run -v /:/host alpine",
        "at now",
        "crontab -e",
        "claude -p '아무거나'",
    ],
)
def test_금지_명령은_차단(ctx, command):
    assert actions(ctx, command) == ["denied-command"], command
    assert verdict(ctx, command) == "deny"
    assert verdict(ctx, command, headless=False) == "deny"


@pytest.mark.parametrize("wrapper", ["nohup", "nice -n 10", "conda run -n base", "bash -c"])
def test_래퍼로_감싸도_금지_명령은_차단(ctx, wrapper):
    if wrapper == "bash -c":
        command = "bash -c 'labremote approve hook-sandbox toolu_1'"
    else:
        command = f"{wrapper} labremote approve hook-sandbox toolu_1"
    assert "denied-command" in actions(ctx, command), command
    assert verdict(ctx, command) == "deny"


# --- 이름만으로는 안 되는 것 --------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "python -m app.cli approve hook-sandbox toolu_1",
        "python3 -m app.cli deny hook-sandbox toolu_1",
        "python -m app.orchestrator",
        "python -m app",
    ],
)
def test_모듈로_우회하는_것도_차단(ctx, command):
    """`labremote` 를 막아도 `python -m app.cli` 로 같은 일을 할 수 있다."""
    assert actions(ctx, command) == ["denied-command"], command


def test_pip_모듈_호출은_그대로_패키지_설치다(ctx):
    """기존 규칙을 깨지 않는다."""
    assert actions(ctx, "python -m pip install peft") == ["pkg"]


@pytest.mark.parametrize(
    "command",
    [
        "sqlite3 lab.db .tables",
        "cp server/data/lab.db /tmp/복사본.db",
        "cat lab.db",
        "rm lab.db-wal",
    ],
)
def test_상태_DB_는_어떤_도구로도_못_건드린다(ctx, command):
    """도구 이름을 막아도 다른 도구로 열 수 있다. **대상**으로 막는다."""
    assert "denied-command" in actions(ctx, command), command


@pytest.mark.parametrize(
    "command",
    ["python -c \"print(1)\"", "python3 -c 'import os'", "perl -e 'print 1'", "node -e '1'", "ruby -e '1'"],
)
def test_임의_코드_문자열은_승인_대상(ctx, command):
    """정적 분석이 불가능하다. 자동으로 열지 않는다."""
    assert actions(ctx, command) == ["suspicious"], command
    assert verdict(ctx, command) == "deny"  # 헤드리스는 ask -> 거절
    assert verdict(ctx, command, headless=False) == "ask"


@pytest.mark.parametrize("command", ["make clean", "make -j8 train", "ninja", "just build"])
def test_레시피_실행은_승인_대상(ctx, command):
    """Makefile 레시피가 무엇이든 실행한다."""
    assert actions(ctx, command) == ["suspicious"], command


def test_훅_소스를_직접_돌리는_것도_차단(ctx):
    from app import policy_defaults as Dft

    server = Dft.hard_protected_roots()[0]
    assert actions(ctx, f"python {server}/app/hooks/decide.py") == ["hardProtect"]


@pytest.mark.parametrize("command", ["chmod 777 ~/.claude", "chmod -R 777 ~/.claude/settings.json"])
def test_권한_바꾸기도_경로로_판정한다(ctx, command):
    """지금까지는 분류가 없어서 `chmod 777 ~/.claude` 가 안 걸렸다."""
    assert "hardProtect" in actions(ctx, command) or "outside" in actions(ctx, command), command
    assert verdict(ctx, command) == "deny"


def test_심볼릭_링크로_보호_경로를_끌어오는_것도_차단(ctx, project_root):
    command = f"ln -s ~/.claude {project_root}/숨긴설정"
    assert "hardProtect" in actions(ctx, command) or "secret" in actions(ctx, command)
    assert verdict(ctx, command) == "deny"


def test_entrypoint_직접_실행은_trainrun(ctx):
    """학습은 오케스트레이터가 띄운다.

    `newexp` 가 아니라 **별도 분류**다 — `full` 프리셋이 `newexp` 를 자동
    허용하므로 같이 두면 Claude 가 학습을 혼자 돌릴 수 있었다 (2026-11-05).
    """
    ctx.policy.data["bash"]["entrypoints"] = ["src/train.py"]
    assert "trainrun" in actions(ctx, "bash src/train.py --lr 1e-4")
    assert "trainrun" in actions(ctx, "./src/train.py")
    # 래퍼로 감싸도 마찬가지다
    assert "trainrun" in actions(ctx, "conda run -n hook-sandbox src/train.py")
    assert "trainrun" in actions(ctx, "nohup python src/train.py &")


def test_entrypoint_목록이_비어_있으면_평소대로(ctx):
    assert ctx.policy.bash["entrypoints"] == []
    assert actions(ctx, "python src/train.py") == ["newexp"]  # RUN_CMDS 규칙 그대로
