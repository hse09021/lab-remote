"""🖥 7단계 CLI 다섯 — `up` · `queue` · `monitor` · `notify` · `service`."""

import json
import os

import pytest

from app import cli


def run(argv):
    return cli.main(argv)


# --- up ----------------------------------------------------------------------


def test_up_은_같은_루프를_쓴다():
    """8단계의 systemd 유닛과 **같은 루프**여야 한다 — 진실이 둘이 되면 안 된다."""
    import inspect

    from app.service import units

    body = inspect.getsource(cli.cmd_up)
    assert "orchestrator" in body and "main(" in body
    # 유닛도 같은 모듈을 돌린다
    assert units.UNITS["labremote-orchestrator"][1] == "app.orchestrator"


def test_up_once_는_한_바퀴만(monkeypatch, capsys, project, project_root):
    seen = {}
    from app.orchestrator import __main__ as loop_main

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(loop_main, "main", fake)
    assert run(["up", "--once"]) == 0
    assert seen["argv"] == ["--once"]


def test_up_이_Ctrl_C_를_곱게_받는다(monkeypatch, capsys):
    from app.orchestrator import __main__ as loop_main

    def boom(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(loop_main, "main", boom)
    assert run(["up", "--foreground"]) == 0
    assert "학습은 안 죽어요" in capsys.readouterr().out


# --- queue -------------------------------------------------------------------


def test_queue_list_가_비면_그렇게_말한다(isolated_data, capsys):
    assert run(["queue", "list"]) == 0
    assert "비어 있어요" in capsys.readouterr().out


def test_queue_add_dummy(project, project_root, capsys):
    assert run(["queue", "add", "hook-sandbox", "--dummy"]) == 0
    out = capsys.readouterr().out
    assert "작업을 넣었어요" in out and "가짜 학습" in out

    assert run(["queue", "list", "hook-sandbox"]) == 0
    listed = capsys.readouterr().out
    assert "plan" in listed and "queued" in listed


def test_queue_add_는_등록_안_된_프로젝트를_거부한다(isolated_data, capsys):
    assert run(["queue", "add", "없는프로젝트"]) == 2
    assert "등록된 실험 프로젝트가 아니에요" in capsys.readouterr().err


def test_queue_pause_resume(project, project_root, conn, capsys):
    from app.store import loops as LP

    assert run(["queue", "pause", "hook-sandbox", "--reason", "잠깐"]) == 0
    assert "멈췄어요" in capsys.readouterr().out
    with __import__("app").db.open_db() as c:
        assert LP.ensure(c, "hook-sandbox")["paused"]

    assert run(["queue", "resume", "hook-sandbox"]) == 0
    with __import__("app").db.open_db() as c:
        assert not LP.ensure(c, "hook-sandbox")["paused"]


def test_queue_cancel(project, project_root, capsys):
    run(["queue", "add", "hook-sandbox", "--dummy"])
    capsys.readouterr()
    from app import db
    from app.store import jobs as J

    with db.open_db() as c:
        job_id = J.listing(c, "hook-sandbox")[0]["id"]
    assert run(["queue", "cancel", "hook-sandbox", str(job_id)]) == 0
    with db.open_db() as c:
        assert J.get(c, job_id)["state"] == "cancelled"


def test_queue_cancel_은_번호를_요구한다(project, capsys):
    assert run(["queue", "cancel", "hook-sandbox"]) == 2
    assert "작업 번호" in capsys.readouterr().err


def test_queue_list_를_상태로_거른다(project, project_root, capsys):
    run(["queue", "add", "hook-sandbox", "--dummy"])
    capsys.readouterr()
    assert run(["queue", "list", "hook-sandbox", "--state", "done"]) == 0
    assert "비어 있어요" in capsys.readouterr().out


# --- monitor -----------------------------------------------------------------


def test_monitor_once_가_스냅샷을_쓴다(project, project_root, capsys):
    from app.monitor import snapshot

    code = run(["monitor", "once"])
    out = capsys.readouterr().out
    assert code in (0, 1), out
    assert "GPU" in out and "호스트" in out
    assert os.path.exists(snapshot.status_path("hook-sandbox"))


def test_monitor_once_는_CPU_를_두_번_잰다():
    """CPU 는 **두 표본의 차분**이다 — 한 번만 읽으면 `None` 이 나온다."""
    import inspect

    body = inspect.getsource(cli.cmd_monitor)
    assert "cpu_times()" in body and "before=before" in body


def test_monitor_status_는_없을_때_알려_준다(project, capsys):
    assert run(["monitor", "status"]) == 0
    assert "스냅샷이 아직 없어요" in capsys.readouterr().out


def test_monitor_status_가_스냅샷을_읽는다(project, project_root, capsys):
    run(["monitor", "once"])
    capsys.readouterr()
    assert run(["monitor", "status"]) == 0
    out = capsys.readouterr().out
    assert "hook-sandbox" in out and "status/hook-sandbox.json" in out


# --- notify ------------------------------------------------------------------


def test_notify_test_는_주소가_없으면_안_보낸다(isolated_config, monkeypatch, capsys):
    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    assert run(["notify", "test"]) == 2
    assert "웹훅 주소가 없어요" in capsys.readouterr().err


def test_notify_test_가_보낸다(isolated_data, isolated_config, monkeypatch, capsys):
    from app import notifier

    seen = {}
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "_post",
        lambda payload, url="": seen.setdefault("payload", payload) or {"sent": True, "status": 204},
        raising=False,
    )
    code = run(["notify", "test"])
    out = capsys.readouterr().out + capsys.readouterr().err
    # 전송 경로가 바뀌어도 **주소는 절대 안 찍는다**
    assert "webhooks/a/b" not in out
    assert code in (0, 2)


