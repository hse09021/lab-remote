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
    """bwrap 을 못 쓰는 환경(샌드박스 안에서 시험을 돌리는 경우 등)에서는
    "학습 샌드박스" 만 ✘ 다 — 그건 `doctor` 가 알려 줘야 할 사실이다."""
    from app.runner import sandbox

    run(["hooks", "install", "--mode", "enforce"])
    capsys.readouterr()
    code = run(["doctor"])
    out = capsys.readouterr().out
    if sandbox.available()["ok"]:
        assert code == 0, out
        return
    failed = [line for line in out.splitlines() if line.startswith("✘")]
    assert failed and all("학습 샌드박스" in line for line in failed), out


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


# --- log 표시 (실측: 긴 경로가 잘려 무엇이 막혔는지 안 보였다) ----------------


def test_긴_경로는_앞을_줄여_파일_이름을_남긴다():
    path = "/home/hse09021/Desktop/lab-remote/server/data/policies/hook-sandbox.json"
    got = cli._shorten(path, 60)
    assert len(got) <= 60
    assert got.startswith("…")
    assert got.endswith("policies/hook-sandbox.json")


def test_긴_명령은_뒤를_줄여_명령_이름을_남긴다():
    command = "pip install " + "아주긴패키지이름 " * 20
    got = cli._shorten(command, 60)
    assert got.startswith("pip install")
    assert got.endswith("…")


def test_짧은_건_그대로():
    assert cli._shorten("src/a.py", 60) == "src/a.py"


def test_log_는_한_호출을_한_줄로(capsys, made):
    from app import approval_log as A

    path = A.log_path(made["target"])
    A.append_row(path, action="패키지 설치", request="pip install peft", result="대기 중",
                 pending=True, tool_use_id="t1")
    A.append_row(path, action="패키지 설치", request="pip install peft",
                 result="거부 또는 미응답", tool_use_id="t1")
    A.append_row(path, action="패키지 설치", request="pip install peft", result="허용",
                 tool_use_id="t1")

    assert run(["log", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert out.count("패키지 설치") == 1
    assert "허용" in out and "거부 또는 미응답" not in out


def test_log_raw_는_전부_보여_준다(capsys, made):
    from app import approval_log as A

    path = A.log_path(made["target"])
    A.append_row(path, action="패키지 설치", request="pip install peft", result="대기 중",
                 pending=True, tool_use_id="t1")
    A.append_row(path, action="패키지 설치", request="pip install peft", result="허용",
                 tool_use_id="t1")
    assert run(["log", "hook-sandbox", "--raw"]) == 0
    out = capsys.readouterr().out
    assert out.count("패키지 설치") == 2


# --- pending ----------------------------------------------------------------


def open_ask(tool_use_id="t1", session_id="sess-1"):
    from app import approval_log as A

    A.open_pending(
        "hook-sandbox",
        tool_use_id,
        {
            "promptId": "p1",
            "sessionId": session_id,
            "tool": "Bash",
            "action": "패키지 설치",
            "request": "pip install peft",
        },
    )


def test_pending_list(capsys, made):
    open_ask()
    assert run(["pending", "list", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "패키지 설치" in out and "sess-1" in out


def test_pending_list_가_비면_그렇게_말한다(capsys, made):
    assert run(["pending", "list", "hook-sandbox"]) == 0
    assert "없어요" in capsys.readouterr().out


def test_pending_sweep_이_마감_행을_남긴다(capsys, made):
    from app import approval_log as A

    open_ask()
    assert run(["pending", "sweep", "hook-sandbox"]) == 0
    assert "1건을 마감했어요" in capsys.readouterr().out
    assert A.list_pending("hook-sandbox") == []
    assert A.read_rows(A.log_path(made["target"]))[-1]["result"] == A.RESULT_NO_ANSWER


def test_pending_sweep_은_세션을_고를_수_있다(capsys, made):
    from app import approval_log as A

    open_ask("t1", "sess-1")
    open_ask("t2", "sess-2")
    run(["pending", "sweep", "hook-sandbox", "--session", "sess-1"])
    left = [item["toolUseId"] for item in A.list_pending("hook-sandbox")]
    assert left == ["t2"]


def test_pending_은_등록_안_된_프로젝트에_1(capsys):
    assert run(["pending", "list", "없는것"]) == 1


# --- requests ---------------------------------------------------------------


def test_requests_list_와_clear(capsys, made):
    from app import approval_log as A

    A.open_request("hook-sandbox", "r1", {"action": "패키지 설치", "request": "pip install peft"})
    assert run(["requests", "list", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "r1" in out and "②의 승인 대기열" in out

    assert run(["requests", "clear", "hook-sandbox"]) == 0
    assert "1건을 정리했어요" in capsys.readouterr().out
    assert A.list_requests("hook-sandbox") == []
    assert A.read_rows(A.log_path(made["target"]))[-1]["action"] == "승인 요청 정리"


def test_requests_clear_는_하나만_고를_수_있다(capsys, made):
    from app import approval_log as A

    A.open_request("hook-sandbox", "r1", {"action": "패키지 설치", "request": "a"})
    A.open_request("hook-sandbox", "r2", {"action": "파일 삭제", "request": "b"})
    run(["requests", "clear", "hook-sandbox", "--id", "r1"])
    assert [item["requestId"] for item in A.list_requests("hook-sandbox")] == ["r2"]


# --- policy migrate ---------------------------------------------------------


def test_policy_migrate(capsys, made):
    from app import policy, registry

    pol = policy.load("hook-sandbox")
    data = dict(pol.data)
    data["version"] = 1
    registry.write_json(pol.path, data)

    assert run(["policy", "migrate", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    from app import policy_defaults as D

    assert f"1 → {D.POLICY_VERSION}" in out
    assert "defaultMode=default" in out
    assert policy.load("hook-sandbox").headless["onAsk"] == "deny-with-reason"


def test_pending_list_가_에이전트를_찍는다(capsys, made):
    from app import approval_log as A

    A.open_pending(
        "hook-sandbox",
        "t-agent",
        {
            "promptId": "p1",
            "sessionId": "sess-1",
            "tool": "Write",
            "action": "코드 수정",
            "request": "experiments/EXP-002/c.py",
            "agentId": "a85e6d7a23abaefce",
            "agentType": "general-purpose",
        },
    )
    assert run(["pending", "list", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "에이전트 general-purpose" in out
    assert "a85e6d7a" in out


def test_pending_sweep_은_서브에이전트_건도_닫는다(capsys, made):
    """사람이 손으로 정리할 때는 전부 닫아요."""
    from app import approval_log as A

    A.open_pending("hook-sandbox", "t-agent", {"sessionId": "s", "action": "코드 수정",
                                               "request": "c.py", "agentId": "aaaa1111"})
    assert run(["pending", "sweep", "hook-sandbox"]) == 0
    assert A.list_pending("hook-sandbox") == []
