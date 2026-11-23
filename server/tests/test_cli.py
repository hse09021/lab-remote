"""`labremote` CLI (v3) — `doctor` · `notify test` · `autostart` · `remote` · `monitor once`."""

import os

import pytest

from app import cli


def run(argv):
    return cli.main(argv)


def test_v1_명령은_없다(capsys):
    """훅·정책·승인·큐·루프 명령은 v3 에서 빠졌다 (PLAN 2장)."""
    for name in ("hooks", "policy", "approvals", "queue", "up", "installs", "init-project", "service"):
        with pytest.raises(SystemExit):
            run([name])
        capsys.readouterr()


# --- notify ------------------------------------------------------------------


def test_notify_test_는_주소가_없으면_안_보낸다(capsys):
    assert run(["notify", "test"]) == 2
    assert "웹훅 주소가 없어요" in capsys.readouterr().err


def test_notify_test_가_성공을_성공으로_본다(monkeypatch, capsys):
    """`notifier.send` 는 `sent`·`status` 를 돌려준다 — `ok` 가 아니다."""
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(notifier, "send", lambda *a, **k: {"sent": True, "status": 204})
    assert run(["notify", "test"]) == 0
    out = capsys.readouterr().out
    assert "✔ 보냈어요 (상태 204)" in out
    assert "webhooks/a/b" not in out


def test_notify_test_가_실패를_실패로_본다(monkeypatch, capsys):
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "send", lambda *a, **k: {"sent": False, "status": 403, "reason": "HTTP Error 403"}
    )
    assert run(["notify", "test"]) == 2
    captured = capsys.readouterr()
    assert "못 보냈어요" in captured.err and "403" in captured.err
    # 주소는 어디에도 안 찍는다
    assert "webhooks/a/b" not in captured.out + captured.err


def test_notify_test_가_중복_제거를_실패로_안_본다(monkeypatch, capsys):
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(notifier, "send", lambda *a, **k: {"sent": False, "suppressed": True})
    assert run(["notify", "test"]) == 0
    assert "눌렸어요" in capsys.readouterr().out


def test_notifier_의_반환_칸_이름을_고정한다(monkeypatch):
    """CLI 가 보는 칸 이름이 바뀌면 조용히 뒤집힌다 — 그걸 막는다."""
    from app import db, notifier, notify

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(notify, "send_payload", lambda *a, **k: {"sent": True, "status": 204})
    with db.open_db() as conn:
        got = notifier.send(conn, "test", title="x", body="y", subject="s1")
    assert "sent" in got, got
    assert "ok" not in got, "칸 이름이 바뀌었어요 — CLI 도 같이 고쳐 주세요"


# --- autostart ---------------------------------------------------------------


@pytest.fixture()
def user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    monkeypatch.setattr(units, "_systemctl", lambda: "/bin/systemctl")
    monkeypatch.setattr(units, "_user", lambda: "me")
    return units


class FakeSystem:
    """systemctl · loginctl 을 흉내 — 무엇을 불렀는지 남긴다."""

    def __init__(self, linger=False):
        self.calls = []
        self.linger = linger

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["loginctl", "enable-linger"]:
            self.linger = True
        if argv[:2] == ["loginctl", "disable-linger"]:
            self.linger = False
        return 0, ""


def test_유닛은_하나뿐이다(user_config):
    """v3 가 만드는 사용자 서비스는 `labremote-session.service` 하나다 (PLAN 1.1)."""
    assert list(user_config.UNITS) == ["labremote-session"]
    assert user_config.unit_path().endswith("systemd/user/labremote-session.service")


def test_유닛_내용(user_config):
    body = user_config.render(port=8123)
    directives = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
    # 키가 섞이면 구독이 아니라 종량제 과금이다 — 넣지 않고, 매니저 환경에 있어도 지운다
    assert not any(d.startswith("Environment=ANTHROPIC") for d in directives)
    assert any(d.startswith("UnsetEnvironment=") and "ANTHROPIC_API_KEY" in d for d in directives)
    # tmux "labremote" 안에서 serve 만 — code tunnel 은 여기서 띄우지 않는다 (2026-11-23 결정)
    start = [d for d in directives if d.startswith("ExecStart=")][0]
    assert "-L labremote new-session -d -s labremote" in start and "-m app.cli serve --port 8123" in start
    assert "tunnel" not in body.split("[Service]")[1].split("#")[0]
    assert "Type=forking" in directives and "Restart=always" in directives
    assert "Environment=LAB_SESSION_UNIT=labremote-session" in directives
    assert user_config.port_of_unit() is None


def test_유닛_PATH_에_세션_전용_경로가_없다(user_config):
    """지금 셸의 `PATH` 를 베끼면 나중에 없어질 경로가 섞인다."""
    line = [l for l in user_config.render().splitlines() if l.startswith("Environment=PATH=")][0]
    assert "vscode-server" not in line and "/usr/bin" in line
    parts = line.split("=", 2)[-1].split(":")
    assert len(parts) == len(set(parts)), parts


def test_공백이_있는_경로는_거절한다(user_config):
    with pytest.raises(ValueError):
        user_config.render(python="/tmp/my env/python")


def test_autostart_install_dry_run_은_안_쓴다(user_config, capsys):
    assert run(["autostart", "install", "--dry-run"]) == 0
    assert "[Unit]" in capsys.readouterr().out
    assert not os.path.exists(user_config.unit_path())


