"""예약 시계 — 서버 안의 asyncio 작업 하나. cron · systemd 타이머를 만들지 않는다.

15초마다 시각이 된 예약을 `schedules.tick()` 에 넘긴다. 서버가 꺼져 있으면
예약도 돌지 않는다(그 사이 지난 것은 "놓쳤어요").
"""

from __future__ import annotations

import asyncio
import time

from . import db, schedules

__all__ = ["start", "stop", "status", "INTERVAL_SEC"]

INTERVAL_SEC = 15
_task: asyncio.Task | None = None
_state = {"running": False, "lastTick": None, "error": ""}


async def _loop() -> None:
    _state["running"] = True
    try:
        while True:
            try:
                with db.open_db() as conn:
                    await schedules.tick(conn)
                _state["lastTick"] = time.time()
                _state["error"] = ""
            except Exception as exc:  # 한 번 실패해도 시계는 계속 돈다
                _state["error"] = f"{type(exc).__name__}: {exc}"[:300]
            await asyncio.sleep(INTERVAL_SEC)
    finally:
        _state["running"] = False


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(), name="labremote-scheduler")


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None


def status() -> dict:
    with db.open_db() as conn:
        items = schedules.list_all(conn)
    upcoming = [x for x in items if x["enabled"] and x["nextAt"]]
    nxt = upcoming[0] if upcoming else None
    return {
        **_state,
        "interval": INTERVAL_SEC,
        "next": {"name": nxt["name"], "at": nxt["nextAt"], "project": nxt["project"]} if nxt else None,
        "waiting": [x["name"] for x in items if x["waitingSince"]],
    }
