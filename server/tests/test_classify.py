"""도구 호출 -> 행동 유형 분류 시험.

필드명은 실측값이다 — `tests/fixtures/hook_events/` 의 덤프가 근거다.
"""

import os

import pytest

from app.hooks import classify
from app.hooks.classify import Finding


def actions(findings):
    return sorted(f.action for f in findings)


def one(ctx, tool, tool_input):
    return classify.classify_event({"tool_name": tool, "tool_input": tool_input}, ctx)


# --- 실측 픽스처로 ----------------------------------------------------------


def test_실측_Edit_이벤트의_키(real_event):
    event = real_event("232035-028911-PreToolUse-Edit")
    assert set(event["tool_input"]) == {"file_path", "old_string", "new_string", "replace_all"}
    assert classify.target_paths("Edit", event["tool_input"]) == [
        "/home/사용자/projects/dump-scratch/experiments/EXP-001/config.yaml"
    ]


def test_실측_Write_이벤트의_키(real_event):
    event = real_event("232104-774768-PreToolUse-Write")
    assert set(event["tool_input"]) == {"file_path", "content"}
    assert classify.target_paths("Write", event["tool_input"])


def test_실측_최상위_필드(real_event):
    event = real_event("232021-833394-PreToolUse-Edit")
    for key in ("session_id", "cwd", "prompt_id", "permission_mode", "tool_use_id"):
        assert key in event, key


def test_실측_Stop_에_prompt_id_가_온다(real_event):
    """대기 건을 응답 단위로 마감하는 근거."""
    event = real_event("232025-072280-Stop")
    assert event["prompt_id"]
    assert event["session_id"]
    assert event["stop_hook_active"] is False


def test_실측_SessionEnd_모양(real_event):
    event = real_event("232025-095527-SessionEnd")
    assert event["hook_event_name"] == "SessionEnd"
    assert "reason" in event
    assert "permission_mode" not in event  # 실측: 안 온다


# --- 필드명 호환 ------------------------------------------------------------


def test_구버전_키_이름도_같은_결정(ctx, project_root):
    """old_str/new_str 변형이 와도 결정이 같아야 한다."""
    new = one(ctx, "Edit", {"file_path": f"{project_root}/src/train.py", "old_string": "a", "new_string": "b"})
    old = one(ctx, "Edit", {"file_path": f"{project_root}/src/train.py", "old_str": "a", "new_str": "b"})
    assert actions(new) == actions(old) == ["code"]


def test_경로_키가_전혀_없으면_차단(ctx):
    found = one(ctx, "Write", {"이상한키": 1, "another": 2})
    assert actions(found) == ["schema-unknown"]
    assert "이상한키" in found[0].detail  # 받은 키를 로그에 남긴다


def test_MultiEdit_은_관찰_안_됐지만_분류는_남아_있다(ctx, project_root):
    """2.1.317 에서 한 번도 안 나왔다. 그래도 빼면 그게 구멍이 된다."""
    assert "MultiEdit" in classify.MULTI_EDIT_TOOLS
    found = one(
        ctx,
        "MultiEdit",
        {"edits": [{"file_path": f"{project_root}/src/a.py"}, {"file_path": "/etc/hosts"}]},
    )
    assert "outside" in actions(found)


def test_MultiEdit_상위_공통_경로_변형(ctx, project_root):
    found = one(ctx, "MultiEdit", {"file_path": f"{project_root}/src/a.py", "edits": [{"old_string": "x"}]})
    assert actions(found) == ["code"]


# --- 경로 분류 --------------------------------------------------------------


@pytest.mark.parametrize(
    "rel, expected",
    [
        ("src/train.py", ["code"]),
        ("experiments/EXP-007/train.py", ["code"]),
        ("experiments/EXP-007/config.yaml", ["hparam"]),
        ("specifications/Config.yaml", ["stop"]),
        ("docs/Evaluation.md", ["stop"]),
        ("docs/Stop_and_recovery.md", ["code"]),  # 사람이 읽는 설명 — 잠금 아님
        ("logs/Experiment_log.csv", ["journal"]),
        ("logs/Decision_log.md", ["journal"]),
        ("state/State.yaml", ["journal"]),
        ("README.md", ["journal"]),
        ("logs/Approval_log.csv", ["selfProtect"]),
        ("logs/hook_events.jsonl", ["selfProtect"]),
        (".claude/settings.json", ["selfProtect"]),
        (".mcp.json", ["selfProtect"]),
    ],
)
def test_경로별_분류(ctx, project_root, rel, expected):
    found = one(ctx, "Write", {"file_path": f"{project_root}/{rel}"})
    assert actions(found) == expected


def test_프로젝트_밖(ctx):
    assert actions(one(ctx, "Write", {"file_path": "/etc/hosts"})) == ["outside"]


