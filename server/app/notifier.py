"""Discord 알림 — 임베드 조립 · 종류별 채널 · 중복 제거 · 재시도.

`app/notify.py` 와 역할이 다르다.

| | `notify.py` | `notifier.py` (이 모듈) |
|---|---|---|
| 훅 경로 | **O** — 최소 전송만 | X |
| 아는 것 | 웹훅 주소와 HTTP | DB·쿨다운·임베드 모양 |

②가 보내는 알림은 종류가 정해져 있다(`KINDS`). 문구는 **한국어 해요체**이고
승인 알림에는 **훅이 쓴 사유를 전문으로** 싣는다 — ①의 숙제였다. 평문
1900자 자르기 대신 임베드 필드로 보내서 사유가 안 잘리게 한다.

**전송 실패가 큐를 멈추지 않는다.** 어떤 예외도 올리지 않고 결과 dict 만
돌려준다.
"""

from __future__ import annotations

import time

from . import config, db, embed, notify
from .store import notifications as N

__all__ = ["KINDS", "COLORS", "build", "send", "subject_of"]

#: 알림 종류. 쿨다운과 채널 라우팅의 열쇠이기도 하다.
KINDS = (
    "approval",  # 승인이 필요해요 — 사유 전문을 싣는다
    "start",  # 실험을 시작했어요
    "done",  # 실험이 끝났어요
    "failure",  # 실패했어요
    "usage_limit",  # 응답이 막혔어요 (추가 결제 없이 기다려요)
    "driver",  # GPU 드라이버 불일치
    "gpu",  # GPU 조회 상태가 바뀜
    "recovery",  # 재부팅 뒤 복구했어요
    "blocked",  # 같은 요청이 반복돼서 멈췄어요
    "test",  # labremote notify test
)

#: 임베드 왼쪽 띠 색은 `app/embed.py` 가 단일 출처다 — 훅도 같은 모양을 쓴다.
COLORS = embed.COLORS

#: 5xx 재시도 간격(초). 429 는 `Retry-After` 를 따른다.
BACKOFF_SEC = (1, 4, 16)
MAX_ATTEMPTS = 3


def subject_of(*parts: str) -> str:
    """중복 제거 열쇠에 쓸 주제. "무엇에 대한 알림인가" 를 한 줄로."""
    return "·".join(str(p) for p in parts if p)


def build(
    kind: str,
    *,
    project: str = "",
    title: str,
    body: str = "",
    fields: list[tuple[str, str]] | None = None,
    footer: str = "",
) -> dict:
    """Discord 임베드 payload. 사유가 길면 필드를 나눠 담는다."""
    if kind not in KINDS:
        raise ValueError(f"모르는 알림 종류예요: {kind!r}")
    return embed.build(
        kind,
        project=project,
        title=title,
        body=body,
        fields=fields,
        footer=footer,
        at=db.now(),
    )


def send(
    conn,
    kind: str,
    *,
    project: str = "",
    subject: str = "",
    title: str,
    body: str = "",
    fields: list[tuple[str, str]] | None = None,
    footer: str = "",
    cooldown_sec: int | None = None,
    poster=None,
    sleep=None,
    now_ts: float | None = None,
) -> dict:
    """중복을 걸러 보낸다. 결과를 dict 로 돌려주고 **던지지 않는다.**

    `poster`·`sleep` 은 시험에서 바꿔 끼운다 (실제 전송은 `notify.send_payload`).
    """
    try:
        return _send(
            conn,
            kind,
            project=project,
            subject=subject or title,
            title=title,
            body=body,
            fields=fields,
            footer=footer,
            cooldown_sec=cooldown_sec,
            poster=poster or notify.send_payload,
            sleep=sleep or time.sleep,
            now_ts=now_ts,
        )
    except Exception as exc:  # pragma: no cover - 알림이 큐를 멈추면 안 된다
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}


def _send(
    conn,
    kind,
    *,
    project,
    subject,
    title,
    body,
    fields,
    footer,
    cooldown_sec,
    poster,
    sleep,
    now_ts,
):
    cooldown = (
        config.cooldown_sec(kind) if cooldown_sec is None else int(cooldown_sec)
    )
    key = N.dedupe_key(project, kind, subject, cooldown, now_ts=now_ts)
    route = notify.webhook_url(kind)
    claimed = N.claim(
        conn, key, project=project or None, kind=kind, title=title, body=body, route=route
    )
    if claimed is None:
        # 같은 알림을 쿨다운 안에서 또 보내려 했다. 조용히 넘긴다.
        return {"sent": False, "suppressed": True, "dedupeKey": key}

    payload = build(
        kind, project=project, title=title, body=body, fields=fields, footer=footer
    )
    last: dict = {}
    for attempt in range(MAX_ATTEMPTS):
        last = poster(payload, kind=kind) or {}
        if last.get("sent"):
            N.mark_sent(conn, claimed["id"], last.get("status"))
            return {**last, "id": claimed["id"], "dedupeKey": key}
        status = last.get("status")
        if status == 429:
            wait = _retry_after(last.get("retryAfter"), BACKOFF_SEC[attempt])
        elif isinstance(status, int) and 500 <= status < 600:
            wait = BACKOFF_SEC[attempt]
        else:
            break  # 주소가 없거나 꺼져 있거나 4xx — 다시 시도해도 같다
        if attempt + 1 >= MAX_ATTEMPTS:
            break
        sleep(wait)

    N.mark_failed(
        conn,
        claimed["id"],
        error=str(last.get("reason") or "보내지 못했어요"),
        status=last.get("status"),
    )
    return {**last, "id": claimed["id"], "dedupeKey": key, "sent": False}


def _retry_after(value, fallback: int) -> float:
    try:
        wait = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(wait, 60.0))  # 터무니없이 긴 값에 루프가 잡히지 않게
