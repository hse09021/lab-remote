"""필드명 실측용 덤프 훅.

판정은 **전혀 하지 않는다.** stdin 으로 들어온 JSON 을 그대로 파일에 받아 적고
아무 출력 없이 exit 0 한다. 설치된 Claude Code 버전의 실제 필드명
(`old_str` vs `old_string`, `file_text` vs `content`, Stop 에 `session_id` 가
오는지)을 눈으로 확인하는 게 목적이다.

여기서 모은 JSON 을 `server/tests/fixtures/hook_events/` 로 복사해 픽스처로 쓴다.
이 단계 전에 분류 로직을 확정하면 그 뒤가 전부 추측이 된다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from .. import registry

__all__ = ["dump_dir", "dump", "main"]


def dump_dir() -> str:
    return os.path.join(registry.data_dir(), "hook_dumps")


def _safe(value: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return keep[:60] or "unknown"


def dump(raw: str) -> str:
    """받은 원문을 그대로 저장하고 파일 경로를 돌려준다."""
    try:
        event = json.loads(raw)
    except Exception:
        event = None

    name_parts = [datetime.now().strftime("%Y%m%d-%H%M%S-%f")]
    if isinstance(event, dict):
        name_parts.append(_safe(str(event.get("hook_event_name") or "noevent")))
        if event.get("tool_name"):
            name_parts.append(_safe(str(event["tool_name"])))
    else:
        name_parts.append("unparsed")

    out = dump_dir()
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "-".join(name_parts) + ".json")

    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(event, dict):
            # 원문 그대로 + 보기 좋게. 키 순서를 바꾸지 않는다.
            json.dump(event, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        else:
            fh.write(raw)
    return path


def main() -> int:
    """어떤 일이 있어도 조용히 exit 0. 덤프가 작업을 막으면 안 된다."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    try:
        dump(raw)
    except Exception:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
