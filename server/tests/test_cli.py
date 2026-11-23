"""`labremote` CLI (v3) — `doctor` · `notify test` · `service` · `monitor once`."""

import os

import pytest

from app import cli


def run(argv):
    return cli.main(argv)


def test_v1_명령은_없다(capsys):
    """훅·정책·승인·큐·루프 명령은 v3 에서 빠졌다 (PLAN 2장)."""
    for name in ("hooks", "policy", "approvals", "queue", "up", "installs", "init-project"):
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


# --- service -----------------------------------------------------------------


@pytest.fixture()
def user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    return units


def test_유닛은_하나뿐이다(user_config):
    """v3 가 만드는 사용자 서비스는 `labremote-session.service` 하나다 (PLAN 1.1)."""
    assert list(user_config.UNITS) == ["labremote-session"]
    assert user_config.unit_path("labremote-session").endswith(
        "systemd/user/labremote-session.service"
    )


def test_service_install_이_유닛을_쓰고_활성화는_안_한다(user_config, monkeypatch, capsys):
    import subprocess

    def boom(*a, **k):
        raise AssertionError(f"명령을 돌리면 안 돼요: {a}")

    monkeypatch.setattr(subprocess, "run", boom)
    assert run(["service", "install"]) == 0
    out = capsys.readouterr().out
    assert "유닛을 썼어요" in out
    assert "loginctl enable-linger" in out and "systemctl --user enable --now" in out
    assert os.path.exists(user_config.unit_path("labremote-session"))


def test_service_install_dry_run_은_안_쓴다(user_config, capsys):
    assert run(["service", "install", "--dry-run"]) == 0
    assert "[Unit]" in capsys.readouterr().out
    assert not os.path.exists(user_config.unit_path("labremote-session"))


def test_유닛_내용(user_config):
    body = user_config.render("labremote-session")
    directives = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
    # 키가 섞이면 구독이 아니라 종량제 과금이다
    assert not any(d.startswith("Environment=ANTHROPIC") for d in directives)
    # v3 는 Claude Code 의 동작을 바꾸지 않는다
    assert not any("DISABLE_AUTOUPDATER" in d or "DISABLE_UPDATES" in d for d in directives)
    # 가볍게 (PLAN 1.3)
    assert "Nice=19" in directives and "IOSchedulingClass=idle" in directives
    # 서버를 재시작해도 남은 건 안 죽인다
    assert [d for d in directives if d.startswith("KillMode=")] == ["KillMode=process"]
    assert any(d.endswith("-m app.cli serve") for d in directives if d.startswith("ExecStart="))


def test_유닛_PATH_에_세션_전용_경로가_없다(user_config):
    """지금 셸의 `PATH` 를 베끼면 나중에 없어질 경로가 섞인다."""
    line = [
        l for l in user_config.render("labremote-session").splitlines()
        if l.startswith("Environment=PATH=")
    ][0]
    assert "vscode-server" not in line
    assert "/usr/bin" in line
    parts = line.split("=", 2)[-1].split(":")
    assert len(parts) == len(set(parts)), parts


def test_service_status(user_config, monkeypatch, capsys):
    import subprocess

    monkeypatch.setattr(user_config, "_systemctl", lambda: "/bin/systemctl")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "enabled\n", "")
    )
    assert run(["service", "status"]) == 0
    assert "labremote-session" in capsys.readouterr().out


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
