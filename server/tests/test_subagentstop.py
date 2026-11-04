"""백그라운드 서브에이전트의 승인 대기 건은 그 에이전트가 멈출 때 닫는다.

실측(2026-11-04 02:03)으로 드러난 버그다. 서브에이전트의 PreToolUse 는 자기를
띄운 턴의 `prompt_id` 를 그대로 들고 오므로, 메인 턴의 Stop 이 응답 단위로
닫을 때 **아직 승인창이 열려 있는** 대기 건까지 끌려 닫혔다.

    02:03:12  PreToolUse  Write c.py          -> ask
    02:03:13  Stop        promptId=f7991340…  -> "거부 또는 미응답"  ← 거짓
    02:06:59  PostToolUse Write c.py          -> "허용" (늦은 승인)

그 사이 4분간 기록이 "거부" 로 보였다. 이제 Stop 은 서브에이전트 건을 건너뛰고,
`SubagentStop`·작업 알림·`SessionEnd` 가 닫는다.
"""

import json
import os

import pytest

from app import approval_log as A
from app.hooks import posttooluse, pretooluse, sessionend, stop, subagentstop, userprompt

AGENT = "a85e6d7a23abaefce"
OTHER_AGENT = "b11c0ffee0000beef"


def rows(project_root):
    return A.read_rows(A.log_path(project_root))


def events(project_root):
    path = A.event_path(project_root)
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def agent_event(hook_event, project_root, *, agent_id=AGENT, prompt_id="p1", tool_use_id="t-agent"):
    """실측 모양 그대로 — 서브에이전트는 띄운 턴의 prompt_id 를 그대로 쓴다."""
    return hook_event(
        "Write",
        {"file_path": f"{project_root}/experiments/EXP-002/c.py", "content": "print('c')\n"},
        cwd=project_root,
        prompt_id=prompt_id,
        tool_use_id=tool_use_id,
        agent_id=agent_id,
        agent_type="general-purpose",
    )


# --- 대기 건에 에이전트가 남는가 ---------------------------------------------


def test_대기_건에_agentId_가_남는다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    item = A.list_pending("hook-sandbox")[0]
    assert item["agentId"] == AGENT
    assert item["agentType"] == "general-purpose"


def test_메인_스레드_건은_agentId_가_빈다(project, project_root, hook_event):
    pretooluse.handle(hook_event("Bash", {"command": "pip install peft"}, cwd=project_root))
    assert A.list_pending("hook-sandbox")[0]["agentId"] == ""


def test_agent_type_만_오면_서브에이전트가_아니다(project, project_root, hook_event):
    """`--agent` 로 띄운 메인 세션에는 agent_type 만 온다 (번들 스키마).

    여기서 구분을 틀리면 메인 대기 건이 영원히 안 닫힌다.
    """
    event = hook_event(
        "Bash", {"command": "pip install peft"}, cwd=project_root, agent_type="code-reviewer"
    )
    pretooluse.handle(event)
    item = A.list_pending("hook-sandbox")[0]
    assert item["agentId"] == "" and item["agentType"] == "code-reviewer"
    assert A.list_pending("hook-sandbox", main_only=True)  # 메인으로 잡힌다


# --- 02:03 사건 재현 --------------------------------------------------------


def test_Stop_은_같은_응답이어도_서브에이전트_건을_안_닫는다(project, project_root, hook_event):
    """이번 버그의 핵심. promptId 가 같아도 건드리면 안 된다."""
    pretooluse.handle(agent_event(hook_event, project_root, prompt_id="p1"))
    closed = stop.handle({"cwd": project_root, "prompt_id": "p1", "session_id": "sess-테스트"})

    assert closed == []
    assert len(A.list_pending("hook-sandbox")) == 1
    assert rows(project_root)[-1]["result"] == "대기 중"  # 사실 그대로


def test_Stop_이_건너뛴_것을_기록한다(project, project_root, hook_event):
    """로그만 보고도 "왜 안 닫았는지" 가 보여야 한다."""
    pretooluse.handle(agent_event(hook_event, project_root, prompt_id="p1"))
    stop.handle({"cwd": project_root, "prompt_id": "p1", "session_id": "sess-테스트"})
    last = [e for e in events(project_root) if e.get("event") == "Stop"][-1]
    assert last["skippedAgents"] == ["t-agent"]


