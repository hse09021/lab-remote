"""📋 2.1.318 의 **실제 도구 목록**과 우리 분류를 맞춘다.

## 왜 이 파일이 있나

`labremote claude hook-sandbox` 에서 "Glob 으로 `~/.ssh/*` 찾아 줘" 를 시켰더니
**`Glob` 도구가 세션에 아예 없어서** 호출조차 못 했습니다(2.1.318).

그런데 `tests/test_credentials.py` 는 "Glob 으로 훑는 것도 막힌다" 고
단정하고 있었습니다. 판정은 맞지만 **없는 도구로는 시도할 수 없으니** 그건
오늘의 보호가 아닙니다. S5 의 matcher 거짓 초록불과 **같은 종류의 거짓**입니다.

실측(2026-11-05): 세션에 도구 목록을 직접 물어봤습니다.

    직접 Agent Artifact Bash Edit ListAgents Read ReportFindings
         ScheduleWakeup SendFeedback Skill ToolSearch Workflow Write
    지연 ArtifactComments ArtifactData Cron{Create,Delete,List} DesignSync
         Monitor NotebookEdit PushNotification RemoteTrigger SendMessage
         TaskStop WebFetch WebSearch

    없음 Glob Grep TodoWrite MultiEdit NotebookRead LS Task
"""

import pytest

from app.agent import launch as L
from app.hooks import classify as C
from app.hooks import decide as D


def _resolve(ctx, tool, tool_input=None):
    found = C.classify_event({"tool_name": tool, "tool_input": tool_input or {}}, ctx)
    return [f.action for f in found], D.resolve(found, ctx)


# --- 없는 도구를 근거로 "막힌다" 고 하지 않는다 ------------------------------


def test_없는_도구_목록이_실측과_맞다():
    assert C.PHANTOM_TOOLS == {
        "Glob", "Grep", "TodoWrite", "MultiEdit", "NotebookRead", "LS", "Task"
    }
    # 겹치면 둘 중 하나가 틀렸다
    assert not (C.PHANTOM_TOOLS & C.TOOLS_2_1_318)


def test_없는_도구도_분류에서_빼지_않는다():
    """다른 판·다른 모델이 쓸 수 있다. 빠져 있으면 그게 구멍이다.

    빼지 않는 것과 "오늘 막고 있다" 고 말하는 것은 다르다 — 문구만 고친다.
    """
    for tool in ("Glob", "Grep"):
        assert tool in C.SECRET_READ_TOOLS, tool
        assert tool in C.READ_ONLY_TOOLS, tool
    assert "MultiEdit" in C.WRITE_TOOLS


def test_Task_는_끄는_목록에_없다():
    """🔑 `--disallowedTools Task` 는 **아무것도 끄지 않았다.**

    2.1.318 의 서브에이전트 도구 이름은 `Agent` 다. 없는 이름을 끄는 척하면
    "서브에이전트는 꺼 뒀다" 는 말이 거짓이 된다.
    """
    assert "Task" not in L.DISALLOWED_TOOLS
    assert "Agent" in L.DISALLOWED_TOOLS


# --- 🔑 실제 도구가 **하나도 빠짐없이** 다뤄지나 -----------------------------


def test_모든_실제_도구가_끄거나_판정된다(ctx):
    """두 겹이다 — 런처가 끄거나(`DISALLOWED_TOOLS`), 훅이 판정한다.

    새 판에서 도구가 늘면 이 시험이 **먼저** 깨진다.
    """
    ctx.headless = True
    uncovered = []
    for tool in sorted(C.TOOLS_2_1_318):
        if tool in L.DISALLOWED_TOOLS:
            continue
        actions, decision = _resolve(ctx, tool)
        # 판정이 나와야 한다. `allow` 는 읽기 전용에만 허용한다.
        if decision.kind == "allow" and tool not in C.READ_ONLY_TOOLS:
            uncovered.append((tool, actions, decision.kind))
    assert uncovered == [], uncovered


def test_모르는_도구는_헤드리스에서_막힌다(ctx):
    """fail-closed. 새로 생긴 도구는 **거절**로 떨어져 사람이 본다."""
    ctx.headless = True
    for tool in ("Agent", "Workflow", "Artifact", "CronCreate", "Monitor",
                 "ListAgents", "SendMessage", "mcp__x__y", "아주새로운도구"):
        actions, decision = _resolve(ctx, tool)
        assert actions == ["unclassified"], (tool, actions)
        assert decision.kind == "deny", (tool, decision.kind)


def test_읽기_전용_도구는_헤드리스에서_통과한다(ctx):
    """헤드리스에서 `defer` 는 **정지**다 — 통과시켜야 루프가 돈다."""
    ctx.headless = True
    for tool in ("ToolSearch", "Skill", "ReportFindings"):
        actions, decision = _resolve(ctx, tool)
        assert actions == ["toolAllowed"], (tool, actions)
        assert decision.kind == "allow", (tool, decision.kind)


def test_NotebookEdit_는_파일_쓰기로_본다(ctx, project_root):
    """2.1.318 에 **있는** 편집 도구다. `MultiEdit` 는 없다."""
    import os

    ctx.headless = True
    actions, _ = _resolve(
        ctx, "NotebookEdit",
        {"notebook_path": os.path.join(project_root, "src", "a.ipynb")},
    )
    assert actions == ["code"], actions
    # 프로젝트 밖은 막힌다
    actions, decision = _resolve(
        ctx, "NotebookEdit", {"notebook_path": "/home/hse09021/밖.ipynb"}
    )
    assert "outside" in actions and decision.kind == "deny"


# --- 끄는 목록이 실제 이름인가 ------------------------------------------------


def test_끄는_도구가_전부_실제로_있는_이름이다():
    """없는 이름을 끄면 "껐다" 는 기록이 거짓이 된다."""
    for tool in L.DISALLOWED_TOOLS:
        assert tool in C.TOOLS_2_1_318, tool


def test_끄는_목록이_판정_가능한_도구를_안_끈다():
    """훅이 판정하는 도구를 끄면 일을 못 한다."""
    keep = {"Bash", "Read", "Write", "Edit", "NotebookEdit", "WebFetch",
            "WebSearch", "ToolSearch", "Skill", "ReportFindings"}
    assert not (set(L.DISALLOWED_TOOLS) & keep)
