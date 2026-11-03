"""설치된 래퍼를 실제로 띄워 보는 끝단 시험.

운영 문서(docs/operations.md)의 "결정 확인표" 와 같은 시나리오다.
여기서 초록이면 `claude -p` 로 손수 확인할 때 기대값을 알고 볼 수 있다.
"""

import json
import os
import subprocess
import sys

import pytest

from app import runstate
from app.hooks import install


@pytest.fixture()
def wrapper(project, project_root, tmp_path):
    """이 테스트의 임시 프로젝트 루트를 박은 래퍼."""
    return install.render_wrapper(roots=str(tmp_path / "projects"))


def run(wrapper, event, env=None):
    base = {
        "PATH": "",  # 절대 경로만 쓰는지 같이 본다
        "HOME": os.environ.get("HOME", "/tmp"),
        "LAB_DATA_DIR": os.environ["LAB_DATA_DIR"],
        "LAB_PROJECTS_DIR": os.environ["LAB_PROJECTS_DIR"],
        "CLAUDE_PROJECT_DIR": event.get("cwd", ""),
    }
    base.update(env or {})
    result = subprocess.run(
        ["/bin/sh", wrapper, "app.hooks.pretooluse"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=base,
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout:
        return None  # 래퍼가 건너뛴 것
    return json.loads(result.stdout)["hookSpecificOutput"]


def decision(wrapper, event, env=None):
    out = run(wrapper, event, env)
    return out["permissionDecision"] if out else "(건너뜀)"


# --- 운영 문서의 결정 확인표 --------------------------------------------------


def test_1_폴더_밖_쓰기는_차단(wrapper, project_root, hook_event):
    assert decision(wrapper, hook_event("Write", {"file_path": "/tmp/x.txt"}, cwd=project_root)) == "deny"


def test_2_실행_중_Evaluation_수정은_차단(wrapper, project_root, hook_event):
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    event = hook_event(
        "Edit",
        {"file_path": f"{project_root}/docs/Evaluation.md", "old_string": "a", "new_string": "b"},
        cwd=project_root,
    )
    assert decision(wrapper, event) == "deny"


def test_3_멈춰_있으면_승인_경로(wrapper, project_root, hook_event):
    runstate.set_idle("hook-sandbox")
    event = hook_event(
        "Edit",
        {"file_path": f"{project_root}/docs/Evaluation.md", "old_string": "a", "new_string": "b"},
        cwd=project_root,
    )
    assert decision(wrapper, event) == "ask"


def test_4_이전_실험_config_는_차단(wrapper, project_root, hook_event):
    folder = os.path.join(project_root, "experiments", "EXP-006")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "result.csv"), "w").close()
    event = hook_event("Write", {"file_path": f"{folder}/config.yaml"}, cwd=project_root)
    assert decision(wrapper, event) == "deny"


def test_5_이전_실험_analysis_는_승인(wrapper, project_root, hook_event):
    folder = os.path.join(project_root, "experiments", "EXP-006")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "result.csv"), "w").close()
    event = hook_event("Write", {"file_path": f"{folder}/analysis.md"}, cwd=project_root)
    assert decision(wrapper, event) == "ask"


def test_6_현재_실험_코드는_수동제어에서_승인(wrapper, project_root, hook_event):
    event = hook_event("Write", {"file_path": f"{project_root}/experiments/EXP-007/train.py"}, cwd=project_root)
    assert decision(wrapper, event) == "ask"


def test_7_패키지_설치는_승인(wrapper, project_root, hook_event):
    assert decision(wrapper, hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)) == "ask"


def test_8_안_돌린_실험_output_삭제는_승인(wrapper, project_root, hook_event):
    """준비 중인 폴더는 지울 수 있어야 한다 (돌린 실험은 아래 test_15)."""
    event = hook_event("Bash", {"command": "rm -rf experiments/EXP-009/output"}, cwd=project_root)
    assert decision(wrapper, event) == "ask"


def test_9_다운로드는_승인(wrapper, project_root, hook_event):
    event = hook_event("Bash", {"command": "curl -O https://example.com/w.bin"}, cwd=project_root)
    assert decision(wrapper, event) == "ask"


def test_10_프로젝트_안_claude_설정은_차단(wrapper, project_root, hook_event):
    event = hook_event("Write", {"file_path": f"{project_root}/.claude/settings.json"}, cwd=project_root)
    assert decision(wrapper, event) == "deny"


def test_11_정책_파일_수정은_차단(wrapper, project, project_root, hook_event):
    assert decision(wrapper, hook_event("Write", {"file_path": project.path}, cwd=project_root)) == "deny"


def test_12_기록_갱신은_조용히_허용(wrapper, project_root, hook_event):
    event = hook_event("Write", {"file_path": f"{project_root}/logs/Decision_log.md"}, cwd=project_root)
    assert decision(wrapper, event) == "allow"


