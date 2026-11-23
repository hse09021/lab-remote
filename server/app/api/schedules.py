"""/api/schedules — 예약 (사람이 시각으로 건 것만)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, schedules

router = APIRouter()


def _bad(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status)


@router.get("/schedules")
def list_schedules():
    with db.open_db() as conn:
        return {"schedules": schedules.list_all(conn)}


@router.post("/schedules")
def create(body: dict):
    with db.open_db() as conn:
        try:
            return schedules.create(conn, body)
        except schedules.ScheduleError as exc:
            return _bad(exc)


@router.put("/schedules/{sid}")
def update(sid: int, body: dict):
    with db.open_db() as conn:
        try:
            return schedules.update(conn, sid, body)
        except schedules.ScheduleError as exc:
            return _bad(exc)


@router.delete("/schedules/{sid}")
def delete(sid: int):
    with db.open_db() as conn:
        schedules.delete(conn, sid)
    return {"ok": True}


@router.get("/schedules/clock")
def clock():
    """예약 시계 상태 — System 화면용."""
    from .. import scheduler

    return scheduler.status()
