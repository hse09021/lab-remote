"""승인 기록.

두 갈래로 나눈다.
  logs/Approval_log.csv   사람·웹 UI 용. 열은 web 의 ApprovalLogEntry 와 같다.
  logs/hook_events.jsonl  기계용 상세 기록. 우회 시도·훅 오류도 여기로.

CSV 는 **고쳐 쓰지 않고 행을 추가**한다. 동시 쓰기에 안전하고, git diff 가
깨끗하고, tail 로 볼 수 있다. 같은 호출의 여러 행은 `toolUseId` 로 묶고
**마지막 행**이 지금 상태다 (`group_rows`). 판 올림(`migrate_log`)만 예외로
파일을 고쳐 쓰고, 그때는 백업을 남긴다.

승인 결과는 다섯 단으로 마감한다:
  1 PreToolUse       ask -> 대기 파일 + "대기 중" 행
                     (+ 같은 세션의 이전 응답 대기 건 마감 · 안전망)
  2 PostToolUse      도구가 실제로 돌았다 -> 대기 해제 + "허용" 행
  3 UserPromptSubmit 새 프롬프트 -> 이전 턴 대기 건 전부 마감
  4 Stop             그 응답에서 안 돌아간 대기 건 -> "거부 또는 미응답"
  5 SessionEnd       Stop 이 못 돈 잔여분 정리

실측(2.1.317)에서 거절된 호출은 **PostToolUse 가 아예 안 온다.** 그리고 PC
터미널에서 거부하면 턴이 끊겨 **Stop 도 안 돈다.** 그래서 3번이 없으면 세션이
끝날 때까지 대기 뱃지가 거짓으로 켜져 있다 (실측 2026-11-04, 25분).

헤드리스에서 막은 승인 요청은 대기 건이 아니라 `data/requests/` 로 간다 —
닫아 줄 주체가 Claude 앱이 아니라 ②의 승인 대기열이기 때문이다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import csv
import fcntl
import io
import json
import os
import time
import shutil
from datetime import datetime

from . import registry

__all__ = [
    "COLUMNS",
    "now",
    "ensure_log",
    "append_row",
    "read_rows",
    "migrate_log",
    "log_event",
    "group_rows",
    "open_pending",
    "close_pending",
    "recall_closed",
    "list_pending",
    "close_stale",
    "open_request",
    "list_requests",
    "clear_request",
    "remember_denied",
    "recall_denied",
    "RESULT_NO_ANSWER",
]

#: web/src/api/types.ts 의 ApprovalLogEntry 와 같은 순서.
#: `toolUseId` 는 **한 호출의 여러 행을 묶는 키**다. 한 호출이 "대기 중" ->
#: "허용"(또는 "거부 또는 미응답") 으로 두 줄 이상 남으므로, 화면은 같은
#: toolUseId 의 **마지막 행**을 따라야 한다. 6열짜리 옛 파일도 읽힌다.
COLUMNS = ["time", "action", "request", "result", "resultPending", "handledBy", "toolUseId"]

#: 사용자가 거부했는지 그냥 응답이 없었는지는 훅이 구분할 수 없다.
RESULT_NO_ANSWER = "거부 또는 미응답"

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
    tool_use_id: str = "",
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
            summarize(tool_use_id),
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


def migrate_log(path: str) -> dict:
    """옛 6열 CSV 를 7열로. **한 번만 하는 이행이고 백업을 남긴다.**

    로그는 런타임에 append-only 다. 여기만 예외인 이유: 헤더가 6열인 파일에
    7열 행을 덧붙이면 `csv.DictReader` 가 남는 칸을 버려서, 같은 호출을 묶을
    키를 읽을 수 없게 된다. 원본은 `<파일>.v1.bak` 으로 복사해 둔다.
    """
    if not os.path.exists(path):
        return {"changed": False, "reason": "파일이 아직 없어요"}
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines()
    if not lines:
        return {"changed": False, "reason": "빈 파일이에요"}

    header = next(csv.reader([lines[0]]))
    if header == COLUMNS:
        return {"changed": False, "reason": "이미 지금 판이에요"}
    # 지금 열 목록의 **앞부분**과 같아야 안전하게 칸을 덧댈 수 있다
    if header != COLUMNS[: len(header)]:
        return {"changed": False, "reason": f"모르는 헤더예요: {header}"}
    missing = COLUMNS[len(header) :]

    backup = f"{path}.v1.bak"
    shutil.copy2(path, backup)

    out = [",".join(COLUMNS)]
    pad = "," * len(missing)
    out.extend(line + pad for line in lines[1:] if line.strip())
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    return {"changed": True, "backup": backup, "added": missing, "rows": len(out) - 1}


def read_rows(path: str) -> list[dict]:
    """CSV 를 dict 목록으로. **6열짜리 옛 파일도 읽힌다.**

    `toolUseId` 는 판 2 에서 생겼다. 로그는 append-only 라 이행 전 파일에는
    그 열이 없으니, 없으면 빈 값으로 채워 읽는 쪽이 한 가지만 다루게 한다.
    """
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = []
            for row in reader:
                row.pop(None, None)  # 헤더보다 칸이 많은 행 (이행 중)
                rows.append({key: row.get(key) or "" for key in COLUMNS})
            return rows
    except (FileNotFoundError, OSError):
        return []


def group_rows(rows: list[dict]) -> list[dict]:
    """한 호출을 한 줄로. 같은 `toolUseId` 의 **마지막 행**이 이긴다.

    백그라운드 서브에이전트의 승인창은 새 프롬프트 뒤까지 열려 있을 수 있어서,
    `거부 또는 미응답` 으로 닫은 뒤에 `허용` 이 늦게 붙는 일이 있다. 두 행 다
    남기고(append-only) 화면만 마지막을 따른다.

    `toolUseId` 가 빈 옛 행은 `action+request` 로 묶는다.
    """
    last: dict[str, dict] = {}
    for row in rows:
        key = row.get("toolUseId") or f"{row.get('action')}\x00{row.get('request')}"
        last[key] = row
    return sorted(last.values(), key=lambda r: str(r.get("time") or ""))


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


def _closed_file(name: str, tool_use_id: str) -> str:
    """닫은 대기 건을 옮겨 두는 곳.

    지우지 않고 보관하는 이유: 백그라운드 서브에이전트의 승인창은 새 프롬프트
    뒤까지 열려 있을 수 있고, 그걸 뒤늦게 승인하면 **닫은 뒤에** PostToolUse
    가 온다. 그때 "무슨 승인이었는지" 이름표를 되찾으려면 내용이 남아 있어야
    한다. `list_pending` 은 `.json` 파일만 보므로 이 하위 폴더는 무시된다.
    """
    base = os.path.join(registry.pending_dir(name), ".closed")
    return os.path.join(base, os.path.basename(_pending_file(name, tool_use_id)))


def close_pending(name: str, tool_use_id: str) -> dict | None:
    """대기 건을 닫고 내용을 돌려준다. 없으면 None (이미 닫혔다는 뜻).

    파일은 지우지 않고 `.closed/` 로 옮긴다 (위 `_closed_file` 참고).
    """
    path = _pending_file(name, tool_use_id)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    try:
        dst = _closed_file(name, tool_use_id)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(path, dst)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            return None
    return data


def recall_closed(name: str, tool_use_id: str) -> dict | None:
    """이미 닫힌 대기 건의 내용. 늦게 온 PostToolUse 가 이름표를 찾는 데 쓴다."""
    try:
        with open(_closed_file(name, tool_use_id), encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def list_pending(
    name: str,
    *,
    prompt_id: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    main_only: bool = False,
) -> list[dict]:
    """열려 있는 대기 건.

    `prompt_id` 로 거르는 게 기본이다 — Stop 은 **그 응답에서** 열린 것만
    마감해야 한다. 실측(2.1.317)에서 PreToolUse·Stop 둘 다 prompt_id 를
    들고 오는 걸 확인했다. prompt_id 가 없을 때만 session_id 로 떨어진다.

    `main_only` 메인 스레드 것만 (`agentId` 가 빈 것).
    `agent_id`   그 서브에이전트 것만.

    **왜 이 둘이 필요한가** (실측 2026-11-04 02:03)
    서브에이전트의 PreToolUse 는 **자기를 띄운 턴의 `prompt_id` 를 그대로**
    들고 온다. 그래서 메인 턴의 Stop 이 응답 단위로 닫을 때 아직 승인창이 열려
    있는 서브에이전트 대기 건까지 끌려 닫혔다. 4분 뒤 늦은 승인이 와서 `허용`
    로 고쳐졌지만, 그 사이 기록이 "거부" 로 보였다.
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
        mine = str(data.get("agentId") or "")
        if main_only and mine:
            continue
        if agent_id and mine != agent_id:
            continue
        out.append(data)
    return out


