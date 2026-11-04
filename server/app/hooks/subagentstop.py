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

**입력 실측 완료** (2026-11-04 09:27~09:33, 2.1.317 native).
픽스처: `tests/fixtures/hook_events/20261104-0930*-SubagentStop.json`

    session_id, transcript_path, cwd, scratchpad_dir, prompt_id,
    permission_mode, agent_id, agent_type, effort{level}, hook_event_name,
    stop_hook_active, agent_transcript_path, last_assistant_message,
    background_tasks[], session_crons[]

`agent_id` 가 **온다.** 그래서 위의 첫 갈래(`by="SubagentStop"`)로 간다.
두 번째 갈래는 다른 버전 대비로 남겨 둔다.

**한 턴에 SubagentStop 이 두 번 온다.** 같은 이벤트가 두 번 오는 게 아니라
`agent_id` 가 서로 다른 두 에이전트다. 두 회차 모두 같은 모양이었다.

    09:30:51  SubagentStop  agent=af3199313de4e46ff  type="general-purpose"
    09:30:58  SubagentStop  agent=afbdfab71ba9cbf43  type=""

둘째는 `agent_type` 이 빈 문자열이고 PreToolUse 를 한 번도 낸 적이 없는
`agent_id` 다. 무엇을 가리키는지는 덤프만으로는 모른다 [미확인]. 다만 **대기
건과 절대 안 맞으므로 해가 없다** — `agent_id` 로 묶기 때문이다. 만약
`prompt_id` 로 묶었다면 2회차에서 사고가 났다.

    09:33:12  PreToolUse    Write e.py              -> ask (대기 건 열림)
    09:33:15  SubagentStop  agent=a35d1440…  type=""   ← 승인 26초 전
    09:33:41  PostToolUse   Write e.py              -> "허용"

`prompt_id` 로 묶었다면 09:33:15 가 대기 건을 가로채 거짓 "거부 또는 미응답"
을 남겼을 것이다. 실제로는 아무 일도 없었고 09:33:41 에 "허용" 으로 닫혔다.

**거부 경로에도 이 훅이 온다.** 1회차에서 사람이 승인창을 거부하자
09:30:51 에 SubagentStop 이 왔고, 그 에이전트의 대기 건이 "거부 또는 미응답"
으로 닫혔다. 그전까지(09:27:38) `Stop` 은 `skippedAgents` 로 건너뛰며
`closed: []` 를 남겼다 — 설계대로다.

또 하나: SubagentStop 시점에도 `background_tasks` 의 자기 항목이 아직
`status: "running"` 이다. "끝났나" 를 그 필드로 판단하면 안 된다.

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
