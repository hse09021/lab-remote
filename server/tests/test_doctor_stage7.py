"""🩺 7단계 `doctor` 점검 일곱.

전부 **계획에 적혀 있었는데 구현이 없던** 것들이다. `grant_key`·GPU 와 같은
가족이다 — "기록은 있는데 안 돈다".
"""

import os

import pytest

from app import doctor


# --- nvidia 자동 업데이트 제외 (apt 적용값으로) -------------------------------


def _apt(entries, auto="false", ok=True, reason=""):
    return {"ok": ok, "entries": list(entries), "autoReboot": auto, "reason": reason}


def test_묶여_있으면_통과한다(monkeypatch):
    """🔑 **`apt-config dump` 의 적용값**을 본다 — 파일 이름이 아니라.

    설정이 여러 파일에 흩어지고 나중 파일이 앞을 덮으므로, 파일이 있는지로는
    알 수 없다.
    """
    monkeypatch.setattr(doctor, "apt_blacklist",
                        lambda: _apt(doctor.NVIDIA_BLACKLIST))
    got = doctor.nvidia_hold_check()
    assert got["ok"] is True
    assert f"{len(doctor.NVIDIA_BLACKLIST)}개 다" in got["detail"]


def test_빠진_항목을_이름으로_알려_준다(monkeypatch):
    partial = [i for i in doctor.NVIDIA_BLACKLIST if i != "cuda-"]
    monkeypatch.setattr(doctor, "apt_blacklist", lambda: _apt(partial))
    got = doctor.nvidia_hold_check()
    assert got["level"] == "warn"
    assert "cuda-" in got["detail"]


def test_Automatic_Reboot_가_켜져_있으면_경고한다(monkeypatch):
    """재부팅이 저절로 되면 학습이 도는 중에 꺼진다."""
    monkeypatch.setattr(doctor, "apt_blacklist",
                        lambda: _apt(doctor.NVIDIA_BLACKLIST, auto="true"))
    got = doctor.nvidia_hold_check()
    assert got["level"] == "warn" and "Automatic-Reboot" in got["detail"]


def test_apt_가_없는_기계에서는_경고만(monkeypatch):
    monkeypatch.setattr(doctor, "apt_blacklist",
                        lambda: _apt([], auto=None, ok=False, reason="없는 명령"))
    got = doctor.nvidia_hold_check()
    assert got["level"] == "warn" and "우분투가 아닌" in got["hint"]


def test_apt_blacklist_가_dump_를_파싱한다(monkeypatch):
    """실제 `apt-config dump` 꼴을 그대로 넣어 본다."""
    import subprocess

    dump = (
        'APT::Architecture "amd64";\n'
        'Unattended-Upgrade::Package-Blacklist "";\n'
        'Unattended-Upgrade::Package-Blacklist:: "nvidia-";\n'
        'Unattended-Upgrade::Package-Blacklist:: "cuda-";\n'
        'Unattended-Upgrade::Automatic-Reboot "false";\n'
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, dump, ""),
    )
    got = doctor.apt_blacklist()
    assert got["ok"] is True
    assert got["entries"] == ["nvidia-", "cuda-"]   # 빈 값은 걸러낸다
    assert got["autoReboot"] == "false"


# --- 추가 결제 차단 -----------------------------------------------------------


