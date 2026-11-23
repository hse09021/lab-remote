"""서버 → 화면 실시간 이벤트 (SSE 하나, PLAN 4.1).

세션 메시지 · 세션 상태 · 승인 요청·결과 · 알림을 같은 통로로 보낸다. 화면은
`GET /api/events` 를 열어 두고, 받은 이벤트로 해당 쿼리를 다시 읽거나 채팅에
이어 붙인다.

`publish()` 는 어느 스레드에서 불러도 된다(감시 스레드·스레드풀 엔드포인트).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading

__all__ = ["bus", "EventBus"]


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def _deliver(self, item: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:  # 화면이 못 따라오면 그 화면만 버린다
                pass

    def publish(self, kind: str, data: dict | None = None) -> None:
        item = {"id": next(self._ids), "kind": kind, "data": data or {}}
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(item)
        else:
            loop.call_soon_threadsafe(self._deliver, item)

    @staticmethod
    def format(item: dict) -> str:
        return f"id: {item['id']}\nevent: {item['kind']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"


bus = EventBus()