def test_Stop_은_같은_응답의_메인_건은_닫는다(project, project_root, hook_event):
    """메인과 서브가 섞여 있어도 각자 몫만."""
    pretooluse.handle(
        hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                   prompt_id="p1", tool_use_id="t-main")
    )
    pretooluse.handle(agent_event(hook_event, project_root, prompt_id="p1"))

    closed = stop.handle({"cwd": project_root, "prompt_id": "p1", "session_id": "sess-테스트"})
    assert [c["toolUseId"] for c in closed] == ["t-main"]
    assert [i["toolUseId"] for i in A.list_pending("hook-sandbox")] == ["t-agent"]


def test_새_프롬프트도_서브에이전트_건을_안_닫는다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    assert userprompt.handle({"cwd": project_root, "session_id": "sess-테스트",
                              "prompt": "다음 할 일"}) == []
    assert len(A.list_pending("hook-sandbox")) == 1


def test_PreToolUse_안전망도_서브에이전트_건을_안_닫는다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root, prompt_id="예전"))
    pretooluse.handle(
        hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                   prompt_id="지금", tool_use_id="t-main")
    )
    assert len(A.list_pending("hook-sandbox")) == 2


# --- SubagentStop ----------------------------------------------------------


def test_SubagentStop_이_그_에이전트_건을_닫는다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    closed = subagentstop.handle(
        {"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT}
    )
    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []
    last = rows(project_root)[-1]
    assert last["result"] == A.RESULT_NO_ANSWER and last["toolUseId"] == "t-agent"


def test_SubagentStop_은_다른_에이전트_건은_안_건드린다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root, agent_id=AGENT, tool_use_id="t-a"))
    pretooluse.handle(
        agent_event(hook_event, project_root, agent_id=OTHER_AGENT, tool_use_id="t-b")
    )
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT})
    assert [i["toolUseId"] for i in A.list_pending("hook-sandbox")] == ["t-b"]


def test_SubagentStop_은_메인_건은_안_건드린다(project, project_root, hook_event):
    pretooluse.handle(
        hook_event("Bash", {"command": "pip install peft"}, cwd=project_root, tool_use_id="t-main")
    )
    assert subagentstop.handle(
        {"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT}
    ) == []
    assert len(A.list_pending("hook-sandbox")) == 1


def test_agent_id_가_안_오면_세션의_서브에이전트_전부(project, project_root, hook_event):
    """이 이벤트의 입력은 아직 실측 전이다. 안 와도 열린 채로 두지 않는다."""
    pretooluse.handle(agent_event(hook_event, project_root, agent_id=AGENT, tool_use_id="t-a"))
    pretooluse.handle(
        agent_event(hook_event, project_root, agent_id=OTHER_AGENT, tool_use_id="t-b")
    )
    pretooluse.handle(
        hook_event("Bash", {"command": "pip install peft"}, cwd=project_root, tool_use_id="t-main")
    )

    closed = subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert sorted(c["toolUseId"] for c in closed) == ["t-a", "t-b"]
    assert [i["toolUseId"] for i in A.list_pending("hook-sandbox")] == ["t-main"]


def test_어느_경로로_닫았는지_기록한다(project, project_root, hook_event):
    """`sweep.by` 로 SubagentStop 이 agent_id 를 주는지 확정할 수 있다."""
    pretooluse.handle(agent_event(hook_event, project_root))
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT})
    assert [e for e in events(project_root) if e.get("event") == "sweep"][-1]["by"] == "SubagentStop"

    pretooluse.handle(agent_event(hook_event, project_root, tool_use_id="t2"))
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert [e for e in events(project_root) if e.get("event") == "sweep"][-1]["by"] == (
        "SubagentStop-session"
    )


def test_두_번_불러도_행이_한_줄(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT})
    before = len(rows(project_root))
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT})
    assert len(rows(project_root)) == before


def test_등록_안_된_폴더는_아무것도_안_한다(tmp_path):
    assert subagentstop.handle({"cwd": str(tmp_path), "agent_id": AGENT}) == []


def test_입력이_깨져도_조용히_끝난다(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("{ 깨진"))
    assert subagentstop.main() == 0


# --- 작업 알림 (2차 닫개) ----------------------------------------------------


