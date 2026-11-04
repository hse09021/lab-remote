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
