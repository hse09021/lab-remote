"""UserPromptSubmit — 새 프롬프트가 왔다. 이전 턴의 대기 건을 마감한다.

**왜 이 훅이 필요한가** (실측 2026-11-04)

PC 터미널에서 승인을 거부하면 턴이 "Interrupted" 로 끊기고 **`Stop` 훅이
돌지 않는다.** `Stop` 은 `prompt_id` 로 그 응답 것만 닫으므로 다음 턴의
`Stop` 도 이전 턴 대기 건을 지나치고, 결국 `SessionEnd` 가 세션을 닫을 때까지
"대기 중" 으로 남는다. 실측에서는 25분간 대기 뱃지가 거짓으로 켜져 있었다
(`logs/Approval_log.csv` 13·15·25·28행이 34~37행에서 한꺼번에 닫혔다).

새 프롬프트가 들어온 **이 시점에 열려 있는 메인 스레드 대기 건은 전부 이전 턴
것**이다. 아직 이 턴의 도구는 하나도 돌지 않았다. 그래서 `prompt_id` 를 보지
않고 세션 전체를 닫는다.

**서브에이전트 대기 건은 건드리지 않는다** (`main_only=True`). 승인창이 열려
있는 동안에는 PC·휴대폰 입력란이 가려져 사람이 새 프롬프트를 보낼 수도 없다 —
여기는 그 대기 건을 닫을 자리가 아니다 (`subagentstop.py` 의 설명).

실측한 최상위 필드 (2026-11-04 · 2.1.317 · 덤프 4건):

    session_id, transcript_path, cwd, scratchpad_dir, prompt_id,
    permission_mode, hook_event_name, prompt

`prompt` 가 사람이 쓴 글이 아닐 수 있다. **작업 알림**이 같은 이벤트로 온다:

    <task-notification>
    <task-id>a85e6d7a23abaefce</task-id>      <- PreToolUse 의 agent_id 와 같은 값
    <status>completed</status>
    <note>A task-notification fires each time this agent stops with no live
    background children of its own. …the same task-id may notify more than once.</note>

즉 "그 에이전트가 멈췄다" 는 신호다. `task-id` 를 뽑아 그 에이전트의 대기 건도
닫는다 — `SubagentStop` 이 안 오는 경우의 2차 닫개다. 같은 알림이 여러 번 와도
두 번째부터는 닫을 게 없어 조용히 지나간다.

아무것도 막지 않는다. stdout 없이 언제나 조용히 exit 0.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import re
import sys

from .. import approval_log as A
from . import debug
from .common import project_of

__all__ = ["main", "handle", "task_id_of", "TASK_ID_RE"]

#: 작업 알림의 `<task-id>`. 그 값이 PreToolUse 의 `agent_id` 와 같다 (실측).
TASK_ID_RE = re.compile(
    r"<task-notification>.*?<task-id>\s*([A-Za-z0-9_.:-]+)\s*</task-id>", re.S
)


def task_id_of(event: dict) -> str:
    """작업 알림이면 그 `task-id`(= `agent_id`), 사람 프롬프트면 빈 문자열."""
    match = TASK_ID_RE.search(str(event.get("prompt") or ""))
    return match.group(1) if match else ""


def handle(event: dict) -> list[dict]:
    found = project_of(event)
    if not found:
        return []
    root, name, pol = found
    session_id = str(event.get("session_id") or "")

    closed = A.close_stale(
        name,
        root,
        pol,
        session_id=session_id,
        main_only=True,  # 서브에이전트는 자기가 멈출 때 닫는다
        by="UserPromptSubmit",
    )

    agent_id = task_id_of(event)
    if agent_id:
        closed += A.close_stale(
            name,
            root,
            pol,
            session_id=session_id,
            agent_id=agent_id,
            by="taskNotification",
        )
    return closed


def main() -> int:
    try:
        raw = sys.stdin.read()
        if os.environ.get("LABREMOTE_HOOK_DUMP") == "1":
            try:
                debug.dump(raw)
            except Exception:
                pass
        event = json.loads(raw)
        if isinstance(event, dict):
            handle(event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