def test_정책_파일_자신도_밖(ctx, project):
    """정책은 프로젝트 밖(잠금 ①)이면서 보호 목록이기도 하다.

    보호 목록이 먼저 걸린다 — `extraWritableRoots` 로 프로젝트 밖 판정을
    열어도 정책 파일은 열리지 않아야 하기 때문이다.
    """
    assert actions(one(ctx, "Write", {"file_path": project.path})) == ["hardProtect"]


def finish(project_root, exp):
    """결과가 나온 실험 폴더로 만든다 (prev 판정의 표식)."""
    import os

    folder = os.path.join(project_root, "experiments", exp)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "result.csv"), "w").close()
    return folder


def test_이전_실험_폴더(ctx, project_root):
    ctx.run.experiment_id = "EXP-007"
    ctx.run.running = True
    finish(project_root, "EXP-006")
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-006/config.yaml"})
    assert actions(found) == ["hparam", "prev"]
    assert [f.exp for f in found if f.action == "prev"] == ["EXP-006"]


def test_지금_도는_실험은_이전이_아니다(ctx, project_root):
    ctx.run.experiment_id = "EXP-007"
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-007/config.yaml"})
    assert actions(found) == ["hparam"]


def test_결과가_없는_실험_폴더는_이전이_아니다(ctx, project_root):
    """실행 중인 실험이 없어도 다음 실험을 준비할 수 있어야 한다."""
    assert not ctx.run.running and ctx.run.experiment_id is None
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-008/config.yaml"})
    assert actions(found) == ["hparam"]  # prev 아님


def test_시작했다가_결과_없이_죽은_실험도_이전이다(ctx, project_root):
    """사양상 실패한 실험 폴더는 남기고 새 폴더에서 재실행해야 한다.
    결과 파일이 없다고 덮어쓸 수 있으면 그 규칙이 무너진다."""
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-005")
    runstate.set_idle("hook-sandbox")  # 결과 없이 끝남
    ctx.run = runstate.load("hook-sandbox")

    folder = os.path.join(project_root, "experiments", "EXP-005")
    os.makedirs(folder, exist_ok=True)
    assert not os.path.exists(os.path.join(folder, "result.csv"))  # 표식 없음

    found = one(ctx, "Write", {"file_path": f"{folder}/config.yaml"})
    assert "prev" in actions(found)


def test_started_는_set_idle_로_지워지지_않는다(ctx, project_root):
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-005")
    runstate.set_running("hook-sandbox", "EXP-006")
    runstate.set_idle("hook-sandbox")
    assert runstate.load("hook-sandbox").started == ["EXP-005", "EXP-006"]


def test_지금_도는_실험은_started_에_있어도_이전이_아니다(ctx, project_root):
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-007")
    ctx.run = runstate.load("hook-sandbox")
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-007/config.yaml"})
    assert "prev" not in actions(found)


def test_결과가_나오면_이전이_된다(ctx, project_root):
    """보조 근거 — runstate 가 생기기 전에 만들어진 폴더를 건진다."""
    assert ctx.run.started == [] or ctx.run.started is None
    finish(project_root, "EXP-008")
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-008/config.yaml"})
    assert "prev" in actions(found)


def test_실험_폴더_분석_노트(ctx, project_root):
    finish(project_root, "EXP-006")
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-006/analysis.md"})
    assert actions(found) == ["journal", "prev"]


def test_extraWritableRoots_예외(ctx, project_root, tmp_path):
    outside = tmp_path / "datasets"
    outside.mkdir()
    ctx.policy.data["paths"]["extraWritableRoots"] = [str(outside)]
    found = one(ctx, "Write", {"file_path": str(outside / "train.csv")})
    assert actions(found) == ["code"]
    assert "extraWritableRoots" in found[0].detail


# --- 그 밖의 도구 -----------------------------------------------------------


def test_WebFetch_는_net(ctx, real_event):
    event = real_event("232136-958710-PreToolUse-WebFetch")
    found = classify.classify_event(event, ctx)
    assert actions(found) == ["net"]
    assert found[0].target == "https://example.com"


def test_읽기_전용_도구는_판정하지_않는다(ctx, real_event):
    """ToolSearch 는 도구 스키마만 불러온다. matcher 에도 넣지 않는다."""
    for fragment in ("PreToolUse-ToolSearch", "232018-048377-PreToolUse-Read"):
        assert classify.classify_event(real_event(fragment), ctx) == []
    assert "ToolSearch" in classify.READ_ONLY_TOOLS


def test_모르는_도구는_판정하지_않는다(ctx):
    assert classify.classify_event({"tool_name": "처음보는도구", "tool_input": {}}, ctx) == []


def test_Bash_에_command_가_없으면_차단(ctx):
    found = one(ctx, "Bash", {"description": "설명만 있음"})
    assert actions(found) == ["schema-unknown"]


