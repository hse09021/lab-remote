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

__all__ = [
    "MAX_ATTEMPTS",
    "sync",
    "sync_from_result",
    "pending",
    "approve",
    "deny",
    "too_many",
    "HOOK_REASON_LABEL",
]

#: 훅이 쓴 사유에 붙이는 꼬리표. `permission_denials` 에는 사유 칸이
#: **없다**(M2) 지만 사람은 "왜 막혔나" 를 알아야 한다. 그래서 훅의 사유를
#: 쓰되 **어디서 왔는지 밝힌다** — 내용·지문과 같은 무게로 보면 안 된다.
HOOK_REASON_LABEL = "훅 참고(검증 안 됨)"

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


def sync_from_result(conn, project: str, result, *, job_id: int | None = None,
                     session_id: str = "") -> list[dict]:
    """🔑 **승인 내용과 지문을 `permission_denials` 에서 만든다** (원칙 (나)).

    오케스트레이터가 **자기 자식 프로세스의 결과 JSON**에서 직접 받은 값이다.
    훅의 요청 파일을 거치면 믿어야 할 것이 하나 늘고, 훅이 파일을 못 썼을
    때(디스크·크래시) 무엇이 막혔는지 모른다.

    여기서만 할 수 있는 것: **지문을 직접 계산한다.** 요청 파일에는 본문을
    저장하지 않으므로(비밀이 섞일 수 있다) `approve` 가 지문을 다시 계산할 수
    없었고 훅이 계산한 값을 믿어야 했다. `permission_denials` 에는
    `tool_input` 전체가 있다.

    DB 에 넣는 것은 **지문 + 본문 없는 요약**이다. 원본 `tool_input` 은 넣지
    않는다 — `lab.db` 에 비밀이 쌓이면 안 된다.

    > ℹ️ 원래 계획은 *"훅의 요청 파일을 AI 가 꾸밀 수 있다"* 를 이유로 들었다.
    > **그 이유는 M1 으로 사라졌다** — `server/data/requests/` 는 샌드박스
    > 안에서 쓰기가 실패한다(M1b). 남은 이유는 위의 것들이다.
    """
    from ..agent import result as result_mod

    out = []
    for item in result_mod.denials(result):
        request_id = item["toolUseId"]
        if not request_id:
            # id 가 없으면 같은 denial 을 가를 수 없다. 건너뛰고 기록한다.
            E.add(
                conn, project, "승인",
                f"tool_use_id 가 없는 거절이 있었어요: {item['tool']}",
                tone="attention",
            )
            continue
        tool_input = item["toolInput"]
        # 🔑 **진짜 재시도만** 센다. 거울을 부를 때마다 올리면 한 번의 거절이
        # 여러 번이 된다(S9 e2e 가 잡았다). 재시도의 신호는 둘이다.
        #   - 다른 세션에서 같은 denial 이 또 왔다
        #   - 이미 결정된(승인·거절) 요청이 또 막혔다 — 재개 뒤 같은 호출
        before = AP.by_request(conn, project, request_id)
        retried = bool(
            before
            and (
                before.get("state") != "open"
                or (session_id and str(before.get("session_id") or "") != session_id)
            )
        )
        row = AP.open_request(
            conn,
            project,
            request_id,
            job_id=job_id,
            session_id=session_id,
            tool=item["tool"],
            # 🔑 **우리가 직접 계산한다.**
            fingerprint=grants.fingerprint(item["tool"], tool_input),
            loose_key=grants.loose_key(item["tool"], None),
            request=grants.describe_input(item["tool"], tool_input),
            source="denials",
            tool_summary=grants.summarize_input(tool_input),
        )
        if retried:
            AP.bump(conn, project, request_id)
            row = AP.by_request(conn, project, request_id) or row
        # 🔑 무한 반복 방지. 전에는 `too_many` 가 **아무 데서도 안 불렸다** —
        # "같은 요청이 반복되면 멈춘다" 는 기록이 거짓이었다(S9 e2e 가 잡았다).
        if too_many(row):
            _block_repeated(conn, project, row)
        out.append(row)
    return out


