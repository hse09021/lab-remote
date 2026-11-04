"""사용량 한도 — **기다리기만 한다. 절대 추가 결제 없음.**

결정(사용자): 원인을 구분하지 않고 백오프로 시작한다.

1. **실패할 때마다 원문을 보관한다** — 나중에 실제로 한도에 걸리면 그 문구로
   "한도 대기" 를 구분한다. 패턴은 코드에 박지 않고
   `~/.config/labremote/usage_patterns.json` 에 두고 **비운 채로** 시작한다.
2. **루프를 멈추지 않는다.** 긴 간격(기본 30분)으로 계속 다시 해서 풀리면
   스스로 이어 간다. 상한 없이 반복한다.
3. **알림은 한 번만.** 대기에 들어갈 때 1회.
4. **몇 시간 넘게 계속 실패하면 다시 알린다** — 한도가 아니라 인증 만료 같은
   다른 오류일 수 있다 (기본 4시간).
5. spec V 대로 **AI 의 의사결정만** 멈춘다. 돌고 있는 학습은 건드리지 않고
   큐의 `train` 작업도 계속 돈다.

구조적 보장은 `agent/launch.py` 에 있다 — `ANTHROPIC_API_KEY` 를 지워서
구독으로만 돈다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import config as config_mod
from ..agent import result as result_mod
from ..store import usage as U

__all__ = ["RETRY_SEC", "RENOTIFY_SEC", "AI_KINDS", "record_failure", "wait_state", "resumed"]

#: 다시 해 보는 간격 (기본 30분)
RETRY_SEC = 30 * 60

#: 이만큼 지나도 계속 실패하면 **한도가 아닐 수 있다** (기본 4시간)
RENOTIFY_SEC = 4 * 60 * 60

#: 한도일 때 멈추는 작업. 학습(`train`)은 **계속 돈다** (spec V).
AI_KINDS = ("plan", "review", "resume", "journal_fix")


def record_failure(conn, project: str, parsed, *, now: datetime | None = None) -> dict:
    """실패 한 건을 원문 그대로 보관하고, 한도로 보이는지 판정한다.

    `{"usageId", "looksLimited", "pattern", "resumeAt"}`.
    """
    now = now or datetime.now().astimezone()
    patterns = config_mod.usage_patterns()
    pattern = result_mod.looks_like_usage_limit(parsed, patterns)
    resume_at = (now + timedelta(seconds=RETRY_SEC)).isoformat(timespec="seconds")
    usage_id = U.record(
        conn,
        project=project,
        raw=str(parsed.get("raw") or "")[:100000],
        exit_code=parsed.get("exitCode"),
        detected_by="pattern" if pattern else "backoff",
        resume_at=resume_at,
    )
    return {
        "usageId": usage_id,
        "looksLimited": bool(pattern),
        "pattern": pattern,
        "resumeAt": resume_at,
    }


def wait_state(conn, project: str, *, now: datetime | None = None) -> dict:
    """지금 기다리는 중인가. 알림을 보내야 하는가.

    `{"waiting", "ready", "notify", "renotify", "sinceSec", "row"}`
    """
    now = now or datetime.now().astimezone()
    row = U.open_wait(conn, project)
    if row is None:
        return {"waiting": False, "ready": True, "notify": False, "renotify": False, "row": None}

    started = _when(row.get("at"), now)
    since = max(0.0, (now - started).total_seconds())
    resume_at = _when(row.get("resume_at"), now)
    return {
        "waiting": True,
        # 다시 해 볼 때가 됐나
        "ready": now >= resume_at,
        # 대기에 들어갈 때 **한 번만**
        "notify": not row.get("notified_at"),
        # 오래 막혀 있으면 한도가 아닐 수 있다
        "renotify": since >= RENOTIFY_SEC,
        "sinceSec": since,
        "row": row,
    }


def resumed(conn, project: str) -> dict | None:
    """풀렸다. 대기를 닫는다."""
    row = U.open_wait(conn, project)
    if row is None:
        return None
    return U.mark_resumed(conn, row["id"])


def _when(value, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback
