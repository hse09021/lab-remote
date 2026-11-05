"""헤드리스 코드 실행 게이트 — Claude Bash 소켓 차단이 **확인될 때까지** 승인.

2단계 조건 4: "python·pytest 는 샌드박스가 실제로 막는 게 확인되면 allow,
아니면 ask". S9 에서 Claude Bash 샌드박스의 유닉스 소켓 차단이 미확인으로
남았다. 그래서 확인 표시(`sandbox.socketVerified`)를 사람이 켜기 전에는
권한 단계와 무관하게 승인으로 간다.
"""

import json
import os

import pytest

from app import policy, registry
from app.hooks import bashparse, decide as D
from app.agent import sandboxcheck


CODE = [
    "python src/x.py", "python3 src/x.py", "python -m mypkg", "python3 -m mypkg",
    "python -m pytest", "pytest -q", "py.test", "conda run -n base python src/x.py",
]


def _decide(ctx, command):
    ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    found = bashparse.classify_with_coverage(command, ctx)
    return found, D.resolve(found, ctx)


@pytest.fixture()
def hctx(ctx, sandboxed):
    ctx.headless = True
    ctx.sandbox = policy.sandbox_state(sandboxed)["ok"]
    ctx.policy.data["saved"] = {"mode": "full", "overrides": {}}  # 권한 단계를 최대로
    return ctx


@pytest.mark.parametrize("command", CODE)
def test_확인_전에는_full_이어도_승인(hctx, command):
    found, got = _decide(hctx, command)
    assert "coderun" in {f.action for f in found}, command
    assert got.kind == "deny" and got.meta.get("originallyAsk"), command  # 승인 가능
    assert "소켓" in got.reason


@pytest.mark.parametrize("command", ["python src/x.py", "pytest -q"])
def test_확인하면_권한_단계대로(hctx, command):
    hctx.socket_verified = True
    _, got = _decide(hctx, command)
    assert got.kind == "allow", command


def test_대화형은_그대로(ctx):
    ctx.headless = False
    found, _ = _decide(ctx, "python src/x.py")
    assert "coderun" not in {f.action for f in found}


def test_coderun_은_잠금이_아니다():
    """사람이 그 명령 하나를 보고 승인할 수 있어야 한다."""
    assert "coderun" not in D.LOCK_ACTIONS
    from app import grants
    assert "coderun" not in grants.LOCKED_ACTIONS


def test_pip_과_자기_모듈은_더_강한_판정이_이긴다(hctx):
    assert {f.action for f in _decide(hctx, "python -m pip install x")[0]} == {"pkg"}
    assert _decide(hctx, "python -m app.cli approve x y")[1].kind == "deny"
    assert {f.action for f in _decide(hctx, "python -c 'print(1)'")[0]} == {"suspicious"}


def test_읽기_명령은_영향_없다(hctx):
    for command in ("ls src", "git status", "grep -n x README.md"):
        assert _decide(hctx, command)[1].kind == "allow", command


def test_allowExtra_로_인터프리터를_열_수_없다(hctx):
    """스위치는 하나뿐 — 확인 전에는 allowExtra 의 인터프리터를 무시한다."""
    hctx.policy.data.setdefault("bash", {})["allowExtra"] = ["node", "bash", "jq"]
    assert "node" not in bashparse.allow_extra(hctx)
    assert "jq" in bashparse.allow_extra(hctx)
    assert _decide(hctx, "node src/x.js")[1].kind != "allow"
    hctx.socket_verified = True
    assert "node" in bashparse.allow_extra(hctx)


# --- 확인 표시 ---------------------------------------------------------------


def _record_version(version):
    path = os.path.join(registry.data_dir(), "agent", "claude_version.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": version}, fh)


def test_없으면_미확인(project):
    got = policy.socket_verification(project)
    assert got["verified"] is False and "확인하지 않았어요" in got["reason"]


def test_켜면_지금_판에_묶인다(project):
    _record_version("2.1.318")
    got = policy.set_socket_verified(project, on=True, note="sandbox-check")
    assert got["verified"] is True and got["for"] == "2.1.318"


def test_판이_바뀌면_저절로_미확인(project):
    _record_version("2.1.318")
    policy.set_socket_verified(project, on=True, note="x")
    _record_version("2.1.400")
    got = policy.socket_verification(project)
    assert got["verified"] is False and "2.1.318" in got["reason"] and "2.1.400" in got["reason"]


