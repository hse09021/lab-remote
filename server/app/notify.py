"""Discord 웹훅 전송 — 최소한만.

웹훅 주소는 환경 변수 `LAB_DISCORD_WEBHOOK`이 먼저고, 없으면 데이터 폴더의
`discord.json`(권한 0600)에서 읽는다(`config.discord_webhook`). 주소 원문은
로그·화면·에러에 찍지 않는다.

**실패해도 예외를 올리지 않는다.** 타임아웃을 짧게 잡고 결과 dict만 돌려준다.
재시도·중복 제거·임베드는 `app/notifier.py`가 맡는다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["USER_AGENT", "HEADERS", "webhook_url", "send", "send_payload"]

#: 🔑 보내는 쪽 이름. **Discord가 파이썬 기본 User-Agent를 403으로 막는다**
#: (실측 2026-11-05: 같은 URL에 `curl`은 204, `urllib` 기본값은
#: `HTTP Error 403: Forbidden`). 고정값을 쓴다.
#:
#: 개인 정보를 넣지 않는다 — 이메일·호스트 이름·프로젝트 이름을 싣지 않는다.
#: 웹훅은 Discord 서버로 나가는 요청이다.
USER_AGENT = "lab.remote-notifier/1.0"

#: 모든 요청에 붙이는 헤더
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}

TIMEOUT_SEC = 3


def webhook_url(kind: str = "") -> str:
    """보낼 주소. 환경 변수가 이기고, 없으면 데이터 폴더의 설정을 본다.

    설정을 못 읽어도 알림만 안 가야 한다 — 예외를 올리지 않는다.
    """
    env = os.environ.get("LAB_DISCORD_WEBHOOK", "").strip()
    if env:
        return env
    try:
        from . import config

        return config.discord_webhook(kind)
    except Exception:
        return ""


def send(text: str, kind: str = "") -> dict:
    """평문 한 줄을 보낸다. 던지지 않는다."""
    return send_payload({"content": text[:1900]}, kind=kind)


def send_payload(payload: dict, *, kind: str = "", url: str = "") -> dict:
    """Discord에 JSON 한 덩어리를 보낸다 (임베드는 `app/notifier.py`가 만든다).

    **어떤 경우에도 예외를 올리지 않는다.**
    """
    target = url or webhook_url(kind)
    if not target:
        return {"sent": False, "reason": "웹훅 주소가 비어 있어요"}
    if os.environ.get("LAB_NOTIFY_DISABLED") == "1":
        return {"sent": False, "reason": "알림이 비활성화돼 있어요"}

    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return {"sent": False, "reason": f"보낼 내용을 JSON으로 만들 수 없어요: {exc}"}
    request = urllib.request.Request(target, data=body, headers=dict(HEADERS))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as resp:
            return {"sent": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as exc:
        # 429(너무 자주)·5xx(서버)는 notifier가 다시 시도한다.
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        return {
            "sent": False,
            "status": exc.code,
            "retryAfter": retry_after,
            "reason": str(exc),
        }
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # 주소가 메시지에 섞여 나올 수 있어 원문을 싣지 않는다.
        return {"sent": False, "reason": type(exc).__name__}
