"""승인 기록.

두 갈래로 나눈다.
  logs/Approval_log.csv   사람·웹 UI 용. 열은 web 의 ApprovalLogEntry 와 같다.
  logs/hook_events.jsonl  기계용 상세 기록. 우회 시도·훅 오류도 여기로.

CSV 는 **고쳐 쓰지 않고 행을 추가**한다. 동시 쓰기에 안전하고, git diff 가
깨끗하고, tail 로 볼 수 있다. ③의 API 가 tool_use_id 로 묶어 UI 에 한 줄로
보여 준다.

승인 결과는 네 단으로 마감한다:
  1 PreToolUse  ask -> 대기 파일 + "대기 중" 행
  2 PostToolUse 도구가 실제로 돌았다 -> 대기 해제 + "허용" 행
  3 Stop        그 응답에서 안 돌아간 대기 건 -> "거부 또는 미응답"
  4 SessionEnd  Stop 이 못 돈 잔여분 정리

실측(2.1.317)에서 거절된 호출은 **PostToolUse 가 아예 안 온다.** 그래서 3번이
없으면 대기 뱃지가 영원히 켜져 있게 된다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import csv
import fcntl
import io
import json
import os
from datetime import datetime

from . import registry

__all__ = [
    "COLUMNS",
    "now",
    "ensure_log",
    "append_row",
    "log_event",
    "open_pending",
    "close_pending",
    "list_pending",
    "remember_denied",
    "recall_denied",
]

#: web/src/api/types.ts 의 ApprovalLogEntry 와 같은 순서
COLUMNS = ["time", "action", "request", "result", "resultPending", "handledBy"]

#: 한 레코드가 한 물리행이어야 한다. 줄바꿈은 바꾸고 길이는 자른다.
MAX_REQUEST = 200


def now() -> str:
    """ISO 8601 + 오프셋. UI 의 "11-02 21:43" 포맷은 ③의 API 가 담당한다."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def summarize(text: str) -> str:
    one_line = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "⏎").strip()
    if len(one_line) > MAX_REQUEST:
        one_line = one_line[: MAX_REQUEST - 1] + "…"
    return one_line


# --- CSV -------------------------------------------------------------------


def log_path(root: str, policy=None) -> str:
    rel = (getattr(policy, "data", {}) or {}).get("logPath") or "logs/Approval_log.csv"
    return os.path.join(root, rel)


def ensure_log(path: str) -> None:
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(COLUMNS)


def append_row(
    path: str,
    *,
    action: str,
    request: str,
    result: str,
    pending: bool = False,
    handled_by: str = "",
    when: str | None = None,
) -> None:
    """한 번의 write() 로 한 행을 덧붙인다. 여러 프로세스가 동시에 써도 안전."""
    ensure_log(path)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(
        [
            when or now(),
            summarize(action),
            summarize(request),
            summarize(result),
            "true" if pending else "false",
            summarize(handled_by),
        ]
    )
    line = buf.getvalue().encode("utf-8")

    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_rows(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except (FileNotFoundError, OSError):
        return []


# --- JSONL (기계용) ---------------------------------------------------------


def event_path(root: str, policy=None) -> str:
    rel = (getattr(policy, "data", {}) or {}).get("eventLogPath") or "logs/hook_events.jsonl"
    return os.path.join(root, rel)


def log_event(path: str, obj: dict) -> None:
    """어떤 일이 있어도 던지지 않는다. 기록 실패가 판정을 막으면 안 된다."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        line = json.dumps({"time": now(), **obj}, ensure_ascii=False) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except Exception:
        pass


# --- 대기 건 ---------------------------------------------------------------


def _pending_file(name: str, tool_use_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in tool_use_id)[:120]
    return os.path.join(registry.pending_dir(name), f"{safe or 'unknown'}.json")


def open_pending(name: str, tool_use_id: str, info: dict) -> str:
    """`ask` 를 내보낼 때 연다. 대시보드 "승인 대기 N건" 의 출처."""
    path = _pending_file(name, tool_use_id)
    registry.write_json(path, {"toolUseId": tool_use_id, "openedAt": now(), **info})
    return path


def close_pending(name: str, tool_use_id: str) -> dict | None:
    """대기 건을 지우고 내용을 돌려준다. 없으면 None (이미 닫혔다는 뜻)."""
    path = _pending_file(name, tool_use_id)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    try:
        os.remove(path)
    except OSError:
        return None
    return data


def list_pending(name: str, *, prompt_id: str | None = None, session_id: str | None = None) -> list[dict]:
    """열려 있는 대기 건.

    `prompt_id` 로 거르는 게 기본이다 — Stop 은 **그 응답에서** 열린 것만
    마감해야 한다. 실측(2.1.317)에서 PreToolUse·Stop 둘 다 prompt_id 를
    들고 오는 걸 확인했다. prompt_id 가 없을 때만 session_id 로 떨어진다.
    """
    folder = registry.pending_dir(name)
    out: list[dict] = []
    try:
        names = sorted(os.listdir(folder))
    except (FileNotFoundError, OSError):
        return out
    for item in names:
        if not item.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, item), encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if prompt_id and data.get("promptId") and data["promptId"] != prompt_id:
            continue
        if not prompt_id and session_id and data.get("sessionId") and data["sessionId"] != session_id:
            continue
        out.append(data)
    return out


# --- 우회 추적 --------------------------------------------------------------
# 실측: Edit 가 거절되자 Bash sed 로, 그것도 막히자 Write 로 같은 파일을
# 노렸다. 같은 세션에서 막힌 대상에 **다른 도구로** 다시 오면 표시한다.


def _denied_file(name: str, session_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)[:120]
    return os.path.join(registry.data_dir(), "denied", name, f"{safe or 'unknown'}.json")


def remember_denied(name: str, session_id: str, rel: str, tool: str, prompt_id: str = "") -> None:
    if not session_id or not rel:
        return
    path = _denied_file(name, session_id)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[rel] = {"tool": tool, "at": now(), "promptId": prompt_id}
    try:
        registry.write_json(path, data)
    except OSError:
        pass


def recall_denied(name: str, session_id: str, rel: str) -> dict | None:
    if not session_id or not rel:
        return None
    try:
        with open(_denied_file(name, session_id), encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    value = data.get(rel) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else None