def test_판_기록이_없으면_못_켠다(project):
    path = os.path.join(registry.data_dir(), "agent", "claude_version.json")
    if os.path.exists(path):
        os.remove(path)
    with pytest.raises(policy.PolicyError):
        policy.set_socket_verified(project, on=True, note="x")


def test_훅이_정책의_표시를_읽는다(project, project_root, monkeypatch):
    from app.hooks import pretooluse as PT

    monkeypatch.setenv("LABREMOTE_HEADLESS", "1")
    ev = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": project_root}
    assert PT._ctx_from(ev).socket_verified is False
    _record_version("2.1.318")
    pol = policy.load("hook-sandbox")
    policy.set_socket_verified(pol, on=True, note="x")
    policy.save(pol)
    assert PT._ctx_from(ev).socket_verified is True


# --- entrypoint 사본 ----------------------------------------------------------


def test_entrypoint_사본을_맞춘다(project, project_root, conn):
    from app.orchestrator import guards
    from tests.conftest import write_runnable_config

    write_runnable_config(project_root, entrypoint="src/train.py")
    assert policy.load("hook-sandbox").bash.get("entrypoints") == []
    guards.check_loop(conn, "hook-sandbox", project_root)
    assert policy.load("hook-sandbox").bash.get("entrypoints") == ["src/train.py"]


def test_멈춘_루프에서도_맞춘다(project, project_root, conn):
    from app.orchestrator import guards
    from app.store import loops as LP
    from tests.conftest import write_runnable_config

    write_runnable_config(project_root, entrypoint="src/train.py")
    LP.set_state(conn, "hook-sandbox", "stopped", stop_reason="최대 실행 횟수")
    guards.check_loop(conn, "hook-sandbox", project_root)
    assert policy.load("hook-sandbox").bash.get("entrypoints") == ["src/train.py"]


# --- sandbox-check 판정 ------------------------------------------------------

ON_LOG = """\
2026-11-05 [DEBUG] [Sandbox Linux] Applying seccomp filter for Unix socket blocking
2026-11-05 [DEBUG] [Sandbox Linux] Wrapped command with bwrap (network, filesystem, seccomp(unix-block) restrictions)
"""
OFF_LOG = """\
2026-11-05 [WARN] [Sandbox Linux] apply-seccomp binary not available - unix socket blocking disabled. Install @anthropic-ai/sandbox-runtime globally for full protection.
2026-11-05 [DEBUG] [Sandbox Linux] Wrapped command with bwrap (network, filesystem restrictions)
"""


def test_필터가_붙었으면_on():
    assert sandboxcheck.parse(ON_LOG)["verdict"] == "on"


def test_helper_가_없으면_off():
    assert sandboxcheck.parse(OFF_LOG)["verdict"] == "off"


def test_allowAll_이면_off():
    log = "[Sandbox Linux] Skipping seccomp filter - allowAllUnixSockets is enabled\n"
    assert sandboxcheck.parse(log)["verdict"] == "off"


def test_감싼_명령에_필터가_없으면_off():
    log = "[Sandbox Linux] Wrapped command with bwrap (network, filesystem restrictions)\n"
    assert sandboxcheck.parse(log)["verdict"] == "off"


def test_근거가_없으면_모른다고_한다():
    assert sandboxcheck.parse("아무 줄도 없어요\n")["verdict"] == "unknown"
    only_apply = "[Sandbox Linux] Applying seccomp filter for Unix socket blocking\n"
    assert sandboxcheck.parse(only_apply)["verdict"] == "unknown"


def test_check_는_실제_런처로_디버그_파일을_넘긴다(project, project_root, sandboxed):
    seen = {}

    def fake(made):
        seen["argv"] = made["argv"]
        path = made["argv"][made["argv"].index("--debug-file") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ON_LOG)
        return 0

    got = sandboxcheck.run("hook-sandbox", runner=fake, preset="full")
    argv = seen["argv"]
    assert "--debug-file" in argv
    assert "--setting-sources" in argv and "--strict-mcp-config" in argv  # 같은 경계
    assert got["verdict"] == "on"
    assert got["log"].startswith(sandboxcheck.log_dir())
    assert oct(os.stat(got["log"]).st_mode & 0o777) == "0o600"
    # 스위치는 안 켠다
    assert policy.socket_verification(policy.load("hook-sandbox"))["verified"] is False
