"""실행 프로세스의 기본 부품 — 그룹 종료, 생존 판정, 종료코드 기록, 환경 정리.

실행을 띄우는 쪽(`labremote run`)은 2단계에서 tmux 모양으로 새로 만든다.
여기서는 그대로 다시 쓸 부품만 시험한다.
"""

import os
import subprocess
import sys
import threading
import time

import pytest

from app.runner import process as P


def spawn(code: str) -> subprocess.Popen:
    """자기 세션·그룹으로 파이썬 한 줄을 띄운다 (pgid == pid).

    **부모가 거둔다**(`wait`). 안 거두면 죽은 자식이 좀비로 그룹에 남아서
    `group_alive` 가 계속 참이다 — 실제 실행기도 부모라면 거둬야 한다.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc


# --- 그룹 종료 ---------------------------------------------------------------


def test_SIGTERM_으로_끝난다():
    proc = spawn("import time; time.sleep(60)")
    try:
        assert P.terminate_group(proc.pid, grace_sec=5, poll_sec=0.05) == "term"
        assert proc.wait(timeout=5) != 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_SIGTERM_을_무시하면_유예_뒤_SIGKILL():
    proc = spawn(
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    )
    try:
        time.sleep(0.3)  # 신호 처리기가 걸릴 때까지
        began = time.time()
        assert P.terminate_group(proc.pid, grace_sec=1, poll_sec=0.05) == "kill"
        assert time.time() - began >= 0.9  # 체크포인트를 저장할 틈을 줬다
    finally:
        if proc.poll() is None:
            proc.kill()


def test_손자까지_정리한다():
    """DataLoader worker 같은 손자가 남으면 GPU 를 계속 잡는다."""
    proc = spawn(
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "time.sleep(60)"
    )
    try:
        time.sleep(0.3)
        assert P.group_alive(proc.pid) is True
        P.terminate_group(proc.pid, grace_sec=5, poll_sec=0.05)
        assert P.group_alive(proc.pid) is False
    finally:
        if proc.poll() is None:
            proc.kill()


def test_이미_끝난_그룹은_gone():
    proc = spawn("pass")
    proc.wait(timeout=5)
    assert P.terminate_group(proc.pid, grace_sec=1) == "gone"


# --- 생존 판정 ---------------------------------------------------------------


def test_살아_있는_프로세스와_죽은_프로세스():
    proc = spawn("import time; time.sleep(60)")
    try:
        start = P.starttime_of(proc.pid)
        assert start is not None
        assert P.alive(proc.pid, start) is True
    finally:
        proc.kill()
        proc.wait(timeout=5)
    assert P.alive(proc.pid, start) is False


def test_pid_재사용을_starttime_으로_가른다():
    """같은 pid 라도 시작 시각이 다르면 **그** 프로세스가 아니다."""
    me = os.getpid()
    start = P.starttime_of(me)
    assert P.alive(me, start) is True
    assert P.alive(me, start + 12345) is False


def test_없는_pid_는_살아있지_않다():
    assert P.alive(None) is False
    assert P.alive(0) is False
    assert P.starttime_of(2**22 + 12345) is None


# --- 종료코드 파일 -----------------------------------------------------------


def test_먼저_아는_쪽이_종료코드를_적는다(tmp_path):
    path = str(tmp_path / "output" / "exit_code")
    assert P.write_exit_code(path, 0) is True
    assert P.write_exit_code(path, 137) is False  # 덮지 않는다
    assert P.read_exit_code(path) == 0
    assert P.write_exit_code(path, 137, overwrite=True) is True
    assert P.read_exit_code(path) == 137


def test_종료코드_파일이_없거나_깨졌으면_None(tmp_path):
    assert P.read_exit_code(str(tmp_path / "없음")) is None
    broken = tmp_path / "exit_code"
    broken.write_text("숫자가 아니에요", encoding="utf-8")
    assert P.read_exit_code(str(broken)) is None


# --- 환경 정리 ---------------------------------------------------------------


def test_API_키와_에이전트_소켓_주소를_지운다():
    env = {
        "PATH": "/usr/bin",
        "ANTHROPIC_API_KEY": "sk-…",
        "SSH_AUTH_SOCK": "/tmp/ssh-x/agent.1",
        "GPG_AGENT_INFO": "/run/user/1000/gnupg/S.gpg-agent",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "DBUS_STARTER_ADDRESS": "unix:path=/run/user/1000/bus",
        "CUDA_VISIBLE_DEVICES": "0",
    }
    got = P.scrub_env(env)
    assert got == {"PATH": "/usr/bin", "CUDA_VISIBLE_DEVICES": "0"}


# --- systemd scope -----------------------------------------------------------


def test_scope_이름은_systemd_가_받는_글자만():
    assert P.scope_name("my proj", "EXP-007") == "labremote-run-my-proj-EXP-007"
    assert P.scope_name("../x") == "labremote-run----x"


def test_scope_접두사():
    got = P.scope_prefix("labremote-run-demo-EXP-001", "lab.remote 실행 · demo")
    assert got[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
    assert "--unit=labremote-run-demo-EXP-001" in got
    assert got[-2:] == ["--collect", "--"]


def test_scope_를_끄면_탐침도_안_돌린다(monkeypatch):
    """시험 픽스처가 `LAB_NO_SCOPE=1` 을 둔다."""
    called = []
    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: called.append(a))
    assert P.scope_available() is False
    assert called == []


def test_탐침은_실행이_받을_환경으로_잰다(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["env"] = kw.get("env")

        class Done:
            returncode = 0

        return Done()

    monkeypatch.delenv(P.NO_SCOPE_ENV, raising=False)
    monkeypatch.setattr(P.shutil, "which", lambda name, path=None: "/usr/bin/systemd-run")
    monkeypatch.setattr(P.subprocess, "run", fake_run)
    assert P.scope_available({"PATH": "/usr/bin", "ONLY": "이것만"}) is True
    assert seen["env"] == {"PATH": "/usr/bin", "ONLY": "이것만"}


def test_서비스_접두사는_우선순위를_되돌리고_환경을_넘긴다():
    argv = P.service_prefix("labremote-run-x", "d", {"PATH": "/usr/bin", "BAD": "a\nb", "A-B": "x"})
    assert argv[:4] == ["systemd-run", "--user", "--quiet", "--unit=labremote-run-x"]
    assert "Type=forking" in argv and "Nice=0" in argv and "IOSchedulingClass=best-effort" in argv
    assert "--setenv=PATH=/usr/bin" in argv
    assert not any(a.startswith("--setenv=BAD") or a.startswith("--setenv=A-B") for a in argv)
    assert argv[-1] == "--"
