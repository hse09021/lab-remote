"""PostToolUse — 도구가 실제로 돌았으니 대기 건을 "허용" 으로 마감.

실측(2.1.317): **거절된 호출은 PostToolUse 가 오지 않는다.** 그래서 여기로
온 건 사용자가 허용했다는 뜻이고, 안 온 건 Stop 이 마감한다.

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

    pending = A.close_pending(name, tool_use_id)
    if pending is None:
        return None  # 대기 건이 아니었다 (allow 나 defer 로 지나간 호출)

    A.append_row(
        A.log_path(root, pol),
        action=str(pending.get("action") or event.get("tool_name") or ""),
        request=str(pending.get("request") or ""),
        result="허용",
        handled_by=M.BY_APP,
    )
    A.log_event(
        A.event_path(root, pol),
        {
            "event": "PostToolUse",
            "tool": event.get("tool_name"),
            "toolUseId": tool_use_id,
            "promptId": event.get("prompt_id"),
            "closed": "허용",
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
