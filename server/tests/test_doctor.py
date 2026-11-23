"""🩺 `labremote doctor` (v3) — PLAN 4.1 의 점검 + GPU·비밀값.

`doctor` 는 **읽기만 한다.** 고칠 명령은 `hint` 로 알려 준다.
"""

import os
import sys

from app import doctor


# --- 무게 --------------------------------------------------------------------


def test_경고는_종료코드를_안_바꾼다():
    report = {"ok": True, "checks": [doctor.warn("x", "y")], "limitations": []}
    text = doctor.render(report)
    assert "⚠ x" in text and "⚠ 는 종료코드를 바꾸지 않아요" in text


def test_run_은_v3_점검만_돈다(monkeypatch):
    """v1 의 훅·정책·샌드박스·앵커 점검은 없다."""
    names = [
        "conda_env_check", "claude_check", "tmux_check", "systemd_scope_check",
        "linger_check", "api_key_check", "webhook_check", "schema_check",
        "gpu_check", "gpu_driver_check",
    ]
    for name in names:
        monkeypatch.setattr(doctor, name, lambda n=name: doctor.Check(True, n))
    report = doctor.run()
    assert [c["title"] for c in report["checks"]] == names
    assert report["ok"] is True
    assert any("터널" in note for note in report["limitations"])


# --- 설치 --------------------------------------------------------------------