#: 자가 점검(`labremote hooks check`)이 남긴 것임을 알아보는 세션 이름
SELF_CHECK_SESSION = "labremote-check"


def close_stale(
    name: str,
    root: str,
    policy=None,
    *,
    session_id: str = "",
    keep_prompt_id: str = "",
    agent_id: str | None = None,
    main_only: bool = False,
    result: str = RESULT_NO_ANSWER,
    by: str = "sweep",
) -> list[dict]:
    """열린 대기 건을 닫고 CSV 에 마감 행을 남긴다.

    **왜 필요한가** — PC 터미널에서 승인을 거부하면 턴이 "Interrupted" 로
    끊겨 `Stop` 훅이 돌지 않는다. `Stop` 은 `prompt_id` 로 그 응답 것만
    닫으므로, 다음 턴의 `Stop` 도 이전 턴 대기 건을 지나친다. 실측에서는
    `SessionEnd` 가 25분 뒤 한꺼번에 쓸어낼 때까지 대기 뱃지가 거짓으로
    켜져 있었다(Approval_log.csv 34~37행).

    `keep_prompt_id` 를 주면 **그 응답 것만 남기고** 나머지를 닫는다
    (PreToolUse 안전망 · 지금 돌고 있는 턴의 대기 건을 건드리면 안 된다).
    `session_id` 가 비면 그 프로젝트의 모든 대기 건을 닫는다 (CLI sweep).
    `main_only`·`agent_id` 는 `list_pending` 과 같은 뜻이다 — 서브에이전트
    대기 건은 그 에이전트가 멈출 때 닫아야 한다.
    """
    from .hooks import messages as M  # handledBy 칸의 단일 출처

    pending = list_pending(
        name,
        session_id=session_id or None,
        agent_id=agent_id,
        main_only=main_only,
    )
    closed: list[dict] = []
    for item in pending:
        if keep_prompt_id and str(item.get("promptId") or "") == keep_prompt_id:
            continue
        tool_use_id = str(item.get("toolUseId") or "")
        got = close_pending(name, tool_use_id)
        if got is None:
            continue  # PostToolUse 가 먼저 닫았다 — 두 번 기록하지 않는다
        kind = result
        if str(got.get("sessionId") or "") == SELF_CHECK_SESSION:
            kind = "정리됨 · 자가 점검"
        append_row(
            log_path(root, policy),
            action=str(got.get("action") or ""),
            request=str(got.get("request") or ""),
            result=kind,
            handled_by=M.BY_APP,
            tool_use_id=tool_use_id,
        )
        closed.append({**got, "result": kind})

    if closed:
        log_event(
            event_path(root, policy),
            {
                "event": "sweep",
                "by": by,
                "sessionId": session_id,
                "keepPromptId": keep_prompt_id,
                "agentId": agent_id or "",
                "mainOnly": main_only,
                "closed": [c.get("toolUseId") for c in closed],
            },
        )
    return closed