def test_작업_알림이_그_에이전트_건을_닫는다(project, project_root, hook_event, real_event):
    """실측 알림을 그대로 먹인다. <task-id> 가 agent_id 와 같은 값이다."""
    pretooluse.handle(agent_event(hook_event, project_root))
    notify = real_event("020702-091764-UserPromptSubmit")
    assert userprompt.task_id_of(notify) == AGENT

    closed = userprompt.handle({**notify, "cwd": project_root, "session_id": "sess-테스트"})
    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []
    assert [e for e in events(project_root) if e.get("event") == "sweep"][-1]["by"] == (
        "taskNotification"
    )


def test_같은_알림이_두_번_와도_조용하다(project, project_root, hook_event, real_event):
    """번들 주석: "the same task-id may notify more than once"."""
    pretooluse.handle(agent_event(hook_event, project_root))
    notify = {**real_event("020702-091764-UserPromptSubmit"),
              "cwd": project_root, "session_id": "sess-테스트"}
    userprompt.handle(notify)
    before = len(rows(project_root))
    assert userprompt.handle(notify) == []
    assert len(rows(project_root)) == before


def test_알림은_다른_에이전트_건을_안_닫는다(project, project_root, hook_event, real_event):
    pretooluse.handle(agent_event(hook_event, project_root, agent_id=OTHER_AGENT, tool_use_id="t-b"))
    notify = real_event("020702-091764-UserPromptSubmit")
    assert userprompt.handle({**notify, "cwd": project_root, "session_id": "sess-테스트"}) == []
    assert len(A.list_pending("hook-sandbox")) == 1


def test_사람_프롬프트는_알림이_아니다(real_event):
    for fragment in ("020026-579275", "020112-588934", "020303-455902"):
        assert userprompt.task_id_of(real_event(f"{fragment}-UserPromptSubmit")) == ""


def test_알림이_메인_건도_같이_닫는다(project, project_root, hook_event, real_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    pretooluse.handle(
        hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                   prompt_id="예전", tool_use_id="t-main")
    )
    notify = real_event("020702-091764-UserPromptSubmit")
    closed = userprompt.handle({**notify, "cwd": project_root, "session_id": "sess-테스트"})
    assert sorted(c["toolUseId"] for c in closed) == ["t-agent", "t-main"]


# --- SessionEnd — 마지막 그물 ------------------------------------------------


def test_SessionEnd_는_서브에이전트_건도_닫는다(project, project_root, hook_event):
    pretooluse.handle(agent_event(hook_event, project_root))
    closed = sessionend.handle(
        {"cwd": project_root, "session_id": "sess-테스트", "prompt_id": "p1", "reason": "other"}
    )
    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []


# --- 늦은 승인은 그대로 동작해야 한다 ----------------------------------------


def test_SubagentStop_뒤_늦은_승인도_허용으로_붙는다(project, project_root, hook_event):
    """닫개가 셋이어도 늦은 PostToolUse 그물은 남아 있어야 한다."""
    event = agent_event(hook_event, project_root)
    pretooluse.handle(event)
    subagentstop.handle({"cwd": project_root, "session_id": "sess-테스트", "agent_id": AGENT})
    assert posttooluse.handle(event) is not None

    raw = [r for r in rows(project_root) if r["toolUseId"] == "t-agent"]
    assert [r["result"] for r in raw] == ["대기 중", A.RESULT_NO_ANSWER, "허용"]
    grouped = A.group_rows(rows(project_root))
    assert [r for r in grouped if r["toolUseId"] == "t-agent"][0]["result"] == "허용"


# --- 헤드리스 승인 요청에도 에이전트가 남는가 --------------------------------


def test_헤드리스_요청에도_에이전트가_남는다(project, project_root, hook_event, monkeypatch):
    monkeypatch.setenv(pretooluse.HEADLESS_ENV, "1")
    monkeypatch.setenv("LAB_NOTIFY_DISABLED", "1")
    pretooluse.handle(agent_event(hook_event, project_root))
    request = A.list_requests("hook-sandbox")[0]
    assert request["agentId"] == AGENT


# --- 실측 픽스처 (2026-11-04 09:27~09:33) ------------------------------------
# 1회차(거부) 09:27:37 d.py 대기 -> 09:27:38 Stop 건너뜀 -> 09:30:51 SubagentStop 닫음
# 2회차(승인) 09:33:12 e.py 대기 -> 09:33:41 PostToolUse "허용"
# 두 회차 모두에서 SubagentStop 이 한 턴에 두 번 왔다. 아래 시험이 그 모양을 고정한다.

