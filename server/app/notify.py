"""Discord 웹훅 알림.

조용히 멈추지 않게 하는 용도다. 승인이 필요한데 사람에게 물어볼 수 없는
상황(헤드리스)에서 "승인 대기" 를 알린다.

**실패해도 판정에 영향이 없어야 한다.** 네트워크가 죽어도 훅은 제시간에
결정을 돌려줘야 하므로 타임아웃을 짧게 잡고 예외를 삼킨다.

웹훅 URL 은 환경 변수 `LAB_DISCORD_WEBHOOK` 에서 읽는다 (`.env` 는 커밋 금지).

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["webhook_url", "send"]

TIMEOUT_SEC = 3


def webhook_url() -> str:
    return os.environ.get("LAB_DISCORD_WEBHOOK", "").strip()


def send(text: str) -> dict:
    """보내 보고 결과를 돌려준다. 던지지 않는다."""
    url = webhook_url()
    if not url:
        return {"sent": False, "reason": "LAB_DISCORD_WEBHOOK 이 비어 있어요"}
    if os.environ.get("LAB_NOTIFY_DISABLED") == "1":
        return {"sent": False, "reason": "알림이 꺼져 있어요"}

    body = json.dumps({"content": text[:1900]}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as resp:
            return {"sent": 200 <= resp.status < 300, "status": resp.status}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"sent": False, "reason": str(exc)}
