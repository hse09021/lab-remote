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
    """정책이 프로젝트 밖에 있는 덕에 잠금 ①에 자동으로 걸린다."""
    assert actions(one(ctx, "Write", {"file_path": project.path})) == ["outside"]


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