def test_conda_환경(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/opt/miniconda3/envs/labremote")
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    assert doctor.conda_env_check()["ok"] is True
    monkeypatch.setattr(sys, "prefix", "/opt/miniconda3")
    got = doctor.conda_env_check()
    assert got["level"] == "warn" and "conda activate labremote" in got["hint"]


def test_claude_가_없으면_실패(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    got = doctor.claude_check()
    assert got["level"] == "bad"
    assert "로그인을 대신하지 않아요" in got["hint"]


def test_claude_로그인을_계정_정보로_본다(monkeypatch):
    """자격 증명 파일을 읽지 않고, SDK 가 알려 주는 구독 종류만 쓴다(이메일은 안 찍는다)."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: (0, "2.1.318 (Claude Code)\n"))
    monkeypatch.setattr(doctor, "_login_probe", lambda: {"installed": True, "loggedIn": True, "plan": "Claude Max"})
    got = doctor.claude_check()
    assert got["ok"] is True and "로그인됨 · Claude Max" in got["detail"]
    monkeypatch.setattr(doctor, "_login_probe", lambda: {"installed": True, "loggedIn": False, "plan": ""})
    got = doctor.claude_check()
    assert got["ok"] is False and "/login" in got["hint"]

    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(doctor, "_login_probe", boom)
    assert doctor.claude_check()["level"] == "warn"


def test_tmux(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor.tmux_check()["level"] == "bad"
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/tmux")
    # conda 의 tmux 는 libtinfo 경고를 앞에 찍는다 — 판 줄만 고른다
    monkeypatch.setattr(
        doctor, "_run",
        lambda argv, timeout=10: (0, "tmux: libtinfo.so.6: no version information\ntmux 3.6a\n"),
    )
    got = doctor.tmux_check()
    assert got["ok"] is True and got["detail"].startswith("tmux 3.6a")


def test_systemd_scope(monkeypatch):
    from app.runner import process

    monkeypatch.setattr(process, "scope_available", lambda env=None: False)
    assert doctor.systemd_scope_check()["level"] == "warn"
    monkeypatch.setattr(process, "scope_available", lambda env=None: True)
    assert doctor.systemd_scope_check()["ok"] is True


def test_자동_시작이_꺼져_있으면_정상(monkeypatch):
    """linger 는 자동 시작을 켤 때만 필요하다 (PLAN 1.1)."""
    from app.service import units

    monkeypatch.setattr(units, "status", lambda: {
        "systemctl": "/bin/systemctl", "linger": False,
        "units": {"labremote-session": {"file": False}},
    })
    assert doctor.linger_check()["ok"] is True


def test_자동_시작이_켜졌는데_linger_가_꺼져_있으면_경고(monkeypatch):
    from app.service import units

    monkeypatch.setattr(units, "status", lambda: {
        "systemctl": "/bin/systemctl", "linger": False,
        "units": {"labremote-session": {"file": True, "enabled": "enabled"}},
    })
    got = doctor.linger_check()
    assert got["level"] == "warn" and "enable-linger" in got["hint"]


# --- 비밀값 ------------------------------------------------------------------


def test_API_키가_있으면_경고한다(monkeypatch):
    """키가 섞이면 구독 한도가 아니라 **종량제 과금**이다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    got = doctor.api_key_check()
    assert got["level"] == "warn" and "ANTHROPIC_API_KEY" in got["detail"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert doctor.api_key_check()["ok"] is True


def test_웹훅_권한이_넓으면_거부하고_주소는_안_찍는다():
    from app import config

    path = config.set_webhook("https://discord.com/api/webhooks/a/b")
    os.chmod(path, 0o644)
    got = doctor.webhook_check()
    assert got["level"] == "bad" and "권한이 넓어요" in got["detail"]

    os.chmod(path, 0o600)
    fixed = doctor.webhook_check()
    assert fixed["ok"] is True
    assert "webhooks/a/b" not in fixed["detail"]
    assert "••••" in fixed["detail"]


def test_웹훅이_없으면_경고한다():
    got = doctor.webhook_check()
    assert got["level"] == "warn" and "알림이 안 가요" in got["detail"]


def test_환경_변수로_들어오면_통과한다(monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/x/y")
    got = doctor.webhook_check()
    assert got["ok"] is True and "환경 변수" in got["detail"]


# --- DB 스키마 ---------------------------------------------------------------


def test_스키마_판이_맞으면_통과한다():
    from app import db

    got = doctor.schema_check()
    assert got["ok"] is True and f"판 {db.SCHEMA_VERSION}" in got["detail"]


def test_앞서_간_DB_는_거부한다():
    from app import db

    with db.open_db() as conn:
        conn.execute(
            "UPDATE schema_meta SET value=? WHERE key='version'", (str(db.SCHEMA_VERSION + 5),)
        )
        conn.commit()
    got = doctor.schema_check()
    assert got["level"] == "bad" and "새로워요" in got["detail"]


# --- nvidia 자동 업데이트 제외 (apt 적용값으로) -------------------------------


def _apt(entries, auto="false", ok=True, reason=""):
    return {"ok": ok, "entries": list(entries), "autoReboot": auto, "reason": reason}


def test_묶여_있으면_참고가_없다(monkeypatch):
    monkeypatch.setattr(doctor, "apt_blacklist", lambda: _apt(doctor.NVIDIA_BLACKLIST))
    assert doctor.nvidia_hold_note() is None


def test_빠졌으면_참고_한_줄_점검은_아니다(monkeypatch):
    partial = [i for i in doctor.NVIDIA_BLACKLIST if i != "cuda-"]
    monkeypatch.setattr(doctor, "apt_blacklist", lambda: _apt(partial, auto="true"))
    note = doctor.nvidia_hold_note()
    assert "cuda-" in note and "Automatic-Reboot" in note and "lab.remote 는 바꾸지 않아요" in note
    # 점검 목록에는 없다 — 경고 수를 늘리지 않는다
    monkeypatch.setattr(doctor, "run", doctor.run)
    assert "nvidia_hold_check" not in dir(doctor)


def test_apt_가_없는_기계에서는_말하지_않는다(monkeypatch):
    monkeypatch.setattr(doctor, "apt_blacklist", lambda: _apt([], auto=None, ok=False, reason="없는 명령"))
    assert doctor.nvidia_hold_note() is None


def test_apt_blacklist_가_dump_를_파싱한다(monkeypatch):
    dump = (
        'APT::Architecture "amd64";\n'
        'Unattended-Upgrade::Package-Blacklist "";\n'
        'Unattended-Upgrade::Package-Blacklist:: "nvidia-";\n'
        'Unattended-Upgrade::Package-Blacklist:: "cuda-";\n'
        'Unattended-Upgrade::Automatic-Reboot "false";\n'
    )
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: (0, dump))
    got = doctor.apt_blacklist()
    assert got["ok"] is True
    assert got["entries"] == ["nvidia-", "cuda-"]
    assert got["autoReboot"] == "false"