# --- 보호 목록 (판 2) --------------------------------------------------------
# 정책으로 못 여는 목록. `extraWritableRoots` **보다 앞에서** 판정한다.


def test_서버_코드도_보호_목록(ctx):
    from app import policy_defaults as D

    server_dir = D.hard_protected_roots()[0]
    found = one(ctx, "Edit", {"file_path": f"{server_dir}/app/hooks/decide.py",
                              "old_string": "a", "new_string": "b"})
    assert actions(found) == ["hardProtect"]


@pytest.mark.parametrize(
    "rel",
    [
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/hooks/x.sh",
        ".credentials.json",  # ~/.claude/ 아래
    ],
)
def test_사용자_claude_폴더는_항상_차단(ctx, rel):
    found = one(ctx, "Write", {"file_path": os.path.expanduser(f"~/.claude/{rel}")})
    assert actions(found) == ["hardProtect"]


@pytest.mark.parametrize("name", ["~/.claude.json", "~/.claude.json.backup"])
def test_MCP_설정도_항상_차단(ctx, name):
    """쓰기 가능한 MCP 를 붙이면 훅 게이트를 그냥 지나간다."""
    assert actions(one(ctx, "Write", {"file_path": os.path.expanduser(name)})) == ["hardProtect"]


def test_보호_목록은_extraWritableRoots_보다_앞(ctx, project):
    """저장소 전체를 예외로 열어도 훅 코드와 정책은 열리지 않아야 한다."""
    from app import policy_defaults as D

    server_dir = D.hard_protected_roots()[0]
    ctx.policy.data["paths"]["extraWritableRoots"] = [os.path.dirname(server_dir)]
    found = one(ctx, "Write", {"file_path": f"{server_dir}/app/policy.py"})
    assert actions(found) == ["hardProtect"]


def test_런타임_폴더를_옮겨도_따라간다(ctx, monkeypatch, tmp_path):
    moved = tmp_path / "다른-런타임"
    moved.mkdir()
    monkeypatch.setenv("LAB_DATA_DIR", str(moved))
    found = one(ctx, "Write", {"file_path": str(moved / "policies" / "x.json")})
    assert actions(found) == ["hardProtect"]


# --- 비밀 파일 --------------------------------------------------------------


def test_Read_는_비밀_파일만_본다(ctx, project_root):
    """읽기를 전면 차단하면 소음만 커진다. 비밀 파일만 막는다."""
    open(os.path.join(project_root, ".env"), "w").close()
    assert actions(one(ctx, "Read", {"file_path": f"{project_root}/.env"})) == ["secret"]
    assert one(ctx, "Read", {"file_path": f"{project_root}/src/train.py"}) == []
    assert one(ctx, "Read", {"file_path": "/etc/hosts"}) == []


def test_Grep_의_대상이_비밀_파일이면_차단(ctx, project_root):
    assert actions(one(ctx, "Grep", {"pattern": "KEY", "path": f"{project_root}/.env"})) == [
        "secret"
    ]
    # 폴더를 훑는 재귀 읽기는 못 막는다 (문서화된 한계)
    assert one(ctx, "Grep", {"pattern": "KEY", "path": project_root}) == []


def test_비밀_파일_쓰기도_차단(ctx, project_root):
    assert actions(one(ctx, "Write", {"file_path": f"{project_root}/.env"})) == ["secret"]


def test_예시_파일은_비밀이_아니다(ctx, project_root):
    for rel in (".env.example", ".env.sample", ".env.template"):
        assert one(ctx, "Read", {"file_path": f"{project_root}/{rel}"}) == []


def test_프로젝트_밖_비밀도_차단(ctx):
    assert actions(one(ctx, "Read", {"file_path": os.path.expanduser("~/.config/labremote/x.env")})) == [
        "secret"
    ]


# --- 산출물 보존 (실측 8번: 도는 실험 output 이 ask -> 승인으로 지워졌다) -----


def running(ctx, exp="EXP-007"):
    ctx.run.running = True
    ctx.run.experiment_id = exp
    ctx.run.started = [exp]
    return exp


def output_file(project_root, exp="EXP-007", rel="output/train.log"):
    path = os.path.join(project_root, "experiments", exp, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("원본 출력\n")
    return path


def bash(ctx, command):
    return classify.classify_event({"tool_name": "Bash", "tool_input": {"command": command}}, ctx)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf experiments/EXP-007/output",
        "rm experiments/EXP-007/output/train.log",
        "mv experiments/EXP-007/output/train.log /tmp/keep.log",
        ": > experiments/EXP-007/output/train.log",
        "echo '' > experiments/EXP-007/output/train.log",
        "truncate -s 0 experiments/EXP-007/output/train.log",
        "cp src/train.py experiments/EXP-007/output/train.log",
        "tee experiments/EXP-007/output/train.log",
        "dd if=/dev/zero of=experiments/EXP-007/output/train.log",
        "sed -i 's/a/b/' experiments/EXP-007/output/train.log",
    ],
)
def test_도는_실험_산출물은_파괴적_조작_전부_차단(ctx, project_root, command):
    running(ctx)
    output_file(project_root)
    assert "outputProtect" in actions(bash(ctx, command))


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_쓰기_도구로_산출물_덮어쓰기도_차단(ctx, project_root, tool):
    running(ctx)
    path = output_file(project_root)
    found = one(ctx, tool, {"file_path": path, "old_string": "a", "new_string": "b"})
    assert "outputProtect" in actions(found)