@pytest.mark.parametrize("command", ["ls -la", "git status", "cat README.md"])
def test_13_읽기_명령에는_아무_일도_없다(wrapper, project_root, hook_event, command):
    assert decision(wrapper, hook_event("Bash", {"command": command}, cwd=project_root)) == "defer"


def test_14_등록_안_된_저장소에서는_간섭하지_않는다(wrapper, tmp_path, hook_event):
    """lab-remote 저장소에서 개발할 때 막히면 안 된다."""
    outside = tmp_path / "lab-remote"
    outside.mkdir()
    event = hook_event("Write", {"file_path": str(outside / "x.py")}, cwd=str(outside))
    assert decision(wrapper, event) == "(건너뜀)"  # 래퍼가 파이썬을 안 띄운다


def test_14b_프로젝트_루트_아래지만_등록_안_된_폴더(wrapper, tmp_path, hook_event):
    """래퍼는 통과시키지만 파이썬이 defer 로 끝낸다."""
    other = tmp_path / "projects" / "남의폴더"
    other.mkdir(parents=True)
    event = hook_event("Write", {"file_path": str(other / "x.py")}, cwd=str(other))
    assert decision(wrapper, event) == "defer"


# --- 실측 우회 시나리오 그대로 -----------------------------------------------


def test_실측_우회_흐름(wrapper, project_root, hook_event, real_event):
    """Edit 거절 -> Bash sed -> Write. 셋 다 같은 결정을 받아야 한다."""
    target = f"{project_root}/docs/Evaluation.md"
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())

    edit = hook_event("Edit", {"file_path": target, "old_string": "a", "new_string": "b"}, cwd=project_root)
    assert decision(wrapper, edit) == "deny"

    sed_cmd = real_event("232300-996652-PreToolUse-Bash")["tool_input"]["command"]
    sed_on_locked = sed_cmd.replace("README.md", "docs/Evaluation.md")
    assert decision(wrapper, hook_event("Bash", {"command": sed_on_locked}, cwd=project_root)) == "deny"

    write = hook_event("Write", {"file_path": target, "content": "x"}, cwd=project_root)
    assert decision(wrapper, write) == "deny"


def test_거절_사유에_우회_금지가_들어_있다(wrapper, project_root, hook_event):
    out = run(wrapper, hook_event("Write", {"file_path": "/etc/hosts"}, cwd=project_root))
    assert "작업을 멈추고 보고해 주세요" in out["permissionDecisionReason"]


# --- 판 2 에서 늘어난 잠금 (설치된 래퍼로) ------------------------------------


def output_file(project_root, exp="EXP-007", rel="output/train.log"):
    path = os.path.join(project_root, "experiments", exp, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("원본 출력\n")
    return path


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf experiments/EXP-007/output",
        ": > experiments/EXP-007/output/train.log",
        "truncate -s 0 experiments/EXP-007/output/train.log",
        "mv experiments/EXP-007/output/train.log /tmp/keep.log",
    ],
)
def test_15_도는_실험_산출물은_차단(wrapper, project_root, hook_event, command):
    """CLAUDE.md 의 "원본 출력을 보존해요" 를 훅이 실제로 강제한다."""
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    output_file(project_root)
    assert decision(wrapper, hook_event("Bash", {"command": command}, cwd=project_root)) == "deny"


def test_15_산출물_덮어쓰기도_차단(wrapper, project_root, hook_event):
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    path = output_file(project_root)
    event = hook_event("Write", {"file_path": path, "content": "덮어쓰기"}, cwd=project_root)
    assert decision(wrapper, event) == "deny"


def test_16_버린_출력은_간섭하지_않는다(wrapper, project_root, hook_event):
    """실측에서 `2>/dev/null` 이 "폴더 밖 쓰기" 로 막혔다."""
    event = hook_event("Bash", {"command": "ls -la .claude 2>/dev/null"}, cwd=project_root)
    assert decision(wrapper, event) == "defer"


def test_17_비밀_파일_읽기는_차단(wrapper, project_root, hook_event):
    with open(os.path.join(project_root, ".env"), "w", encoding="utf-8") as fh:
        fh.write("WANDB_API_KEY=비밀\n")
    event = hook_event("Read", {"file_path": f"{project_root}/.env"}, cwd=project_root)
    assert decision(wrapper, event) == "deny"


def test_17_예시_파일_읽기는_간섭하지_않는다(wrapper, project_root, hook_event):
    event = hook_event("Read", {"file_path": f"{project_root}/.env.example"}, cwd=project_root)
    assert decision(wrapper, event) == "defer"