# --- 승인 요청 (헤드리스) ----------------------------------------------------
# 대기 건(`pending/`)과 **다른 폴더**에 둔다. 대기 건은 Claude 앱의 답을
# 기다리는 것이라 Stop·sweep 이 닫지만, 헤드리스 요청을 닫아 줄 주체는
# ②의 승인 대기열이다. 같은 폴더에 두면 영원히 안 닫히는 대기 건이 된다.


def _requests_dir(name: str) -> str:
    return registry.requests_dir(name)


def open_request(name: str, request_id: str, info: dict) -> str:
    """헤드리스에서 막은 승인 요청을 남긴다. ②의 대기열이 읽어 간다."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in request_id)[:120]
    path = os.path.join(_requests_dir(name), f"{safe or 'unknown'}.json")
    registry.write_json(path, {"requestId": request_id, "openedAt": now(), **info})
    return path


def list_requests(name: str) -> list[dict]:
    out: list[dict] = []
    try:
        names = sorted(os.listdir(_requests_dir(name)))
    except (FileNotFoundError, OSError):
        return out
    for item in names:
        if not item.endswith(".json"):
            continue
        try:
            with open(os.path.join(_requests_dir(name), item), encoding="utf-8") as fh:
                out.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _request_name(request_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in request_id)[:120]
    return f"{safe or 'unknown'}.json"


def clear_request(name: str, request_id: str) -> bool:
    try:
        os.remove(os.path.join(_requests_dir(name), _request_name(request_id)))
        return True
    except OSError:
        return False


def close_request(name: str, request_id: str, *, result: str, grant_id: str = "") -> bool:
    """끝난 요청을 `.closed/` 로 옮기고 결과를 적는다.

    지우지 않고 옮기는 이유: 승인 1회가 **정말 그 호출 하나에만** 쓰였는지
    나중에 확인할 수 있어야 한다. 허가 쪽 `.consumed/` 와 쌍을 이룬다.

    **기록이 실패해도 판정은 그대로 나간다** — 훅 안에서 불린다.
    """
    source = os.path.join(_requests_dir(name), _request_name(request_id))
    try:
        with open(source, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    try:
        target = os.path.join(
            _requests_dir(name), ".closed", f"{int(time.time())}-{_request_name(request_id)}"
        )
        os.makedirs(os.path.dirname(target), exist_ok=True)
        registry.write_json(
            target, {**info, "closedAt": now(), "result": result, "grantId": grant_id}
        )
        os.remove(source)
        return True
    except OSError:
        return False


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
