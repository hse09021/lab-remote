"""SessionEnd — Stop 이 못 돈 잔여분 정리.

세션이 강제로 끝나거나 크래시하면 Stop 이 안 돌 수 있다. 그때 남은 대기 건을
같은 사유로 마감한다. 여기서는 **세션 전체**를 보고, **서브에이전트 대기 건도
닫는다** — 대기 건 마감의 마지막 그물이다.

실측(2.1.317)의 SessionEnd 최상위:
    session_id, transcript_path, cwd, prompt_id, hook_event_name, reason
`permission_mode` 와 `effort` 는 오지 않는다.

아무것도 막지 않는다. 언제나 조용히 exit 0.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import sys

from . import stop

__all__ = ["main", "handle"]


def handle(event: dict) -> list[dict]:
    # prompt_id 를 비워 세션 전체를 훑게 한다.
    scoped = {k: v for k, v in event.items() if k != "prompt_id"}
    # 마지막 그물이라 **서브에이전트 대기 건까지** 닫는다 (main_only=False).
    # 세션이 끝났으면 그 에이전트도 더는 돌지 않는다.
    return stop.handle(scoped, event_name="SessionEnd", main_only=False)


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