def test_산출물에_덧붙이기는_차단하지_않는다(ctx, project_root):
    """`>>` 는 원본을 날리지 않는다. 실험 자신이 로그를 쌓는 모양이다."""
    running(ctx)
    output_file(project_root)
    assert "outputProtect" not in actions(bash(ctx, "echo x >> experiments/EXP-007/output/train.log"))


def test_새_산출물_만들기는_차단하지_않는다(ctx, project_root):
    running(ctx)
    output_file(project_root)
    found = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-007/output/new.log"})
    assert "outputProtect" not in actions(found)


def test_result_csv_는_수정은_되고_삭제는_안_된다(ctx, project_root):
    """루프가 돌면서 result.csv 를 다시 쓰는 건 정상(기록)이다."""
    running(ctx)
    output_file(project_root, rel="result.csv")
    write = one(ctx, "Write", {"file_path": f"{project_root}/experiments/EXP-007/result.csv"})
    assert actions(write) == ["journal"]
    assert "outputProtect" in actions(bash(ctx, "rm experiments/EXP-007/result.csv"))


def test_안_돌린_실험_폴더는_지울_수_있다(ctx, project_root):
    """준비 중인 폴더를 못 지우면 일이 안 된다."""
    running(ctx, "EXP-007")
    output_file(project_root, exp="EXP-009", rel="output/x.log")
    found = bash(ctx, "rm -rf experiments/EXP-009/output")
    assert "outputProtect" not in actions(found)
    assert "del" in actions(found)


def test_끝난_실험_산출물도_보존(ctx, project_root):
    ctx.run.started = ["EXP-005"]
    output_file(project_root, exp="EXP-005")
    assert "outputProtect" in actions(bash(ctx, "rm -rf experiments/EXP-005/output"))


def test_checkpoints_도_산출물(ctx, project_root):
    running(ctx)
    output_file(project_root, rel="checkpoints/last.ckpt")
    assert "outputProtect" in actions(bash(ctx, "rm experiments/EXP-007/checkpoints/last.ckpt"))


# --- 서브에이전트 구분 (실측 픽스처) -----------------------------------------
# 2026-11-04 02:03 사건의 근거. 대기 건 마감을 이 값으로 가른다.


def test_실측_서브에이전트_PreToolUse_에_agent_id_가_있다(real_event):
    event = real_event("020312-209511-PreToolUse-Write")
    assert event["agent_id"] == "a85e6d7a23abaefce"
    assert event["agent_type"] == "general-purpose"
    # 자기를 띄운 턴의 prompt_id 를 그대로 쓴다 — 그래서 Stop 에 끌려 닫혔다
    assert event["prompt_id"] == real_event("020303-455902-UserPromptSubmit")["prompt_id"]


def test_실측_메인_스레드에는_agent_id_가_없다(real_event):
    event = real_event("020029-843779-PreToolUse-Bash")
    assert "agent_id" not in event
    assert "agent_type" not in event


def test_실측_UserPromptSubmit_최상위_필드(real_event):
    """첫 실측(2026-11-04). tool_* 은 안 온다."""
    event = real_event("020026-579275-UserPromptSubmit")
    assert set(event) == {
        "session_id", "transcript_path", "cwd", "scratchpad_dir",
        "prompt_id", "permission_mode", "hook_event_name", "prompt",
    }


def test_실측_작업_알림도_UserPromptSubmit_으로_온다(real_event):
    event = real_event("020702-091764-UserPromptSubmit")
    assert event["hook_event_name"] == "UserPromptSubmit"
    assert "<task-notification>" in event["prompt"]
    assert "<task-id>a85e6d7a23abaefce</task-id>" in event["prompt"]


def test_서브에이전트_호출도_똑같이_판정한다(ctx, project_root, real_event):
    """구분은 마감에만 쓴다. 판정은 메인과 같아야 한다."""
    event = real_event("020312-209511-PreToolUse-Write")
    moved = {**event, "tool_input": {
        "file_path": f"{project_root}/experiments/EXP-002/c.py", "content": "print('c')\n"}}
    assert actions(classify.classify_event(moved, ctx)) == ["code"]
