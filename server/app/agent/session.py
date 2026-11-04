"""세션 ID — **우리가 미리 정한다.**

`--session-id <uuid>` 로 넘기면 출력을 파싱하지 않고도 `--resume` 할 수 있다.
승인 뒤 이어 가는 경로(6-1)의 전제다.

`--fork-session` 은 쓰지 않는다 — 세션 ID 가 바뀌면 재시도 상한 추적이 끊긴다.
"""

from __future__ import annotations

import re
import uuid

__all__ = ["UUID_RE", "new_id", "is_valid", "same"]

#: `claude --session-id` 가 받는 모양 (uuid4)
UUID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I
)


def new_id() -> str:
    """새 세션 ID. 작업을 큐에 넣을 때 만들어 `jobs.session_id` 에 둔다."""
    return str(uuid.uuid4())


def is_valid(session_id) -> bool:
    return bool(session_id) and bool(UUID_RE.match(str(session_id)))


def same(a, b) -> bool:
    """대소문자만 다른 건 같은 것으로 본다."""
    return is_valid(a) and is_valid(b) and str(a).lower() == str(b).lower()