def _block_repeated(conn, project: str, row: dict) -> None:
    """같은 요청이 상한을 넘었다 — 루프를 멈추고 사람을 부른다."""
    from .. import notifier
    from ..store import loops as LP

    text = (
        f"같은 요청이 {row['attempts']}번 반복됐어요 (상한 {MAX_ATTEMPTS}): "
        f"{row.get('request')}"
    )
    E.add(conn, project, "승인", text, tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=project,
            subject=notifier.subject_of("repeat", row["request_id"]),
            title=f"같은 요청이 반복돼서 루프를 멈췄어요 · {project}",
            body=text,
            fields=[
                ("요청", str(row.get("request") or ""))[:1],
                ("횟수", f"{row['attempts']} / 상한 {MAX_ATTEMPTS}"),
                ("승인", f"labremote approvals approve {project} {row['request_id']}"),
                ("거절", f"labremote approvals deny {project} {row['request_id']}"),
            ][1:],
        )
    except Exception:
        pass
    LP.set_state(conn, project, "blocked", stop_reason=text)


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
    # 🔑 **DB 행이 승인의 근거다** (원칙 (나)). `source='denials'` 면 그
    # 지문은 오케스트레이터가 자기 자식의 결과 JSON 에서 직접 계산한 값이다.
    row = AP.by_request(conn, project, request_id)
    if not row:
        raise grants.GrantError(f"그런 승인 요청이 없어요: {request_id}")
    if row.get("state") != "open":
        raise grants.GrantError(f"이미 {row['state']} 예요: {request_id}")

    # 훅의 요청 파일은 **참고용**이다 — 행동 목록과 사유를 여기서만 알 수
    # 있다(`permission_denials` 에는 사유 칸이 없다 — M2).
    hint = next(
        (i for i in A.list_requests(project) if str(i.get("requestId") or "") == request_id),
        {},
    )
    actions = [a.get("action") for a in (hint.get("actions") or []) if a.get("action")]
    if not actions:
        actions = [str(row.get("action_key") or "")] if row.get("action_key") else []
    if not actions:
        raise _missing_actions(request_id)

    # 🔑 **승인해도 아무 일이 안 일어나는 행동은 승인하지 않는다.**
    #
    # S1 의 M3: Claude 의 Bash 로 `pip install` 을 돌리면 conda 환경이
    # 프로젝트 밖이라 샌드박스가 쓰기를 버린다. 허가를 내주면 **최악의
    # 조합**이 된다 — 사람이 승인했고 승인 로그에 `허용 · 1회용 승인` 이
    # 남고 설치는 안 된다. 기록이 거짓이 된다.
    if set(actions) & grants.NO_GRANT_ACTIONS:
        raise grants.GrantError(grants.NO_GRANT_REASON)

    fingerprint = str(row.get("fingerprint") or "")
    if not fingerprint:
        raise grants.GrantError(
            f"지문이 없어서 승인할 수 없어요: {request_id} · "
            "오케스트레이터가 결과 JSON 을 못 받았어요."
        )
    tool = str(row.get("tool") or hint.get("tool") or "")

    grant = grants.issue(
        project,
        tool=tool,
        # 본문은 안 가지고 있다. 지문은 아래 `fingerprint_override` 가 정한다.
        tool_input=_tool_input_of(hint) if hint else {},
        # 🔑 **DB 행의 지문**을 쓴다. `source='denials'` 면 우리가 계산한 것이다.
        fingerprint_override=fingerprint,
        action_key=str(row.get("action_key") or actions[0]),
        actions=actions or None,
        rel=row.get("rel") if row.get("rel") is not None else hint.get("rel"),
        request_id=request_id,
        session_id=str(row.get("session_id") or hint.get("sessionId") or ""),
        summary=str(row.get("request") or hint.get("request") or "")[:200],
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
        f"{hint.get('action') or row.get('action_key') or '요청'} 을 승인했어요 "
        f"· {grant['grantId']} · 출처 {row.get('source')}",
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


def _missing_actions(request_id: str):
    return grants.GrantError(
        f"무엇을 승인하는지 알 수 없어요: {request_id} · 훅의 요청 파일이 "
        "없고 DB 에도 행동 유형이 없어요."
    )


def _tool_input_of(item: dict) -> dict:
    """저장된 입력 요약. **지문 계산에는 쓰지 않는다.**

    요청 파일에는 본문을 저장하지 않는다(비밀이 섞일 수 있다). 지문은
    훅이 계산해 파일에 적어 둔 값을 그대로 쓴다 (`fingerprint_override`).
    여기 값은 허가 파일에 "무엇을 승인했나" 를 남기는 용도다.
    """
    return item.get("toolSummary") if isinstance(item.get("toolSummary"), dict) else {}