def test_API_키가_있으면_경고한다(monkeypatch):
    """키가 섞이면 구독 한도가 아니라 **종량제 과금**이다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    got = doctor.api_key_check()
    assert got["level"] == "warn" and "ANTHROPIC_API_KEY" in got["detail"]

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert doctor.api_key_check()["ok"] is True


# --- 웹훅 설정 ----------------------------------------------------------------


def test_웹훅_권한이_넓으면_거부한다(isolated_config, monkeypatch):
    from app import config

    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    path = config.config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('[discord]\nwebhook = "https://discord.com/api/webhooks/a/b"\n')
    os.chmod(path, 0o644)
    got = doctor.webhook_check()
    assert got["level"] == "bad" and "권한이 넓어요" in got["detail"]

    os.chmod(path, 0o600)
    fixed = doctor.webhook_check()
    assert fixed["ok"] is True
    # 🔑 주소는 **찍지 않는다**
    assert "webhooks/a/b" not in fixed["detail"]


def test_웹훅이_없으면_경고한다(isolated_config, monkeypatch):
    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    got = doctor.webhook_check()
    assert got["level"] == "warn" and "알림이 안 가요" in got["detail"]


def test_환경_변수로_들어오면_통과한다(isolated_config, monkeypatch):
    monkeypatch.setenv("LAB_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/x/y")
    got = doctor.webhook_check()
    assert got["ok"] is True and "환경 변수" in got["detail"]


# --- DB 스키마 ---------------------------------------------------------------


def test_스키마_판이_맞으면_통과한다(isolated_data):
    from app import db

    got = doctor.schema_check()
    assert got["ok"] is True and f"판 {db.SCHEMA_VERSION}" in got["detail"]


def test_앞서_간_DB_는_거부한다(isolated_data, monkeypatch):
    """새 코드가 만든 표를 옛 코드가 반쯤 이해한 채로 쓰면 조용히 틀린 값을 쓴다."""
    from app import db

    with db.open_db() as conn:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(db.SCHEMA_VERSION + 5),),
        )
        conn.commit()
    got = doctor.schema_check()
    assert got["level"] == "bad" and "새로워요" in got["detail"]


# --- 금지 명령 ---------------------------------------------------------------


def test_금지_명령이_다_있으면_통과한다(project):
    got = doctor.deny_commands_check(project)
    assert got["ok"] is True


def test_빠진_금지_명령을_이름으로_알려_준다(project):
    """자기 승인 차단(`labremote`·`sqlite3`…)이 빠지면 AI 가 자기를 승인한다."""
    from app import policy_defaults as D

    kept = [c for c in D.DENY_COMMANDS if c not in ("labremote", "sqlite3")]
    project.bash["denyCommands"] = kept
    got = doctor.deny_commands_check(project)
    assert got["level"] == "bad"
    assert "labremote" in got["detail"] and "sqlite3" in got["detail"]
    assert "policy migrate" in got["hint"]


def test_비어_있으면_거부한다(project):
    project.bash["denyCommands"] = []
    assert doctor.deny_commands_check(project)["level"] == "bad"


# --- 루프 상태 정합 (①의 숙제) ------------------------------------------------


def test_둘이_같으면_통과한다(project, project_root):
    got = doctor.loop_state_check(project_root, "hook-sandbox")
    assert got["ok"] is True


def test_서버만_실행_중이면_거부한다(project, project_root):
    """실측에서 둘이 어긋나(loop 0 vs EXP-002 running) Claude 가 잠금의 이유를
    설명하지 못했다. `Current.yaml` 이 근거 파일이므로 어긋나면 근거가 깨진다."""
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-002")
    got = doctor.loop_state_check(project_root, "hook-sandbox")
    assert got["level"] == "bad"
    assert "서버는 실행 중" in got["detail"]


def test_실험_번호가_다르면_거부한다(project, project_root):
    from app import loopstate, runstate

    runstate.set_running("hook-sandbox", "EXP-002")
    loopstate.write_current("hook-sandbox", project_root)
    # 서버 쪽만 다른 실험으로 바꾼다
    runstate.set_running("hook-sandbox", "EXP-009")
    got = doctor.loop_state_check(project_root, "hook-sandbox")
    assert got["level"] == "bad" and "EXP-009" in got["detail"]


# --- 승인 요청 잔여 -----------------------------------------------------------


def test_남은_요청을_경고한다(project):
    from app import approval_log as A

    assert doctor.leftover_requests_check("hook-sandbox")["ok"] is True
    A.open_request("hook-sandbox", "toolu_x", {"tool": "Bash", "request": "x"})
    got = doctor.leftover_requests_check("hook-sandbox")
    assert got["level"] == "warn" and "1건" in got["detail"]
    assert "requests clear" in got["hint"]
