"""🔑 허가 서명 키 — `labremote keys`.

승인(`labremote approvals approve`)이 1회용 허가를 **HMAC 으로 서명**한다.
키가 없으면 `grants.verify` 가 전부 거짓이 되어 **헤드리스 승인이 아예 안
된다** — 훅이 허가를 무시하고 그대로 막는다(fail-closed).

이게 `doctor` 에 **없었다**(S9 e2e 가 잡았다). 사람이 `approve` 를 돌려서
실패할 때까지 알 수 없었고, 그때의 안내는 **없는 명령**을 가리켰다
(`labremote service install` — 8단계에서 만들 것).
"""

import os

import pytest

from app import cli, config, doctor


@pytest.fixture()
def keydir(isolated_config):
    return config.grant_key_path()


# --- doctor ------------------------------------------------------------------


def test_doctor_가_키_없음을_잡는다(keydir):
    got = doctor.grant_key_check()
    assert got["ok"] is False and got["level"] == "bad"
    assert "헤드리스 승인이 안 돼요" in got["detail"]
    assert "labremote keys init" in got["hint"]
    # 없는 명령을 가리키지 않는다
    assert "service install" not in got["hint"]


def test_doctor_가_넓은_권한을_잡는다(keydir):
    config.ensure_grant_key()
    os.chmod(keydir, 0o644)
    got = doctor.grant_key_check()
    assert got["ok"] is False
    assert "권한이 넓어요" in got["detail"]
    assert "--fix-mode" in got["hint"]


def test_doctor_가_빈_키를_잡는다(keydir):
    os.makedirs(os.path.dirname(keydir), exist_ok=True)
    os.close(os.open(keydir, os.O_WRONLY | os.O_CREAT, 0o600))
    got = doctor.grant_key_check()
    assert got["ok"] is False and "비어 있어요" in got["detail"]


def test_doctor_가_제대로_된_키를_통과시킨다(keydir):
    config.ensure_grant_key()
    assert doctor.grant_key_check()["ok"] is True


def test_키가_없으면_doctor_종료코드가_1_이다(keydir, capsys, monkeypatch):
    """승인이 불가능한 상태다 — ⚠ 가 아니라 ✘ 다."""
    report = {
        "ok": True, "warnings": [],
        "checks": [doctor.grant_key_check()], "limitations": [],
    }
    report["ok"] = not any(c.get("level") == "bad" for c in report["checks"])
    monkeypatch.setattr(doctor, "run", lambda: report)
    assert cli.main(["doctor"]) == 1


# --- labremote keys ----------------------------------------------------------


def test_init_이_0600_으로_만든다(keydir, capsys):
    assert cli.main(["keys", "init"]) == 0
    out = capsys.readouterr().out
    assert "키를 만들었어요" in out
    assert config.mode_of(keydir) == 0o600
    assert config.is_private(keydir) is True
    assert len(config.grant_key() or b"") == 64  # 32바이트의 hex


def test_키_값을_화면에_안_찍는다(keydir, capsys):
    cli.main(["keys", "init"])
    made = capsys.readouterr().out
    raw = (config.grant_key() or b"").decode("ascii")
    assert raw and raw not in made
    # 길이만 보여 준다
    cli.main(["keys", "show"])
    shown = capsys.readouterr().out
    assert raw not in shown
    assert "길이" in shown and "64자" in shown


def test_이미_있으면_덮어쓰지_않는다(keydir, capsys):
    cli.main(["keys", "init"])
    capsys.readouterr()
    before = config.grant_key()

    assert cli.main(["keys", "init"]) == 0
    out = capsys.readouterr().out
    assert "이미 있어요" in out and "덮어쓰지 않아요" in out
    assert config.grant_key() == before, "키가 바뀌면 안 쓴 허가가 전부 무효가 돼요"


def test_fix_mode_는_권한만_고친다(keydir, capsys):
    cli.main(["keys", "init"])
    capsys.readouterr()
    before = config.grant_key()
    os.chmod(keydir, 0o644)

    assert cli.main(["keys", "init"]) == 1  # 안내만 하고 안 고친다
    assert config.mode_of(keydir) == 0o644
    capsys.readouterr()

    assert cli.main(["keys", "init", "--fix-mode"]) == 0
    assert config.mode_of(keydir) == 0o600
    assert config.grant_key() == before, "권한만 고쳐야 해요"


def test_show_는_없으면_종료코드_1(keydir, capsys):
    assert cli.main(["keys", "show"]) == 1
    assert "labremote keys init" in capsys.readouterr().out


# --- 안내가 있는 명령을 가리키나 ---------------------------------------------