def test_18_서버_보호_파일은_차단(wrapper, project_root, hook_event):
    from app import policy_defaults as D

    server_dir = D.hard_protected_roots()[0]
    event = hook_event(
        "Edit",
        {"file_path": f"{server_dir}/app/hooks/decide.py", "old_string": "a", "new_string": "b"},
        cwd=project_root,
    )
    assert decision(wrapper, event) == "deny"


def test_18_MCP_설정도_차단(wrapper, project_root, hook_event):
    event = hook_event("Write", {"file_path": os.path.expanduser("~/.claude.json")}, cwd=project_root)
    assert decision(wrapper, event) == "deny"


def test_19_헤드리스는_사유와_함께_거절(wrapper, project_root, hook_event):
    """실측: `claude -p` 의 ask 는 사람에게 안 가고 10초 안에 자동 거부된다."""
    from app.hooks import pretooluse

    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    out = run(wrapper, event, env={pretooluse.HEADLESS_ENV: "1", "LAB_NOTIFY_DISABLED": "1"})
    assert out["permissionDecision"] == "deny"
    assert "승인 요청을 남겨 두었어요" in out["permissionDecisionReason"]
    assert "작업을 멈추고 보고해 주세요" in out["permissionDecisionReason"]


def test_20_권한_우회_모드여도_잠금은_그대로(wrapper, project_root, hook_event):
    """판정은 permission_mode 를 읽지 않는다."""
    event = hook_event(
        "Write", {"file_path": "/tmp/x.txt"}, cwd=project_root, permission_mode="auto"
    )
    assert decision(wrapper, event) == "deny"


def test_21_UserPromptSubmit_이_이전_턴을_마감한다(wrapper, project, project_root, hook_event):
    """거부로 턴이 끊겨 Stop 이 안 돈 경우 (실측 B)."""
    import json as jsonmod
    import subprocess

    from app import approval_log as A

    ask = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                     prompt_id="예전", tool_use_id="t1")
    assert decision(wrapper, ask) == "ask"
    assert len(A.list_pending("hook-sandbox")) == 1

    result = subprocess.run(
        ["/bin/sh", wrapper, "app.hooks.userprompt"],
        input=jsonmod.dumps({"cwd": project_root, "session_id": "sess-테스트",
                             "prompt_id": "새것", "prompt": "다음 할 일"}),
        capture_output=True,
        text=True,
        env={
            "PATH": "",
            "HOME": os.environ.get("HOME", "/tmp"),
            "LAB_DATA_DIR": os.environ["LAB_DATA_DIR"],
            "LAB_PROJECTS_DIR": os.environ["LAB_PROJECTS_DIR"],
            "CLAUDE_PROJECT_DIR": project_root,
        },
    )
    assert result.returncode == 0 and result.stdout == ""
    assert A.list_pending("hook-sandbox") == []
    assert A.read_rows(A.log_path(project_root))[-1]["result"] == A.RESULT_NO_ANSWER


def run_module(wrapper, module, event):
    """기록용 훅(stdout 없음)을 래퍼로 띄운다."""
    result = subprocess.run(
        ["/bin/sh", wrapper, module],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env={
            "PATH": "",
            "HOME": os.environ.get("HOME", "/tmp"),
            "LAB_DATA_DIR": os.environ["LAB_DATA_DIR"],
            "LAB_PROJECTS_DIR": os.environ["LAB_PROJECTS_DIR"],
            "CLAUDE_PROJECT_DIR": str(event.get("cwd") or ""),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", result.stdout  # 아무것도 막지 않는다
    return result


def test_22_서브에이전트_대기_건은_Stop_이_아니라_SubagentStop_이_닫는다(
    wrapper, project, project_root, hook_event
):
    """실측 2026-11-04 02:03 사건. 설치된 래퍼로 끝까지 돌려 본다."""
    from app import approval_log as A

    agent_id = "a85e6d7a23abaefce"
    ask = hook_event(
        "Write",
        {"file_path": f"{project_root}/experiments/EXP-002/c.py", "content": "print('c')\n"},
        cwd=project_root,
        prompt_id="p-agent",
        tool_use_id="t-agent",
        agent_id=agent_id,
        agent_type="general-purpose",
    )
    assert decision(wrapper, ask) == "ask"

    # 메인 턴이 끝난다 — 승인창은 아직 열려 있다
    run_module(wrapper, "app.hooks.stop",
               {"cwd": project_root, "session_id": "sess-테스트", "prompt_id": "p-agent"})
    assert len(A.list_pending("hook-sandbox")) == 1
    assert A.read_rows(A.log_path(project_root))[-1]["result"] == "대기 중"

    # 그 에이전트가 멈출 때 닫힌다
    run_module(wrapper, "app.hooks.subagentstop",
               {"cwd": project_root, "session_id": "sess-테스트", "agent_id": agent_id})
    assert A.list_pending("hook-sandbox") == []
    assert A.read_rows(A.log_path(project_root))[-1]["result"] == A.RESULT_NO_ANSWER
