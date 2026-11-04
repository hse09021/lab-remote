"""PostToolUse — 도구가 실제로 돌았으니 대기 건을 "허용" 으로 마감.

실측(2.1.317): **거절된 호출은 PostToolUse 가 오지 않는다.** 그래서 여기로
온 건 사용자가 허용했다는 뜻이고, 안 온 건 Stop 이 마감한다.

**이미 닫힌 대기 건에도 온다.** 백그라운드 서브에이전트의 승인창은 새
프롬프트 뒤까지 열려 있을 수 있어서(10단계 초반 실측), `UserPromptSubmit`
이 `거부 또는 미응답` 으로 닫은 뒤에 뒤늦게 승인되는 일이 있다. 그때도
`허용` 행을 **그대로 덧붙인다** — 로그는 append-only 이고, 화면은 같은
`toolUseId` 의 마지막 행을 따른다(`approval_log.group_rows`).

아무것도 막지 않는다. 언제나 조용히 exit 0.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import sys

from .. import approval_log as A
from . import messages as M
from .common import project_of

__all__ = ["main", "handle"]


def handle(event: dict) -> dict | None:
    found = project_of(event)
    if not found:
        return None
    root, name, pol = found

    tool_use_id = str(event.get("tool_use_id") or "")
    if not tool_use_id:
        tool_use_id = f"{event.get('prompt_id') or ''}:{event.get('tool_name') or ''}"

    late = False
    pending = A.close_pending(name, tool_use_id)
    if pending is None:
        # 이미 닫힌 건인가 (늦게 승인된 백그라운드 호출), 아니면 애초에
        # 대기 건이 아니었나 (allow·defer 로 지나간 호출).
        pending = A.recall_closed(name, tool_use_id)
        if pending is None:
            return None
        late = True

    A.append_row(
        A.log_path(root, pol),
        project=name,
        action=str(pending.get("action") or event.get("tool_name") or ""),
        request=str(pending.get("request") or ""),
        result="허용",
        handled_by=M.BY_APP,
        tool_use_id=tool_use_id,
    )
    A.log_event(
        A.event_path(root, pol),
        {
            "event": "PostToolUse",
            "tool": event.get("tool_name"),
            "toolUseId": tool_use_id,
            "promptId": event.get("prompt_id"),
            "closed": "허용",
            **({"late": True} if late else {}),
        },
    )
    return pending


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
