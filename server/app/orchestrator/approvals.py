"""승인 대기열 — ①이 넘긴 숙제 1번.

훅이 헤드리스에서 막은 요청은 `server/data/requests/<프로젝트>/` 에 쌓인다.
①에서는 **쌓이기만 하고 닫아 줄 주체가 없었다.** 여기가 그 주체다.

```
훅이 ask -> deny-with-reason -> requests/*.json  +  Discord(사유 전문)
  -> sync()      파일을 DB 로 거울 (사람·화면이 보는 쪽)
  -> approve()   1회용 허가 발급 (HMAC 서명) + 요청 닫기
  -> 오케스트레이터가 claude -p --resume 로 이어 감
  -> 훅이 같은 호출에서 허가를 원자적으로 소비 -> ALLOW
```

**잠긴 항목은 승인으로도 안 열린다** — `grants.issue` 가 거절한다.
"""

from __future__ import annotations

from .. import approval_log as A
from .. import grants
from ..store import approvals as AP
from ..store import events as E

__all__ = ["MAX_ATTEMPTS", "sync", "pending", "approve", "deny", "too_many"]

#: 같은 요청이 이만큼 반복되면 루프를 멈춘다 (무한 반복 방지)
MAX_ATTEMPTS = 2


def sync(conn, project: str, *, job_id: int | None = None) -> list[dict]:
    """`requests/` 의 파일을 DB 로 거울. **파일이 진실이다.**

    같은 요청이 또 오면 `attempts` 만 올라간다 (UNIQUE 제약).
    """
    out = []
    for item in A.list_requests(project):
        request_id = str(item.get("requestId") or "")
        if not request_id:
            continue
        actions = item.get("actions") or []
        row = AP.open_request(
            conn,
            project,
            request_id,
            job_id=job_id,
            session_id=str(item.get("sessionId") or ""),
            tool=str(item.get("tool") or ""),
            action_key=str(item.get("actionKey") or ""),
            rel=item.get("rel"),
            request=str(item.get("request") or ""),
            reason=str(item.get("reason") or ""),
            fingerprint=str(item.get("fingerprint") or ""),
            loose_key=str(item.get("looseKey") or ""),
        )
        out.append({**row, "actions": actions, "file": item})
    return out


def pending(conn, project: str) -> list[dict]:
    """아직 **안 닫힌** 요청. 파일이 진실이다.

    승인(`approve`)은 요청 파일을 닫지 않는다 — 훅이 허가를 **소비할 때**
    닫는다. 그래서 DB 의 `state` 가 아니라 **파일이 남아 있는가**로 센다.
    거절한 건은 파일이 사라지므로 자연히 빠진다.
    """
    out = []
    for item in A.list_requests(project):
        request_id = str(item.get("requestId") or "")
        row = AP.by_request(conn, project, request_id) or {}
        if row.get("state") == "denied":
            continue
        out.append({**row, "request_id": request_id, "file": item})
    return out


def too_many(row: dict) -> bool:
    return int(row.get("attempts") or 0) > MAX_ATTEMPTS


def approve(
    conn,
    project: str,
    request_id: str,
    *,
    ttl_sec: int = grants.DEFAULT_TTL_SEC,
    loose: bool = False,
    note: str = "",
    by: str = "cli",
) -> dict:
    """1회용 허가를 발급하고 요청을 닫는다.

    **잠긴 항목이면 `grants.GrantError` 다** — CLI 가 그대로 보여 준다.
    승인 1회가 **그 호출의 ask 를 전부** 연다 (`actions`).
    """
    found = [i for i in A.list_requests(project) if str(i.get("requestId") or "") == request_id]
    if not found:
        raise grants.GrantError(f"그런 승인 요청이 없어요: {request_id}")
    item = found[0]
    actions = [a.get("action") for a in (item.get("actions") or []) if a.get("action")]
    tool = str(item.get("tool") or "")

    grant = grants.issue(
        project,
        tool=tool,
        tool_input=_tool_input_of(item),
        # 훅이 계산한 지문을 그대로 쓴다 — 우리는 본문을 안 가지고 있다.
        fingerprint_override=str(item.get("fingerprint") or ""),
        action_key=str(item.get("actionKey") or (actions[0] if actions else "")),
        actions=actions or None,
        rel=item.get("rel"),
        request_id=request_id,
        session_id=str(item.get("sessionId") or ""),
        summary=str(item.get("request") or "")[:200],
        ttl_sec=ttl_sec,
        loose=loose,
        note=note,
        granted_by=by,
    )
    AP.decide(conn, project, request_id, "approved", grant_id=grant["grantId"], by=by)
    E.add(
        conn,
        project,
        "승인",
        f"{item.get('action') or '요청'} 을 승인했어요 · {grant['grantId']}",
        tone="good",
        ref=request_id,
    )
    # 요청 파일은 훅이 허가를 **소비할 때** 닫는다. 여기서 지우면 재개한
    # 세션이 "무엇을 승인받았는지" 를 못 본다.
    return grant


def deny(conn, project: str, request_id: str, *, reason: str = "", by: str = "cli") -> dict:
    """거절한다. 요청 파일을 닫고 기록을 남긴다."""
    row = AP.decide(conn, project, request_id, "denied", by=by)
    A.close_request(project, request_id, result=f"거절 · {reason or '사유 없음'}")
    E.add(conn, project, "승인", f"요청을 거절했어요: {reason or '사유 없음'}", tone="attention", ref=request_id)
    return row


def _tool_input_of(item: dict) -> dict:
    """저장된 입력 요약. **지문 계산에는 쓰지 않는다.**

    요청 파일에는 본문을 저장하지 않는다(비밀이 섞일 수 있다). 지문은
    훅이 계산해 파일에 적어 둔 값을 그대로 쓴다 (`fingerprint_override`).
    여기 값은 허가 파일에 "무엇을 승인했나" 를 남기는 용도다.
    """
    return item.get("toolSummary") if isinstance(item.get("toolSummary"), dict) else {}
