"""🔎 결과 JSON 의 `permission_denials` **원본 보관** — 승인하는 사람이 실행될 것을 끝까지 보게.

## 왜 이 파일이 생겼나 (2026-11-05, 9단계 1번)

`labremote approvals show` 가 명령을 **200자에서 잘라** 보여 줬고, 잘림은
저장할 때 일어나서 **전문이 아예 사라졌다.** 그래서 사람은 이렇게 생긴 걸
보고 승인해야 했다.

    for f in state/State.yaml … experiments/EXP-002/* state/Install_result.json; do echo "=== $f"; cat "$f"; done; ls; g…

무해한 앞부분 뒤에 무엇이 붙어 있는지 알 수 없다. **승인은 본 것에만 할 수
있어야 한다** — 못 본 뒷부분을 함께 허용하는 건 승인이 아니다.

## 원칙을 버린 게 아니라 날카롭게 한 것

S4 의 원칙은 *"본문은 저장하지 않는다 — `server/data` 는 gitignore 지만 비밀이
섞일 수 있다"* 였다. 그 판단은 **파일 본문**(`Write.content` ·
`Edit.old_string`)에 대해서는 지금도 맞다 — 사람은 본문을 안 봐도 "어느
파일에 쓰는가" 로 결정할 수 있고, 거기엔 `.env` 를 그대로 복사한 내용이 들어올
수 있다.

그런데 **Bash 명령은 본문이 아니라 결정의 대상 자체**다. 경로·URL 도 같다.
그래서 가른다.

| 칸 | `lab.db` | 이 파일 (0600) | 왜 |
|---|---|---|---|
| `command` · `file_path` · `url` … | 짧은 줄 | **전문** | 승인하는 대상이다 |
| `content` · `old_string` … (파일 본문) | 길이 + 해시 **만** | **전문** (상한까지) | 아래 |

처음엔 본문을 아무 데도 남기지 않았다. 그런데 `hparam` 승인 화면이 이렇게
나왔다.

    행동      hparam
    content   파일 본문 532자 · sha256 423adb…  (본문은 일부러 안 남겨요)

**하이퍼파라미터 값을 안 보고 하이퍼파라미터 변경을 승인**하게 된다. `code`
승인은 더 심하다 — 들어갈 코드를 안 보고 코드를 허용하는 것이다. 명령에 대해
방금 고친 것과 **같은 구멍**이 한 단계 아래에 있었다.

그래서 가른 기준을 바꾼다. 기준은 "본문인가" 가 아니라 **"어디에 쌓이나"** 다.

| 자리 | 성질 | 본문 |
|---|---|---|
| `lab.db` | 오래 남는 기록. 승인 이력·지문·통계 | **안 넣는다** (원래 원칙 그대로) |
| `server/data/denials/*.json` | 승인 한 건의 증거. 0600 · 샌드박스 차단 · gitignore · `prune` 으로 최근 것만 | **넣는다** |

`show` 는 사람이 **승인하려고 일부러 들여다보는** 자리다. 거기서 가리면
승인이 추측이 된다.

## 왜 여기에 두나

| 자리 | 근거 |
|---|---|
| `server/data/denials/<프로젝트>/<세션>.json` | 샌드박스 안에서 **쓰기도 읽기도 실패**한다(M1b 실측). AI 가 위조도 열람도 못 한다 |
| 권한 `0600` · 폴더 `0700` | 명령에 토큰이 섞여 있을 수 있다 |
| 출처 | 오케스트레이터가 **자기 자식의 결과 JSON** 에서 받은 것 (원칙 (나)). 훅의 요청 파일이 아니다 |
| gitignore | `server/data` 는 저장소에 올라가지 않는다 |

DB(`approvals.request`·`tool_summary`)는 **목록용 짧은 줄**로 남는다. 전문은
항상 이 파일에서 읽는다.

## 한계

- **이 파일이 생기기 전의 요청은 전문을 되살릴 수 없다.** `find()` 가 `None` 을
  돌려주고 `show` 가 그 사실을 말한다 — 조용히 짧은 줄을 보여 주지 않는다.
- 세션 파일은 `prune()` 로 프로젝트당 최근 것만 남긴다.
"""

from __future__ import annotations

import json
import os
import re

from . import registry

__all__ = [
    "DIR_NAME",
    "KEEP_SESSIONS",
    "project_dir",
    "session_path",
    "safe_input",
    "BODY_MAX",
    "store",
    "find",
    "prune",
    "segments_of",
]

#: `server/data/` 아래. 샌드박스에서 쓰기·읽기가 다 실패한다 (M1b).
DIR_NAME = "denials"

#: 프로젝트당 남겨 둘 세션 파일 수.
KEEP_SESSIONS = 50

#: 전문을 남기지 **않는** 칸. `grants._BODY_KEYS` 와 같은 뜻이다 — 파일 본문은
#: 결정의 대상이 아니고 비밀이 들어올 자리다.
BODY_KEYS = ("content", "old_string", "new_string", "file_text", "contents", "prompt")