def test_autostart_install_은_묻고_아니면_안_바꾼다(user_config, monkeypatch, capsys):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
    monkeypatch.setattr(user_config, "linger", lambda: False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "n")
    assert run(["autostart", "install"]) == 1
    out = capsys.readouterr().out
    assert "linger 켜기" in out and "아무것도 바꾸지 않았어요" in out
    assert not os.path.exists(user_config.unit_path())


def test_autostart_켜고_끄면_linger_가_원래대로(user_config, monkeypatch, isolated_data):
    from app.service import autostart

    fake = FakeSystem(linger=False)
    monkeypatch.setattr(user_config, "linger", lambda: fake.linger)
    steps = autostart.install(port=8001, run=fake)
    assert all(s["ok"] for s in steps)
    assert ["loginctl", "enable-linger", "me"] in fake.calls
    assert ["/bin/systemctl", "--user", "enable", "--now", "labremote-session.service"] in fake.calls
    assert os.path.exists(user_config.unit_path()) and user_config.port_of_unit() == 8001
    assert autostart.record()["lingerBefore"] is False
    # 다시 켜도 "원래 값" 은 처음 것 그대로
    autostart.install(port=8001, run=fake)
    assert autostart.record()["lingerBefore"] is False

    fake.calls.clear()
    autostart.uninstall(run=fake)
    assert ["loginctl", "disable-linger", "me"] in fake.calls
    assert fake.calls[-1] == ["/bin/systemctl", "--user", "stop", "--no-block", "labremote-session.service"]
    assert not os.path.exists(user_config.unit_path()) and autostart.record() == {}


def test_원래_linger_가_켜져_있었으면_끄지_않는다(user_config, monkeypatch):
    from app.service import autostart

    fake = FakeSystem(linger=True)
    monkeypatch.setattr(user_config, "linger", lambda: fake.linger)
    autostart.install(run=fake)
    assert not any(c[0] == "loginctl" for c in fake.calls)
    autostart.uninstall(run=fake)
    assert fake.linger is True and not any(c[:2] == ["loginctl", "disable-linger"] for c in fake.calls)


def test_실패하면_거기서_멈춘다(user_config, monkeypatch):
    from app.service import autostart

    monkeypatch.setattr(user_config, "linger", lambda: True)
    with pytest.raises(autostart.AutostartError, match="daemon-reload"):
        autostart.install(run=lambda argv: (1, "boom") if "daemon-reload" in argv else (0, ""))


def test_꺼져_있으면_다시_켜기를_거절(user_config):
    from app.service import autostart

    with pytest.raises(autostart.AutostartError, match="꺼져"):
        autostart.restart(run=lambda argv: (0, ""))


def test_autostart_status(user_config, monkeypatch, capsys):
    import subprocess

    monkeypatch.setattr(user_config, "linger", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "enabled\n", ""))
    assert run(["autostart", "status"]) == 0
    out = capsys.readouterr().out
    assert "labremote-session" in out and "tmux -L labremote attach" in out


# --- remote ------------------------------------------------------------------


def test_remote_set_show_clear(monkeypatch, capsys):
    from app import tunnel

    monkeypatch.setattr(tunnel, "status", lambda **k: {"state": "off", "url": "", "service": False, "loggedIn": False})
    assert run(["remote", "set", "http://x.example"]) == 2
    assert run(["remote", "set", "https://abc-8000.example.ms/"]) == 0
    assert run(["remote"]) == 0
    out = capsys.readouterr().out
    assert "https://abc-8000.example.ms" in out and "로그인 안 함" in out
    assert run(["remote", "clear"]) == 0


def test_setsid_는_cgroup_을_안_바꾼다():
    """실측(2026-11-05)으로 고정한다 — 그래서 실행은 `systemd-run --scope` 로 돈다."""
    import subprocess
    import time

    mine = open(f"/proc/{os.getpid()}/cgroup").read().strip()
    child = subprocess.Popen(["/bin/sh", "-c", "sleep 5"], start_new_session=True)
    try:
        time.sleep(0.3)
        theirs = open(f"/proc/{child.pid}/cgroup").read().strip()
        assert theirs == mine, "cgroup 이 달라졌어요 — 전제가 바뀌었어요"
        assert os.getsid(child.pid) != os.getsid(os.getpid())
    finally:
        child.kill()
        child.wait()


# --- monitor -----------------------------------------------------------------


def test_monitor_once(monkeypatch, capsys):
    from app.monitor import gpu

    monkeypatch.setattr(gpu, "probe", lambda: {"available": False, "reason": "시험", "devices": []})
    assert run(["monitor", "once"]) == 0
    out = capsys.readouterr().out
    assert "GPU    조회 불가 — 시험" in out
    assert "호스트  CPU" in out


# --- doctor ------------------------------------------------------------------


def test_doctor_는_종료코드로_판정을_돌려준다(monkeypatch, capsys):
    from app import doctor

    monkeypatch.setattr(doctor, "run", lambda: {"ok": False, "checks": [], "limitations": []})
    assert run(["doctor"]) == 1
    monkeypatch.setattr(doctor, "run", lambda: {"ok": True, "checks": [], "limitations": []})
    assert run(["doctor"]) == 0