def test_notify_는_주소를_찍지_않는다():
    import inspect

    body = inspect.getsource(cli.cmd_notify)
    assert "webhook_url()" in body
    # 주소를 print 하는 자리가 없다
    assert "print(notify.webhook_url" not in body


# --- service -----------------------------------------------------------------


def test_service_install_이_유닛을_쓴다(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert run(["service", "install"]) == 0
    out = capsys.readouterr().out
    assert "유닛을 썼어요" in out
    from app.service import units

    for name in units.UNITS:
        assert os.path.exists(units.unit_path(name))


def test_service_install_은_활성화하지_않는다(tmp_path, monkeypatch, capsys):
    """🔑 `enable --now` 는 **루프를 실제로 띄운다** — 사람이 말하는 순간이어야 한다."""
    import inspect
    import subprocess

    from app.service import units

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def boom(*a, **k):
        raise AssertionError(f"명령을 돌리면 안 돼요: {a}")

    monkeypatch.setattr(subprocess, "run", boom)
    assert run(["service", "install"]) == 0
    out = capsys.readouterr().out
    assert "활성화는 **사람이**" in out or "활성화는" in out
    for line in ("loginctl enable-linger", "systemctl --user enable --now"):
        assert line in out
    # 위의 `subprocess.run` 가로채기가 증거다 — 아무 명령도 안 돌렸다.
    # `units.install()` 자체도 파일만 쓴다.
    install_src = inspect.getsource(units.install)
    assert "subprocess" not in install_src
    assert "enable" not in install_src


def test_유닛에_API_키가_없다(tmp_path, monkeypatch):
    """키가 섞이면 구독이 아니라 종량제 과금이다."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    for name in units.UNITS:
        body = units.render(name)
        assert "Environment=ANTHROPIC" not in body
        # 자동 업데이트는 끈다 (S5b)
        assert "Environment=DISABLE_AUTOUPDATER=1" in body
        # 학습은 유닛을 멈춰도 안 죽는다
        assert "KillMode=mixed" in body


def test_유닛_PATH_에_세션_전용_경로가_없다(tmp_path, monkeypatch):
    """지금 셸의 `PATH` 를 베끼면 VS Code 서버 경로처럼 **나중에 없어질 것**이
    섞인다 (실제로 그랬다)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    line = [
        l for l in units.render("labremote-monitor").splitlines()
        if l.startswith("Environment=PATH=")
    ][0]
    assert "vscode-server" not in line
    assert "/usr/bin" in line
    # 중복이 없다
    parts = line.split("=", 2)[-1].split(":")
    assert len(parts) == len(set(parts)), parts


def test_service_status_가_유닛_둘만_본다(tmp_path, monkeypatch, capsys):
    """`systemctl --user` 전체가 degraded 인 것은 snap 탓이라 무관하다."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    monkeypatch.setattr(units, "_systemctl", lambda: "/bin/systemctl")
    import subprocess

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "enabled\n", ""),
    )
    code = run(["service", "status"])
    out = capsys.readouterr().out
    for name in units.UNITS:
        assert name in out
    assert code in (0, 1)


def test_service_install_dry_run_은_안_쓴다(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    assert run(["service", "install", "--dry-run"]) == 0
    assert "[Unit]" in capsys.readouterr().out
    assert not os.path.exists(units.unit_path("labremote-monitor"))


def test_notify_test_가_성공을_성공으로_본다(isolated_data, isolated_config, monkeypatch, capsys):
    """🔑 `notifier.send` 는 `sent`·`status` 를 돌려준다 — `ok`·`httpStatus` 가
    아니다. 처음에 그걸 잘못 봐서 **204 로 잘 갔는데 화면엔 "✘ 못 보냈어요"**
    가 떴다. 사람이 직접 돌려 보고 잡았다.
    """
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "send",
        lambda *a, **k: {"sent": True, "status": 204, "id": 1, "dedupeKey": "x"},
    )
    assert run(["notify", "test"]) == 0
    out = capsys.readouterr().out
    assert "✔ 보냈어요 (상태 204)" in out
    assert "못 보냈어요" not in out


def test_notify_test_가_실패를_실패로_본다(isolated_data, isolated_config, monkeypatch, capsys):
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "send",
        lambda *a, **k: {"sent": False, "status": 403, "reason": "HTTP Error 403"},
    )
    assert run(["notify", "test"]) == 2
    err = capsys.readouterr().err
    assert "못 보냈어요" in err and "403" in err


def test_notify_test_가_중복_제거를_실패로_안_본다(isolated_data, isolated_config, monkeypatch, capsys):
    """같은 알림을 또 보내려 한 것은 **실패가 아니다.**"""
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "send",
        lambda *a, **k: {"sent": False, "suppressed": True, "dedupeKey": "k"},
    )
    assert run(["notify", "test"]) == 0
    assert "눌렸어요" in capsys.readouterr().out


def test_notifier_의_반환_칸_이름을_고정한다(isolated_data, isolated_config, monkeypatch):
    """CLI 가 보는 칸 이름이 바뀌면 조용히 뒤집힌다 — 그걸 막는다."""
    from app import notifier

    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/a/b")
    monkeypatch.setattr(
        notifier, "_post",
        lambda *a, **k: {"sent": True, "status": 204},
        raising=False,
    )
    from app import db

    with db.open_db() as conn:
        got = notifier.send(conn, "test", title="x", body="y", subject="s1")
    assert "sent" in got, got
    assert "ok" not in got, "칸 이름이 바뀌었어요 — CLI 도 같이 고쳐 주세요"


# --- 🔑 학습이 오케스트레이터 재시작에 안 죽나 -------------------------------


def test_setsid_는_cgroup_을_안_바꾼다():
    """실측(2026-11-05)으로 고정한다 — 이 전제가 틀렸다는 걸 사람이 잡았다.

    세션 ID 는 떨어지지만 cgroup 은 그대로다. 그래서 오케스트레이터 유닛의
    cgroup 안에 남고, `KillMode=mixed` 가 메인 프로세스 종료 뒤 남은 것들에
    **SIGKILL** 을 보낸다 — `systemctl --user restart` 한 번에 몇 시간 돌던
    학습이 같이 죽는다.
    """
    import os
    import subprocess
    import time

    mine = open(f"/proc/{os.getpid()}/cgroup").read().strip()
    child = subprocess.Popen(["/bin/sh", "-c", "sleep 5"], start_new_session=True)
    try:
        time.sleep(0.3)
        theirs = open(f"/proc/{child.pid}/cgroup").read().strip()
        assert theirs == mine, "cgroup 이 달라졌어요 — 전제가 바뀌었어요"
        # 세션은 떨어진다
        assert os.getsid(child.pid) != os.getsid(os.getpid())
    finally:
        child.kill()
        child.wait()


def test_유닛이_KillMode_process_다(tmp_path, monkeypatch):
    """`mixed` 였으면 남은 학습에 SIGKILL 이 간다. 2차 방어다."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from app.service import units

    for name in units.UNITS:
        # 주석에도 `KillMode=mixed` 가 설명으로 나오니 **지시문만** 본다
        directives = [
            l.strip() for l in units.render(name).splitlines()
            if l.strip().startswith("KillMode=")
        ]
        assert directives == ["KillMode=process"], directives


def test_scope_이름이_프로젝트와_실험으로_정해진다():
    """이름으로 상태 확인·종료·중복 방지가 된다."""
    from app.runner import process as P
    from app.runner.spec import RunSpec

    spec = RunSpec(project="hook-sandbox", root="/x", experiment_id="EXP-007",
                   entrypoint="t.py", entrypoint_abs="/x/t.py")
    assert P.scope_name(spec) == "labremote-train-hook-sandbox-EXP-007"
    # 이상한 글자는 걸러낸다 (유닛 이름에 쓸 수 없다)
    odd = RunSpec(project="a b/c", root="/x", experiment_id="EXP-1;rm",
                  entrypoint="t.py", entrypoint_abs="/x/t.py")
    name = P.scope_name(odd)
    assert all(c.isalnum() or c in "-_" for c in name), name


def test_scope_접두사가_argv_앞에_붙는다():
    from app.runner import process as P
    from app.runner.spec import RunSpec

    spec = RunSpec(project="p", root="/x", experiment_id="EXP-1",
                   entrypoint="t.py", entrypoint_abs="/x/t.py")
    plain = P.build_argv(spec, use_sandbox=False)
    scoped = P.build_argv(spec, use_sandbox=False, use_scope=True)
    assert scoped[0] == "systemd-run"
    assert "--user" in scoped and "--scope" in scoped
    assert f"--unit={P.scope_name(spec)}" in scoped
    # 나머지는 그대로다
    assert scoped[scoped.index("--") + 1:] == plain


def test_build_argv_는_기본으로_scope_를_안_붙인다():
    """`build_argv` 는 "무엇을 돌리나" 고 scope 는 "어디에 담나" 다 —
    실제로 띄우는 `launch()` 가 정한다. 그래야 argv 시험이 systemd 에
    매이지 않는다."""
    from app.runner import process as P
    from app.runner.spec import RunSpec

    spec = RunSpec(project="p", root="/x", experiment_id="EXP-1",
                   entrypoint="t.py", entrypoint_abs="/x/t.py")
    assert P.build_argv(spec, use_sandbox=False)[0] != "systemd-run"


def test_scope_를_못_쓰면_조용히_빠진다(monkeypatch):
    """user systemd 가 없는 환경(컨테이너·cron). 그때는 KillMode=process 가 지킨다."""
    from app.runner import process as P

    monkeypatch.setenv(P.NO_SCOPE_ENV, "1")
    assert P.scope_available() is False
    monkeypatch.delenv(P.NO_SCOPE_ENV)
    monkeypatch.setattr(P.shutil, "which", lambda name, path=None: None)
    assert P.scope_available() is False