#: 본문을 남길 상한. 넘으면 앞부분만 두고 `truncated` 를 켠다 — **조용히
#: 자르지 않는다.** 해시는 항상 전체에 대해 계산하므로 "같은 내용인가" 는
#: 상한과 무관하게 알 수 있다.
BODY_MAX = 200_000

#: 세션 ID 로 받아들일 꼴. 경로 조작을 막는다 (UUID 를 기대한다).
_SESSION_RE = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")


def project_dir(project: str) -> str:
    """`<data>/denials/<프로젝트>/`. 이름은 `registry.valid_name` 으로 거른다
    (`audit.audit_path` 와 같은 방식 — 경로 조작을 막는다)."""
    return os.path.join(
        registry.data_dir(), DIR_NAME, registry.valid_name(project)
    )


def session_path(project: str, session_id: str) -> str:
    if not _SESSION_RE.match(str(session_id or "")):
        raise ValueError(f"세션 ID 로 쓸 수 없는 값이에요: {session_id!r}")
    return os.path.join(project_dir(project), f"{session_id}.json")


def _hash(text: str) -> dict:
    import hashlib

    return {
        "len": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def safe_input(tool_input) -> dict:
    """저장할 `tool_input`. 명령·경로는 그대로, **파일 본문은 표시를 달아서**.

    본문은 `{"body": True, "len", "sha256", "text", "truncated"}` 꼴이다 —
    `show` 가 "이건 파일 본문이다" 를 말하면서 값을 보여 줄 수 있게.
    """
    if not isinstance(tool_input, dict):
        return {}
    out: dict = {}
    for key in sorted(tool_input):
        value = tool_input[key]
        if key in BODY_KEYS and isinstance(value, str):
            kept = value[:BODY_MAX]
            out[key] = {
                "body": True,
                **_hash(value),
                "text": kept,
                "truncated": len(value) > BODY_MAX,
            }
            continue
        out[key] = value
    return out


def _normalize(item) -> dict:
    """결과 JSON 의 denial 한 건을 우리 꼴로. 칸 이름이 판마다 흔들린다(M2)."""
    if not isinstance(item, dict):
        return {}
    request_id = (
        item.get("tool_use_id") or item.get("toolUseId") or item.get("id") or ""
    )
    tool = item.get("tool_name") or item.get("toolName") or item.get("tool") or ""
    raw = item.get("tool_input")
    if raw is None:
        raw = item.get("toolInput")
    return {
        "requestId": str(request_id or ""),
        "tool": str(tool or ""),
        "input": safe_input(raw),
        # 결과 JSON 에 사유 칸이 없다(M2). 있으면 받아 둔다.
        "reason": str(item.get("reason") or item.get("message") or ""),
    }


def store(project: str, session_id: str, raw_denials, *, at: str = "") -> dict:
    """세션 하나의 denial 전부를 파일로. **덮어쓴다** (세션당 하나다)."""
    from datetime import datetime

    items = [_normalize(d) for d in (raw_denials or [])]
    items = [d for d in items if d.get("requestId")]
    payload = {
        "version": 1,
        "project": project,
        "sessionId": str(session_id or ""),
        "at": at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "denials": items,
    }
    folder = project_dir(project)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    path = session_path(project, session_id)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return {"ok": True, "path": path, "count": len(items)}


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _session_files(project: str) -> list[str]:
    folder = project_dir(project)
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".json")]
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names]
    # 새 것부터. 같은 요청이 여러 세션에 있으면 최근 것이 맞다.
    paths.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
    return paths


def find(project: str, request_id: str, *, session_id: str = "") -> dict | None:
    """그 요청의 **전문**. 없으면 `None` — 부르는 쪽이 그 사실을 말해야 한다."""
    wanted = str(request_id or "")
    if not wanted:
        return None
    paths = []
    if session_id:
        try:
            one = session_path(project, session_id)
        except ValueError:
            one = ""
        if one and os.path.exists(one):
            paths.append(one)
    paths += [p for p in _session_files(project) if p not in paths]

    for path in paths:
        data = _read(path)
        for item in data.get("denials") or []:
            if isinstance(item, dict) and str(item.get("requestId") or "") == wanted:
                return {
                    **item,
                    "sessionId": data.get("sessionId"),
                    "at": data.get("at"),
                    "path": path,
                }
    return None


def prune(project: str, *, keep: int = KEEP_SESSIONS) -> int:
    """오래된 세션 파일을 지운다. 지운 개수."""
    paths = _session_files(project)
    gone = 0
    for path in paths[max(0, int(keep)):]:
        try:
            os.remove(path)
            gone += 1
        except OSError:
            pass
    return gone


def segments_of(tool: str, tool_input) -> list[str]:
    """Bash 명령을 **훅이 본 것과 같은 방식으로** 조각낸다.

    판정은 조각별로 돈다(`;`·`&&`·`||`·`|`). 사람도 같은 조각을 봐야 "앞은
    무해하고 뒤가 위험한" 꼴을 알아볼 수 있다.
    """
    if str(tool) != "Bash" or not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return []
    from .hooks import bashparse

    try:
        return bashparse.split_segments(command)
    except Exception:
        return [command]
