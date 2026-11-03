"""승인 기록과 대기 건 마감 시험.

실측(2.1.317): **거절된 호출은 PostToolUse 가 안 온다.** 그래서 Stop 이
마감하지 않으면 대기 뱃지가 영원히 켜져 있게 된다.
"""

import csv
import json
import multiprocessing
import os

import pytest

from app import approval_log as A
from app.hooks import posttooluse, pretooluse, sessionend, stop


def rows(project_root):
    with open(A.log_path(project_root), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def events(project_root):
    path = A.event_path(project_root)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --- CSV 모양 ---------------------------------------------------------------


def test_열이_웹_UI_와_같다(project_root):
    from tests.conftest import REPO_ROOT

    types = (REPO_ROOT / "web" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    block = types.split("interface ApprovalLogEntry")[1].split("}")[0]
    for column in A.COLUMNS:
        assert column in block, column


def test_한_레코드는_한_물리행(project_root):
    path = A.log_path(project_root)
    tricky = '쉼표, "따옴표" 그리고\n줄바꿈'
    A.append_row(path, action="코드 수정", request=tricky, result="차단")
    assert len(open(path, encoding="utf-8").read().splitlines()) == 2  # 헤더 + 1
    assert rows(project_root)[0]["request"] == '쉼표, "따옴표" 그리고⏎줄바꿈'


def test_긴_요청은_잘린다(project_root):
    A.append_row(A.log_path(project_root), action="a", request="가" * 500, result="차단")
    assert len(rows(project_root)[0]["request"]) <= A.MAX_REQUEST


def _writer(args):
    path, i = args
    A.append_row(path, action=f"a{i}", request=f"r{i}", result="허용")


def test_동시에_써도_안_깨진다(project_root):
    path = A.log_path(project_root)
    A.ensure_log(path)
    with multiprocessing.Pool(5) as pool:
        pool.map(_writer, [(path, i) for i in range(20)])
    got = rows(project_root)
    assert len(got) == 20
    assert all(set(row) == set(A.COLUMNS) for row in got)


# --- 대기 건 마감 -----------------------------------------------------------


def run_pre(event):
    return pretooluse.handle(event)


def test_ask_는_대기_건을_연다(project, project_root, hook_event):
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    assert run_pre(event).kind == "ask"

    pending = A.list_pending("hook-sandbox")
    assert len(pending) == 1
    assert pending[0]["promptId"] == "prompt-테스트"
    assert pending[0]["action"] == "패키지 설치"

    row = rows(project_root)[-1]
    assert row["result"] == "대기 중" and row["resultPending"] == "true"
    assert row["action"] == "패키지 설치"


def test_PostToolUse_가_허용으로_마감(project, project_root, hook_event):
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    run_pre(event)
    posttooluse.handle({**event, "hook_event_name": "PostToolUse"})

    assert A.list_pending("hook-sandbox") == []
    assert rows(project_root)[-1]["result"] == "허용"


def test_Stop_이_안_돌아간_대기_건을_마감(project, project_root, hook_event):
    """실측: 거절된 호출은 PostToolUse 가 안 온다."""
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    run_pre(event)
    closed = stop.handle({"cwd": project_root, "prompt_id": "prompt-테스트", "session_id": "sess-테스트"})

    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []
    assert rows(project_root)[-1]["result"] == stop.RESULT


def two_pendings():
    """서로 다른 응답에서 열린 대기 건 두 개.

    `run_pre` 를 두 번 부르지 않는 이유: PreToolUse 안전망이 새 응답을 보면
    이전 응답 대기 건을 닫아 버린다(그게 B 버그 수정이다). Stop 의 응답 단위
    묶기만 보려면 상태를 직접 만들어야 한다.
    """
    for prompt_id, tool_use_id in (("p1", "t1"), ("p2", "t2")):
        A.open_pending(
            "hook-sandbox",
            tool_use_id,
            {
                "promptId": prompt_id,
                "sessionId": "sess-테스트",
                "tool": "Bash",
                "action": "패키지 설치",
                "request": f"pip install {tool_use_id}",
            },
        )


def test_Stop_은_그_응답의_대기_건만_건드린다(project, project_root):
    """prompt_id 로 묶는다. 세션으로 묶으면 다른 응답 것까지 끌려 닫힌다."""
    two_pendings()
    assert len(A.list_pending("hook-sandbox")) == 2

    stop.handle({"cwd": project_root, "prompt_id": "p1", "session_id": "sess-테스트"})
    left = A.list_pending("hook-sandbox")
    assert [item["promptId"] for item in left] == ["p2"]


def test_prompt_id_가_없으면_session_id_로(project, project_root, hook_event):
    """prompt_id 를 안 주는 버전 대비."""
    event = hook_event("Bash", {"command": "pip install a"}, cwd=project_root)
    del event["prompt_id"]
    run_pre(event)
    closed = stop.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert len(closed) == 1


def test_PostToolUse_가_닫은_건은_Stop_이_두_번_기록_안_한다(project, project_root, hook_event):
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    run_pre(event)
    posttooluse.handle(event)
    before = len(rows(project_root))
    assert stop.handle({"cwd": project_root, "prompt_id": "prompt-테스트"}) == []
    assert len(rows(project_root)) == before


def test_SessionEnd_가_잔여분을_정리(project, project_root):
    """Stop 이 못 돈 경우(크래시·강제 종료)."""
    two_pendings()
    closed = sessionend.handle(
        {"cwd": project_root, "session_id": "sess-테스트", "prompt_id": "p2", "reason": "other"}
    )
    assert len(closed) == 2  # 응답 단위가 아니라 세션 전체
    assert A.list_pending("hook-sandbox") == []


def test_등록_안_된_폴더는_아무것도_안_한다(tmp_path):
    assert posttooluse.handle({"cwd": str(tmp_path)}) is None
    assert stop.handle({"cwd": str(tmp_path)}) == []


# --- 우회 추적 --------------------------------------------------------------


def test_거절_뒤_다른_도구로_오면_우회_시도로_남는다(project, project_root, hook_event):
    """실측 그대로: Edit 거절 -> Bash sed -> Write."""
    target = f"{project_root}/docs/Evaluation.md"
    assert run_pre(hook_event("Edit", {"file_path": target, "old_string": "a", "new_string": "b"}, cwd=project_root)).kind == "ask"

    # 같은 파일을 sed 로
    run_pre(hook_event("Bash", {"command": "sed -i 's/a/b/' docs/Evaluation.md"}, cwd=project_root))
    marks = [e for e in events(project_root) if e.get("bypassAttempt")]
    assert marks, "우회 시도가 기록되지 않았어요"
    assert marks[-1]["bypassAttempt"] == {
        "rel": "docs/Evaluation.md",
        "before": "Edit",
        "now": "Bash",
    }
    assert any(row["action"] == "우회 시도" for row in rows(project_root))


def test_같은_도구로_다시_오면_우회가_아니다(project, project_root, hook_event):
    target = f"{project_root}/docs/Evaluation.md"
    event = hook_event("Edit", {"file_path": target, "old_string": "a", "new_string": "b"}, cwd=project_root)
    run_pre(event)
    run_pre(event)
    assert not [e for e in events(project_root) if e.get("bypassAttempt")]


# --- 로그 내용 --------------------------------------------------------------


def test_잠긴_항목은_Hooks_가_처리한_것으로(project, project_root, hook_event):
    run_pre(hook_event("Write", {"file_path": "/etc/hosts"}, cwd=project_root))
    row = rows(project_root)[-1]
    assert row["result"] == "차단"
    assert row["handledBy"] == "Hooks · 잠금"
    assert row["action"] == "프로젝트 폴더 밖 쓰기·삭제"


def test_허용도_빠짐없이_남는다(project, project_root, hook_event):
    run_pre(hook_event("Write", {"file_path": f"{project_root}/logs/Decision_log.md"}, cwd=project_root))
    row = rows(project_root)[-1]
    assert row["result"] == "허용" and row["action"] == "기록 갱신"


def test_권한_우회_모드는_기록된다(project, project_root, hook_event):
    event = hook_event(
        "Write", {"file_path": f"{project_root}/src/x.py"}, cwd=project_root,
        permission_mode="bypassPermissions",
    )
    run_pre(event)
    assert any(row["action"] == "권한 우회 모드" for row in rows(project_root))


def test_시각은_ISO_8601(project, project_root, hook_event):
    from datetime import datetime

    run_pre(hook_event("Write", {"file_path": "/etc/hosts"}, cwd=project_root))
    stamp = rows(project_root)[-1]["time"]
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None  # 오프셋이 붙어 있다


# --- 서브에이전트 거르개 (판 2 · 2026-11-04) ---------------------------------


def with_agent(tool_use_id, agent_id):
    A.open_pending(
        "hook-sandbox",
        tool_use_id,
        {
            "promptId": "p1",
            "sessionId": "sess-테스트",
            "tool": "Write",
            "action": "코드 수정",
            "request": "experiments/EXP-002/c.py",
            "agentId": agent_id,
            "agentType": "general-purpose" if agent_id else "",
        },
    )


def test_main_only_는_서브에이전트_건을_뺀다(project):
    with_agent("t-main", "")
    with_agent("t-agent", "a85e6d7a23abaefce")
    assert [i["toolUseId"] for i in A.list_pending("hook-sandbox", main_only=True)] == ["t-main"]
    assert len(A.list_pending("hook-sandbox")) == 2


def test_agent_id_로_그_에이전트만(project):
    with_agent("t-a", "aaaa1111")
    with_agent("t-b", "bbbb2222")
    got = A.list_pending("hook-sandbox", agent_id="bbbb2222")
    assert [i["toolUseId"] for i in got] == ["t-b"]


def test_거르개를_안_주면_전부(project):
    with_agent("t-main", "")
    with_agent("t-agent", "aaaa1111")
    assert len(A.list_pending("hook-sandbox")) == 2


def test_close_stale_이_거르개를_따른다(project, project_root):
    with_agent("t-main", "")
    with_agent("t-agent", "aaaa1111")
    closed = A.close_stale("hook-sandbox", project_root, project, main_only=True)
    assert [c["toolUseId"] for c in closed] == ["t-main"]
    assert [i["toolUseId"] for i in A.list_pending("hook-sandbox")] == ["t-agent"]


def test_sweep_기록에_거르개가_남는다(project, project_root):
    with_agent("t-agent", "aaaa1111")
    A.close_stale("hook-sandbox", project_root, project, agent_id="aaaa1111", by="SubagentStop")
    last = [e for e in events(project_root) if e.get("event") == "sweep"][-1]
    assert last["agentId"] == "aaaa1111" and last["mainOnly"] is False
