"""로그 꼬리 — **증분으로** 읽는다.

학습 로그는 수십 MB가 된다. 5초마다 통째로 읽으면 디스크를 계속 때린다.
그래서 오프셋을 기억하고 **늘어난 만큼만** 읽는다.

파일이 줄어들었으면(새 실험이 로그를 다시 쓴 경우) 오프셋을 0으로 되돌린다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["TAIL_BYTES", "tail", "Follower"]

#: 한 번에 보여 줄 꼬리 크기. 화면의 로그 패널이 이 정도면 충분하다.
TAIL_BYTES = 64 * 1024


def tail(path: str, *, limit: int = TAIL_BYTES, lines: int | None = None) -> dict:
    """파일 끝에서 `limit` 바이트. 없으면 빈 결과 (던지지 않는다)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            raw = fh.read()
    except OSError as exc:
        return {"ok": False, "reason": str(exc), "text": "", "lines": [], "size": 0}
    text = raw.decode("utf-8", errors="replace")
    if size > limit:
        # 앞이 잘려서 첫 줄이 반쪽일 수 있다. 버린다.
        text = text.split("\n", 1)[-1]
    found = text.splitlines()
    if lines is not None:
        found = found[-lines:]
    return {"ok": True, "reason": "", "text": "\n".join(found), "lines": found, "size": size}


@dataclass
class Follower:
    """한 파일을 따라 읽는다. 오프셋을 기억한다."""

    path: str
    offset: int = 0
    #: 마지막으로 본 mtime. "진전 없음" 판정에 쓴다.
    mtime: float = 0.0
    carry: str = field(default="", repr=False)

    def read(self, *, limit: int = TAIL_BYTES) -> dict:
        """늘어난 부분만. `{"ok","lines","grew","size","mtime"}`.

        줄이 반쪽으로 끊겼으면 다음 호출까지 들고 있는다 — `\\n`이 아직 안
        온 줄을 넘기면 지표 파싱이 깨진다.
        """
        try:
            size = os.path.getsize(self.path)
            mtime = os.path.getmtime(self.path)
        except OSError as exc:
            return {"ok": False, "reason": str(exc), "lines": [], "grew": 0, "size": 0, "mtime": self.mtime}
        if size < self.offset:
            # 새로 쓰기 시작했다 (로그를 비웠다)
            self.offset = 0
            self.carry = ""
        if size == self.offset:
            self.mtime = mtime
            return {"ok": True, "reason": "", "lines": [], "grew": 0, "size": size, "mtime": mtime}
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                raw = fh.read(limit)
        except OSError as exc:  # pragma: no cover - 위에서 이미 열렸다
            return {"ok": False, "reason": str(exc), "lines": [], "grew": 0, "size": size, "mtime": mtime}
        grew = len(raw)
        self.offset += grew
        text = self.carry + raw.decode("utf-8", errors="replace")
        if not text.endswith("\n"):
            text, _, self.carry = text.rpartition("\n")
        else:
            self.carry = ""
        self.mtime = mtime
        return {
            "ok": True,
            "reason": "",
            "lines": text.splitlines(),
            "grew": grew,
            "size": size,
            "mtime": mtime,
        }

    def stalled_sec(self, now: float) -> float:
        """로그가 안 자란 시간. "진전 없음" 판정에 쓴다."""
        return max(0.0, now - self.mtime) if self.mtime else 0.0
