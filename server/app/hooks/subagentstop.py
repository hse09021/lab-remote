"""SubagentStop — 백그라운드 에이전트가 멈췄다. 그 에이전트의 대기 건을 마감한다.

**왜 이 훅이 필요한가** (실측 2026-11-04 02:03)

서브에이전트의 PreToolUse 는 **자기를 띄운 턴의 `prompt_id` 를 그대로** 들고
온다. 그래서 메인 턴의 `Stop` 이 응답 단위로 닫을 때, 아직 승인창이 열려 있는
서브에이전트 대기 건까지 끌려 닫혔다.

    02:03:12  PreToolUse  Write c.py          -> ask (대기 건 열림)
    02:03:13  Stop        promptId=f7991340…  -> "거부 또는 미응답" 으로 닫음
    02:06:59  PostToolUse Write c.py          -> "허용" (늦은 승인)

늦은 승인 처리는 동작했지만 그 사이 4분간 기록이 "거부" 로 보였다. 이제 `Stop`
은 서브에이전트 건을 건드리지 않고(`main_only=True`), 닫는 일을 이 훅이 맡는다.

**이 이벤트의 입력은 아직 실측 못 했다 [미확인].** 2.1.317 번들의 훅 이벤트
목록에 `SubagentStop` 이 있는 건 확인했고, 공통 입력 스키마에 `agent_id` 가
"서브에이전트 안에서 뜬 훅에만 있다" 고 적혀 있다. 그래서

  - `agent_id` 가 오면  -> 그 에이전트 것만 닫는다 (`by="SubagentStop"`)
  - 안 오면            -> 그 세션의 서브에이전트 건 전부 (`by="SubagentStop-session"`)

어느 쪽으로 갔는지 `logs/hook_events.jsonl` 의 `sweep.by` 에 남으므로, 한 번
돌려 보면 확정된다. `LABREMOTE_HOOK_DUMP=1` 이면 stdin 을 받아 적어 픽스처로
올릴 수 있다.

이 훅이 안 와도 **작업 알림**(`userprompt.py`)과 `SessionEnd` 가 뒤를 받는다.
세 닫개가 겹쳐도 `close_pending` 이 이미 닫힌 건에 `None` 을 돌려주므로 행이
두 줄 생기지 않는다.

아무것도 막지 않는다. stdout 없이 언제나 조용히 exit 0.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import sys

from .. import approval_log as A
from . import debug
from .common import project_of

__all__ = ["main", "handle"]


def handle(event: dict) -> list[dict]:
    found = project_of(event)
    if not found:
        return []
    root, name, pol = found

    agent_id = str(event.get("agent_id") or "")
    session_id = str(event.get("session_id") or "")
    if agent_id:
        return A.close_stale(
            name, root, pol, session_id=session_id, agent_id=agent_id, by="SubagentStop"
        )

    # agent_id 가 없으면 누가 멈췄는지 모른다. 그 세션의 서브에이전트 건을
    # 전부 닫는다 — 열린 채로 두면 대기 뱃지가 거짓으로 켜져 있게 된다.
    closed = []
    for item in A.list_pending(name, session_id=session_id or None):
        if not item.get("agentId"):
            continue  # 메인 스레드 건은 Stop 의 몫이다
        closed += A.close_stale(
            name,
            root,
            pol,
            session_id=session_id,
            agent_id=str(item["agentId"]),
            by="SubagentStop-session",
        )
    return closed


def main() -> int:
    try:
        raw = sys.stdin.read()
        # 아직 실측 전인 이벤트다. 덤프를 켜 두면 픽스처로 쓸 수 있다.
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
