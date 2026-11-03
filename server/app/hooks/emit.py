"""결정 -> stdout JSON.

반환 방식 두 가지(종료코드 0/2 · stdout JSON)는 **배타적**이라 섞으면 안 된다.
우리는 stdout JSON 만 쓴다 — 사유와 `allow`/`ask` 를 같이 실어야 하기 때문이다.
그래서 **종료코드는 언제나 0** 이다.

stdout 에 JSON 말고 아무것도 섞이면 안 된다. 디버그 출력은 전부 stderr 나
logs/hook_events.jsonl 로 보낸다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

__all__ = ["Decision", "ALLOW", "ASK", "DENY", "DEFER", "payload", "emit"]

#: 가장 제한적인 것이 이긴다
PRIORITY = {"deny": 3, "ask": 2, "defer": 1, "allow": 0}


@dataclass
class Decision:
    kind: str  # allow | ask | deny | defer
    reason: str = ""
    #: 승인 로그의 `action` 칸에 쓸 이름
    label: str = ""
    #: 어떤 Finding 에서 나왔는지 (로그·우회 추적용)
    action: str = ""
    rel: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def rank(self) -> int:
        return PRIORITY.get(self.kind, 0)


def ALLOW(reason: str = "", **kw) -> Decision:
    return Decision("allow", reason, **kw)


def ASK(reason: str = "", **kw) -> Decision:
    return Decision("ask", reason, **kw)


def DENY(reason: str = "", **kw) -> Decision:
    return Decision("deny", reason, **kw)


def DEFER(reason: str = "", **kw) -> Decision:
    """Claude Code 기본 권한 흐름에 맡긴다.

    훅이 함부로 `allow` 를 돌려주면 Claude Code 자체 보호장치까지 건너뛴다.
    그래서 "우리 규칙에 안 걸림" 은 allow 가 아니라 defer 다.
    """
    return Decision("defer", reason, **kw)


def payload(decision: Decision, event_name: str = "PreToolUse") -> dict:
    out = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": decision.kind,
        }
    }
    if decision.reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = decision.reason
    return out


def emit(decision: Decision, event_name: str = "PreToolUse", stream=None) -> int:
    """stdout 에 JSON 한 덩어리만 쓰고 0 을 돌려준다."""
    (stream or sys.stdout).write(json.dumps(payload(decision, event_name), ensure_ascii=False))
    return 0
