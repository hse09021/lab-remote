"""알림 규칙 — 무엇을 Discord로 보낼지, 조용한 시간, 그리고 "Inbox에 넣고 보내기".

규칙은 데이터 폴더의 `notify.json`에 둔다(비밀이 아니라 0600 파일과 나눴다).
웹훅 주소는 `config`(discord.json, 0600)에만 있다.

조용한 시간에는 **답 필요와 실패만** 보낸다(목업 Inbox). 다른 알림은 Inbox에만
남고 `sent`에 "조용한 시간이라 안 보냄" 이라고 적힌다.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime

from . import config, inbox, notifier, registry

__all__ = [
    "RULES",
    "RULE_LABELS",
    "DEFAULT_RULES",
    "DEFAULT_QUIET",
    "load",
    "save_rules",
    "save_quiet",
    "in_quiet",
    "post",
    "webhook_status",
]

#: (키, 이름, 설명) — 목업 Inbox의 "Discord로 보낼 알림" 순서
RULES = (
    ("ask", "답이 필요할 때", "승인 요청 · 질문"),
    ("done", "실행이 끝났을 때", "종료 코드 0"),
    ("fail", "실행 실패 · 끊김", "종료 코드가 0이 아니거나 재부팅으로 끊김"),
    ("plan", "예약 실행이 시작되거나 대기할 때", "예약 시각에 시작했거나 GPU가 사용 중이라 대기를 시작했을 때"),
    ("pr", "PR 리뷰 · 변경 요청", "GitHub에서 가져와요"),
    ("merge", "머지", "main에 머지됐을 때"),
    ("sys", "시스템 경고", "VRAM · 디스크 · GPU 드라이버"),
)
RULE_LABELS = {k: name for k, name, _ in RULES}
DEFAULT_RULES = {"ask": True, "done": True, "fail": True, "plan": True, "pr": False, "merge": False, "sys": True}
DEFAULT_QUIET = {"on": True, "start": "00:00", "end": "07:00"}
#: 조용한 시간에도 보내는 규칙
URGENT = ("ask", "fail")

TIME_RE = re.compile(r"\A([01]\d|2[0-3]):([0-5]\d)\Z")

#: 규칙 → 임베드 색(notifier 종류)
DISCORD_KIND = {
    "ask": "approval",
    "done": "done",
    "fail": "failure",
    "plan": "start",
    "pr": "start",
    "merge": "done",
    "sys": "system",
}


def _path() -> str:
    return os.path.join(registry.data_dir(), "notify.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    rules = dict(DEFAULT_RULES)
    if isinstance(raw.get("rules"), dict):
        for k, v in raw["rules"].items():
            if k in rules and isinstance(v, bool):
                rules[k] = v
    quiet = dict(DEFAULT_QUIET)
    if isinstance(raw.get("quiet"), dict):
        q = raw["quiet"]
        if isinstance(q.get("on"), bool):
            quiet["on"] = q["on"]
        for key in ("start", "end"):
            if isinstance(q.get(key), str) and TIME_RE.match(q[key]):
                quiet[key] = q[key]
    return {"rules": rules, "quiet": quiet}


def _write(data: dict) -> dict:
    registry.write_json(_path(), {"version": 1, **data})
    return load()


def save_rules(changes: dict) -> dict:
    data = load()
    for k, v in (changes or {}).items():
        if k not in DEFAULT_RULES or not isinstance(v, bool):
            raise ValueError(f"알 수 없는 알림 규칙이에요: {k!r}")
        data["rules"][k] = v
    return _write(data)


def save_quiet(on: bool, start: str, end: str) -> dict:
    for value in (start, end):
        if not isinstance(value, str) or not TIME_RE.match(value):
            raise ValueError(f"시각은 HH:MM 형식으로 입력해 주세요: {value!r}")
    data = load()
    data["quiet"] = {"on": bool(on), "start": start, "end": end}
    return _write(data)


def in_quiet(quiet: dict, now: datetime | None = None) -> bool:
    if not quiet.get("on"):
        return False
    now = now or datetime.now()
    minutes = now.hour * 60 + now.minute
    sh, sm = map(int, quiet["start"].split(":"))
    eh, em = map(int, quiet["end"].split(":"))
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # 자정을 넘는 구간


def webhook_status(conn: sqlite3.Connection | None = None) -> dict:
    """화면용 — **가린 주소**만. 원문은 내보내지 않는다."""
    path = config.discord_path()
    url = config.discord_webhook()
    out = {
        "set": bool(url),
        "masked": config.masked_webhook(url) if url else "",
        "source": config.route_label() or "",
        "private": config.is_private(path) if os.path.exists(path) else None,
        "last": None,
    }
    if conn is not None:
        row = conn.execute(
            "SELECT state, last_at, first_at, http_status, error FROM notifications ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            out["last"] = {
                "state": row[0],
                "at": row[1] or row[2],
                "status": row[3],
                "error": row[4],
            }
    return out


def post(
    conn: sqlite3.Connection,
    kind: str,
    rule: str | None,
    title: str,
    *,
    where: str = "",
    body: str = "",
    project: str | None = None,
    ref: dict | None = None,
    act: bool = False,
    subject: str = "",
    read: bool = False,
    poster=None,
    now: datetime | None = None,
) -> dict:
    """Inbox에 넣고, 규칙이 허락하면 Discord로도 보낸다. **던지지 않는다.**

    `rule`이 None 이면 Inbox에만 넣는다(사람이 직접 한 일 등).
    """
    item_id = inbox.add(conn, kind, title, where=where, body=body, project=project, ref=ref, act=act, read=read)
    sent = ""
    result: dict = {}
    if rule:
        settings = load()
        if not settings["rules"].get(rule, False):
            sent = "보내지 않음 · 비활성화된 알림"
        elif in_quiet(settings["quiet"], now) and rule not in URGENT:
            sent = "보내지 않음 · 조용한 시간"
        elif not config.discord_webhook(DISCORD_KIND.get(rule, "")):
            sent = ""
        else:
            fields = [("위치", where)] if where else []
            # 바깥 주소(터널)를 적어 두었으면 그 화면으로 바로 가는 링크 — 답은 거기서 한다
            from . import remote

            link = remote.link_for(ref)
            if link:
                fields.append(("답하기" if rule == "ask" else "열기", link))
            result = notifier.send(
                conn,
                DISCORD_KIND.get(rule, "system"),
                project=project or "",
                subject=subject or f"{kind}:{title}",
                title=title,
                body=body,
                fields=fields or None,
                poster=poster,
            )
            if result.get("sent"):
                sent = "Discord 보냄"
            elif result.get("suppressed"):
                sent = "보내지 않음 · 중복 알림"
            else:
                # 사유에 주소가 섞이지 않게 상태 코드만 남긴다
                status = result.get("status")
                sent = f"Discord 실패{f' · {status}' if status else ''}"
        if sent:
            inbox.set_sent(conn, item_id, sent)
    from .events import bus

    bus.publish("inbox.new", {"id": item_id, "kind": kind})
    return {"id": item_id, "sent": sent, "result": {k: v for k, v in result.items() if k != "reason"}}
