"""/api/inbox · /api/notify · /api/dashboard."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import alerts, config, dashboard, db, inbox, notifier

router = APIRouter()


class ReadBody(BaseModel):
    ids: list[int] | None = None  # 없으면 전부


class RulesBody(BaseModel):
    rules: dict[str, bool]


class QuietBody(BaseModel):
    on: bool
    start: str
    end: str


class WebhookBody(BaseModel):
    url: str


def _bad(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=400)


@router.get("/inbox")
def list_inbox(kind: str = "", unread: bool = False):
    if kind and kind not in inbox.KINDS:
        return _bad(f"모르는 알림 종류예요: {kind}")
    with db.open_db() as conn:
        return {
            "items": inbox.items(conn, kind=kind, unread=unread),
            "counts": inbox.counts(conn),
            "badge": inbox.badge(conn),
        }


@router.get("/inbox/badge")
def badge():
    with db.open_db() as conn:
        return {"badge": inbox.badge(conn)}


@router.post("/inbox/read")
def mark_read(body: ReadBody):
    with db.open_db() as conn:
        return {"changed": inbox.mark_read(conn, body.ids)}


@router.get("/notify")
def notify_settings():
    with db.open_db() as conn:
        settings = alerts.load()
        return {
            "webhook": alerts.webhook_status(conn),
            "rules": [
                {"key": k, "label": label, "sub": sub, "on": settings["rules"][k]} for k, label, sub in alerts.RULES
            ],
            "quiet": settings["quiet"],
        }


@router.put("/notify/rules")
def put_rules(body: RulesBody):
    try:
        alerts.save_rules(body.rules)
    except ValueError as exc:
        return _bad(str(exc))
    return notify_settings()


@router.put("/notify/quiet")
def put_quiet(body: QuietBody):
    try:
        alerts.save_quiet(body.on, body.start, body.end)
    except ValueError as exc:
        return _bad(str(exc))
    return notify_settings()


@router.put("/notify/webhook")
def put_webhook(body: WebhookBody):
    """주소를 받아 0600 파일에만 쓴다. 응답·오류에 주소를 싣지 않는다."""
    try:
        config.set_webhook(body.url)
    except ValueError as exc:
        return _bad(str(exc))
    return notify_settings()


@router.delete("/notify/webhook")
def delete_webhook():
    config.clear_webhook()
    return notify_settings()


@router.post("/notify/test")
def test_send():
    if not config.discord_webhook("test"):
        return _bad("웹훅 주소가 없어요. 먼저 주소를 넣어 주세요.")
    with db.open_db() as conn:
        result = notifier.send(
            conn,
            "test",
            subject="test",
            title="lab.remote 시험 알림이에요",
            body="이 알림이 보이면 Discord 연결이 잘 된 거예요.",
            cooldown_sec=0,
        )
    if result.get("sent"):
        return {"sent": True}
    status = result.get("status")
    return {"sent": False, "detail": f"보내지 못했어요{f' (HTTP {status})' if status else ''}"}


@router.get("/dashboard")
def overview():
    with db.open_db() as conn:
        return dashboard.overview(conn)
