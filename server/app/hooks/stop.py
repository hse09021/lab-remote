"""Stop — 응답이 끝났다. 그 응답에서 안 돌아간 대기 건을 마감한다.

한 응답 안에서 도구는 돌거나 안 돌거나 둘 중 하나다. Stop 시점에 대기 건이
남아 있다는 건 사용자가 거부했거나 응답이 없었다는 뜻이다.

**단, 서브에이전트 것은 건드리지 않는다** (`main_only=True` 가 기본).
실측(2026-11-04 02:03): 서브에이전트의 PreToolUse 는 자기를 띄운 턴의
`prompt_id` 를 그대로 들고 오므로, 메인 턴이 끝날 때 아직 승인창이 열려 있는
그 대기 건까지 끌려 닫혔다. 서브에이전트는 메인 턴이 끝나도 계속 돈다 —
닫는 건 `SubagentStop`·작업 알림·`SessionEnd` 의 몫이다.

**세션이 아니라 응답(prompt_id) 단위로 묶는다.** 실측(2.1.317)에서
PreToolUse 와 Stop 둘 다 최상위에 `prompt_id` 를 들고 오는 걸 확인했다.
세션으로 묶으면 같은 세션의 다른 응답에서 막 연 대기 건까지 끌려 닫힌다.
`prompt_id` 가 없는 버전에서만 `session_id` 로 떨어진다.

아무것도 막지 않는다. 언제나 조용히 exit 0.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import sys

from .. import approval_log as A
from . import messages as M
from .common import project_of

__all__ = ["main", "handle", "RESULT"]

#: 사용자가 거부했는지 그냥 응답이 없었는지는 훅이 구분할 수 없다.
RESULT = A.RESULT_NO_ANSWER


def handle(event: dict, *, event_name: str = "Stop", main_only: bool = True) -> list[dict]:
    found = project_of(event)
    if not found:
        return []
    root, name, pol = found

    prompt_id = str(event.get("prompt_id") or "")
    session_id = str(event.get("session_id") or "")
    # prompt_id 가 있으면 그 응답 것만. 없으면 세션 전체로 떨어진다.
    pending = A.list_pending(
        name, prompt_id=prompt_id, session_id=session_id, main_only=main_only
    )
    # 건너뛴 서브에이전트 건 — 로그만 보고도 "왜 안 닫았는지" 가 보이게 남긴다
    skipped = (
        [
            item.get("toolUseId")
            for item in A.list_pending(name, prompt_id=prompt_id, session_id=session_id)
            if item.get("agentId")
        ]
        if main_only
        else []
    )

    closed: list[dict] = []
    for item in pending:
        tool_use_id = str(item.get("toolUseId") or "")
        got = A.close_pending(name, tool_use_id)
        if got is None:
            continue  # PostToolUse 가 먼저 닫았다 — 두 번 기록하지 않는다
        A.append_row(
            A.log_path(root, pol),
            project=name,
            action=str(got.get("action") or ""),
            request=str(got.get("request") or ""),
            result=RESULT,
            handled_by=M.BY_APP,
            tool_use_id=tool_use_id,
        )
        closed.append(got)

    if closed or skipped:
        A.log_event(
            A.event_path(root, pol),
            {
                "event": event_name,
                "promptId": prompt_id,
                "sessionId": session_id,
                "closed": [c.get("toolUseId") for c in closed],
                "result": RESULT,
                "by": "promptId" if prompt_id else "sessionId",
                **({"skippedAgents": skipped} if skipped else {}),
            },
        )
    return closed


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        if isinstance(event, dict):
            handle(event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