def test_오류_안내가_있는_명령을_가리킨다(project, project_root, isolated_config):
    """🔑 전에는 `labremote service install` 을 가리켰고 **그 명령은 없다**(8단계)."""
    from app import grants

    with pytest.raises(grants.GrantError) as exc:
        grants.issue(
            "hook-sandbox", tool="Bash", tool_input={"command": "x"},
            action_key="del", session_id="s",
        )
    text = str(exc.value)
    assert "labremote keys init" in text
    assert "service install" not in text

    # 그 명령이 실제로 있다
    parser = cli.build_parser()
    assert parser.parse_args(["keys", "init"]).func is cli.cmd_keys


# --- 🩺 계획에 적힌 doctor 점검이 **실제로 다 있나** -------------------------


def test_계획에_적힌_점검이_전부_run_에_붙어_있다():
    """🔑 `grant_key` 와 GPU 가 **아예 빠져 있었다.**

    함수는 있는데(`monitor/gpu.probe`) `doctor` 가 부르지 않거나, 계획에만
    적혀 있고 구현이 없는 경우다. 둘 다 "기록은 있는데 안 돈다" 는 같은
    종류의 거짓이다 — S5b·S9 와 같은 가족이다.

    새 점검을 더할 때 이 목록도 같이 늘린다. **②의 범위**만 본다 —
    7·8단계 것(linger·유닛·DB 스키마 판 …)은 그 단계에서 더한다.
    """
    import inspect

    from app import doctor as d

    run_src = inspect.getsource(d.run)
    must = [
        "permission_mode_check",   # 권한 기본 모드
        "sandbox_check",           # 학습 샌드박스 (bwrap + apparmor)
        "bash_sandbox_check",      # Bash 샌드박스 설정
        "project_settings_check",  # 프로젝트 설정 정본 (M6)
        "git_anchor_check",        # git 기록 앵커 (T5)
        "project_env_check",       # 실험 conda 환경 (.pth)
        "audit_check",             # 승인 기록 진본 (S7)
        "cache_check",             # 공용 캐시
        "grant_key_check",         # 허가 서명 키 (S9 가 빠진 것을 잡았다)
        "gpu_check",               # GPU 조회 (⚠)
        "gpu_driver_check",        # 드라이버 불일치·재부팅 대기
        "claude_version_check",    # Claude Code 판 (S5c)
        "user_sandbox_check",      # 사용자 설정에 sandbox
        "shell_guard_check",       # 셸 보호 함수 (⚠)
    ]
    missing = [name for name in must if f"{name}(" not in run_src]
    assert missing == [], missing


def test_정의한_점검_함수가_전부_불린다():
    """정의만 하고 안 부르면 **있는 척**이 된다."""
    import inspect

    from app import doctor as d

    run_src = inspect.getsource(d.run)
    defined = [
        n for n in dir(d)
        if n.endswith("_check") and inspect.isfunction(getattr(d, n))
    ]
    assert defined, "점검 함수를 못 찾았어요"
    unused = [n for n in defined if f"{n}(" not in run_src]
    assert unused == [], unused


def test_GPU_조회_실패는_경고다(monkeypatch):
    """실패가 **정상 경로**다 — 가짜 학습은 돈다(spec: ② 검증은 가짜 학습부터)."""
    from app import doctor as d
    from app.monitor import gpu

    monkeypatch.setattr(
        gpu, "probe",
        lambda: {"available": False, "reason": "Driver/library version mismatch", "devices": []},
    )
    got = d.gpu_check()
    assert got["level"] == "warn"
    assert "조회 불가" in got["detail"]


def test_드라이버_불일치는_거부다(monkeypatch):
    """재부팅 전에는 학습이 실패한다 — guards 가 train 을 안 띄운다."""
    from app import doctor as d
    from app.monitor import gpu

    monkeypatch.setattr(
        gpu, "driver_state",
        lambda: {"ok": False, "kernel": "595.84", "userland": "595.99.02",
                 "mismatch": True, "reason": ""},
    )
    got = d.gpu_driver_check()
    assert got["level"] == "bad"
    assert "595.84" in got["detail"] and "595.99.02" in got["detail"]
    assert "재부팅" in got["hint"]


def test_nvidia_재부팅_대기는_경고다(monkeypatch):
    """아직 안 깨졌지만 곧 깨진다 — 미리 알린다."""
    from app import doctor as d
    from app.monitor import gpu

    monkeypatch.setattr(
        gpu, "driver_state",
        lambda: {"ok": True, "kernel": "595.99.02", "userland": "595.99.02",
                 "mismatch": False, "reason": ""},
    )
    monkeypatch.setattr(
        gpu, "reboot_pending",
        lambda: {"pending": True, "packages": ["nvidia-driver-595"],
                 "nvidia": ["nvidia-driver-595"]},
    )
    got = d.gpu_driver_check()
    assert got["level"] == "warn" and "nvidia" in got["detail"]