FIX_SUBAGENT_REAL = "20261104-093051-360919-SubagentStop"
FIX_SUBAGENT_EMPTY = "20261104-093058-395017-SubagentStop"
FIX_TASK_NOTIFY = "20261104-093051-420967-UserPromptSubmit"


def test_실측_SubagentStop_에_agent_id_가_온다(real_event):
    """설계가 이 필드 하나에 걸려 있다. 안 오면 세션 전체 쓸기로 떨어진다."""
    event = real_event(FIX_SUBAGENT_REAL)
    assert event["hook_event_name"] == "SubagentStop"
    assert event["agent_id"] == "af3199313de4e46ff"
    assert event["agent_type"] == "general-purpose"
    # 메인 스레드 Stop 과 구분되는 필드
    assert "agent_transcript_path" in event
    assert event["stop_hook_active"] is False


def test_실측_SubagentStop_은_자기를_실행_중으로_들고_온다(real_event):
    """SubagentStop 시점에도 background_tasks 의 status 는 아직 running 이다.
    그래서 "작업이 끝났나" 를 background_tasks 로 판단하면 안 된다."""
    event = real_event(FIX_SUBAGENT_REAL)
    tasks = event["background_tasks"]
    assert [t["id"] for t in tasks] == [event["agent_id"]]
    assert tasks[0]["status"] == "running"


def test_실측_한_턴에_SubagentStop_이_두_번_오고_agent_id_가_다르다(real_event):
    """같은 이벤트가 두 번 온 게 아니라 **다른 에이전트**가 둘 멈춘 것이다.

    둘째는 agent_type 이 빈 문자열이고, PreToolUse 를 한 번도 낸 적이 없는
    agent_id 다. prompt_id 로 묶었다면 둘째가 첫째의 대기 건을 가로채
    거짓 "거부" 를 남겼을 것이다. agent_id 로 묶는 이유가 이것이다.
    """
    first = real_event(FIX_SUBAGENT_REAL)
    second = real_event(FIX_SUBAGENT_EMPTY)

    assert first["agent_id"] != second["agent_id"]
    assert first["prompt_id"] != second["prompt_id"]
    assert second["agent_type"] == ""
    assert second["background_tasks"] == []


def test_실측_작업_알림의_task_id_가_에이전트_것과_같다(real_event):
    """3차 닫개(작업 알림)가 같은 건을 가리키는지. 둘째 SubagentStop 과
    prompt_id 를 공유한다 — 알림이 새 프롬프트를 만들고 그 턴이 끝난 것이다."""
    notify = real_event(FIX_TASK_NOTIFY)
    agent = real_event(FIX_SUBAGENT_REAL)
    second = real_event(FIX_SUBAGENT_EMPTY)

    assert f"<task-id>{agent['agent_id']}</task-id>" in notify["prompt"]
    assert notify["prompt_id"] == second["prompt_id"]


def test_실측_빈_agent_type_쪽은_아무것도_안_닫는다(project, project_root, hook_event, real_event):
    """2회차 09:33:15 에 같은 모양이 **승인 26초 전에** 왔다. 이게 대기 건을
    닫았다면 기록이 거짓 "거부 또는 미응답" 이 됐을 것이다."""
    pretooluse.handle(agent_event(hook_event, project_root))
    assert len(A.list_pending("hook-sandbox")) == 1

    stray = dict(real_event(FIX_SUBAGENT_EMPTY))
    stray["cwd"] = project_root
    stray["session_id"] = "sess-테스트"
    assert subagentstop.handle(stray) == []

    assert len(A.list_pending("hook-sandbox")) == 1  # 그대로 열려 있다
    assert not [row for row in rows(project_root) if row["result"] == "거부 또는 미응답"]


def test_실측_모양_그대로_주면_그_건이_닫힌다(project, project_root, hook_event, real_event):
    """1회차 09:30:51 — 실제로 닫은 쪽."""
    pretooluse.handle(agent_event(hook_event, project_root, agent_id="af3199313de4e46ff"))

    event = dict(real_event(FIX_SUBAGENT_REAL))
    event["cwd"] = project_root
    event["session_id"] = "sess-테스트"
    closed = subagentstop.handle(event)

    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []
    assert rows(project_root)[-1]["result"] == "거부 또는 미응답"
    sweeps = [e for e in events(project_root) if e.get("event") == "sweep"]
    assert sweeps[-1]["by"] == "SubagentStop"
