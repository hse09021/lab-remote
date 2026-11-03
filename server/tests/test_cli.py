"""`labremote` 명령 시험. doctor 와 hooks check 포함."""

import json
import os

import pytest

from app import cli, doctor, policy, registry, runstate
from app.generator import scaffold
from app.generator.spec import ProjectSpec
from app.hooks import check as hooks_check
from app.hooks import install


@pytest.fixture(autouse=True)
def fake_settings(tmp_path, monkeypatch):
    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"effortLevel": "high"}), encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(path))
    return path


@pytest.fixture()
def made():
    return scaffold.create_project(ProjectSpec("hook-sandbox", goal="훅·생성기 검증용"))


def run(argv):
    return cli.main(argv)


# --- init-project -----------------------------------------------------------


def test_dry_run(capsys):
    assert run(["init-project", "hook-sandbox", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "hook-sandbox/" in out and "CLAUDE.md" in out


def test_dry_run_json(capsys):
    assert run(["--json", "init-project", "hook-sandbox", "--dry-run"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 24


def test_생성(capsys):
    assert run(["init-project", "hook-sandbox", "--goal", "훅 검증"]) == 0
    out = capsys.readouterr().out
    assert "만들었어요" in out and "첫 커밋" in out
    assert registry.root_of("hook-sandbox")


def test_생성_실패는_종료코드_2(capsys, made):
    assert run(["init-project", "hook-sandbox"]) == 2
    assert "✘" in capsys.readouterr().err


def test_나쁜_이름도_종료코드_2(capsys):
    assert run(["init-project", "../../etc"]) == 2


# --- policy -----------------------------------------------------------------


def test_policy_show(capsys, made):
    assert run(["policy", "show", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "수동제어" in out or "manual" in out
    assert "🔒" in out  # 잠긴 항목 표시
    assert "자동 허용" in out or "승인 필요" in out


def test_policy_set(capsys, made):
    assert run(["policy", "set", "hook-sandbox", "--mode", "full", "--override", "pkg=allow"]) == 0
    pol = policy.load("hook-sandbox")
    assert pol.effective_mode() == "full"
    assert pol.resolve("pkg") == "allow"
    assert "다음 작업부터" in capsys.readouterr().out


def test_policy_set_이_Decision_log_에_남는다(made):
    from app import loop_layout as L

    run(["policy", "set", "hook-sandbox", "--mode", "error"])
    body = open(os.path.join(made["target"], L.LOOP_LAYOUT["decision_log"]), encoding="utf-8").read()
    assert "권한 설정 변경" in body and "error" in body


def test_잠긴_항목은_set_으로_못_바꾼다(capsys, made):
    assert run(["policy", "set", "hook-sandbox", "--override", "outside=allow"]) == 2
    assert policy.load("hook-sandbox").resolve("outside") == "block"


def test_sync_template(capsys):
    assert run(["policy", "sync-template"]) == 0
    assert "policy.default.json" in capsys.readouterr().out


# --- run-state --------------------------------------------------------------


def test_run_state(capsys, made):
    assert run(["run-state", "hook-sandbox", "--running", "EXP-001"]) == 0
    assert "EXP-001" in capsys.readouterr().out
    assert runstate.load("hook-sandbox").running

    assert run(["run-state", "hook-sandbox", "--idle"]) == 0
    out = capsys.readouterr().out
    assert "아니요" in out
    assert "EXP-001" in out  # started 목록은 남는다


# --- log --------------------------------------------------------------------


def test_log_tail(capsys, made, hook_event):
    from app.hooks import pretooluse

    pretooluse.handle(hook_event("Write", {"file_path": "/etc/hosts"}, cwd=made["target"]))
    assert run(["log", "hook-sandbox"]) == 0
    assert "차단" in capsys.readouterr().out


def test_log_은_없는_프로젝트에_1(capsys):
    assert run(["log", "없는프로젝트"]) == 1


# --- hooks ------------------------------------------------------------------


def test_hooks_install_status_uninstall(capsys):
    assert run(["hooks", "install", "--mode", "dump"]) == 0
    assert "되돌리기" in capsys.readouterr().out

    assert run(["hooks", "status"]) == 0
    assert "PreToolUse" in capsys.readouterr().out

    assert run(["hooks", "uninstall"]) == 0
    assert "제거" in capsys.readouterr().out


def test_hooks_check_는_훅이_없으면_1(capsys, made):
    assert run(["hooks", "check"]) == 1
    assert "훅이 없어요" in capsys.readouterr().out


def test_hooks_check_는_dump_모드에서_1(capsys, made):
    run(["hooks", "install", "--mode", "dump"])
    capsys.readouterr()
    assert run(["hooks", "check"]) == 1
    assert "dump 모드" in capsys.readouterr().out


def test_hooks_check_가_enforce_에서_전부_통과(capsys, made, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_PROJECTS_DIR", os.environ["LAB_PROJECTS_DIR"])
    run(["hooks", "install", "--mode", "enforce"])
    capsys.readouterr()
    code = run(["hooks", "check"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "전부 통과했어요" in out
    assert "✘" not in out


def test_hooks_check_가_프로젝트_없이는_1(capsys):
    run(["hooks", "install", "--mode", "enforce"])
    capsys.readouterr()
    assert run(["hooks", "check"]) == 1


# --- doctor -----------------------------------------------------------------


def test_doctor_는_훅이_없으면_빨간불(capsys, made):
    assert run(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "✘ 훅 등록" in out
    assert "labremote hooks install" in out


def test_doctor_는_dump_모드를_알려_준다(capsys, made):
    run(["hooks", "install", "--mode", "dump"])
    capsys.readouterr()
    run(["doctor"])
    out = capsys.readouterr().out
    assert "판정 모드" in out and "아무것도 막지 않아요" in out


def test_doctor_가_enforce_에서_초록(capsys, made):
    run(["hooks", "install", "--mode", "enforce"])
    capsys.readouterr()
    code = run(["doctor"])
    out = capsys.readouterr().out
    assert code == 0, out


def test_doctor_가_한계를_매번_안내(capsys, made):
    run(["doctor"])
    out = capsys.readouterr().out
    assert "항상 이 프로젝트 폴더 안에서" in out
    assert ".mcp.json" in out


def test_doctor_가_좀비_실행_상태를_잡는다(capsys, made):
    runstate.set_running("hook-sandbox", "EXP-001", pid=2 ** 22)
    run(["doctor"])
    out = capsys.readouterr().out
    assert "프로세스가 없어요" in out


def test_doctor_가_잠금_풀림을_잡는다(capsys, made):
    pol = policy.load("hook-sandbox")
    for action in pol.data["actions"]:
        if action["key"] == "prev":
            action["defaults"] = {"manual": "allow", "error": "allow", "full": "allow"}
    policy.save(pol)
    run(["doctor"])
    assert "풀린 항목" in capsys.readouterr().out


def test_doctor_json(capsys, made):
    run(["--json", "doctor"])
    report = json.loads(capsys.readouterr().out)
    assert "checks" in report and "limitations" in report
