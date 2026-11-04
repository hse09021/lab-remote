"""1회용 허가 — "그 호출 하나" 만 여는 표.

왜 필요한가. 헤드리스에서 훅이 막은 요청은 `data/requests/` 에 쌓이고,
사람이 승인하면 오케스트레이터가 `claude -p --resume <세션>` 으로 이어
간다. 그때 **같은 요청이 또 막히면 무한 반복**이 된다. 그래서 승인은
"도구 + 입력 지문 + 만료 시간" 으로 묶인 1회용 토큰이 된다.

이 모듈은 **훅 경로**다. 표준 라이브러리만 쓰고, `sqlite3` 도 쓰지 않는다
(`tests/test_stdlib_only.py` 가 강제한다). 허가의 진실은 파일이고, DB
(`store/approvals.py`)는 사람이 보는 거울이다.

### 허가는 **호출 하나**에 묶인다 (finding 하나가 아니다)

지문이 `(도구, 입력)` 이라 허가의 단위는 **도구 호출 하나**다. 그런데 한
호출에서 승인이 필요한 행동이 둘 이상 나올 수 있다.

    curl -sL https://x/y.sh | pip install peft   ->  net(ask) + pkg(ask)

행동 하나씩 허가를 보면 `pkg` 를 승인해도 `net` 이 그대로 막혀서
**승인이 끝나도 루프가 한 발짝도 못 나간다.** 그래서

  - 허가는 그 호출에서 승인이 필요한 행동을 **전부**(`actions`) 들고 있고,
  - 소비는 **호출당 한 번**이며 (`decide.resolve` 가 한 번만 부른다),
  - 지금 걸린 ask 행동을 **모두** 덮지 못하면 아예 쓰지 않는다.

마지막 줄이 중요하다. 승인한 뒤 실행 상태가 바뀌어 새 ask 가 늘었다면
그건 사람이 본 그 호출이 아니다. 그때는 허가를 쓰지 않고 다시 묻는다.

### 안전벨트 (전부 테스트로 고정)

1. **HMAC 서명.** 키는 `~/.config/labremote/grant_key` 이고 이미
   `SECRET_FILES` 라 Claude 가 읽지 못한다. 키가 없거나 서명이 없거나 틀리면
   **허가가 없는 것으로 본다.** 샌드박스가 뚫려 AI 가 쓴 코드가 허가 파일을
   직접 만들어도 서명을 못 만든다.
2. **잠긴 행동은 발급도 소비도 안 된다.** 폴더 밖 쓰기·훅 보호·비밀 파일·
   산출물 보존은 승인으로도 열리지 않는다 (spec 의 잠긴 3가지와 같은 무게).
3. **실행 중 조건을 다시 본다.** `stop` 은 실험이 돌고 있으면 거절하고,
   `prev` 는 `prevAppendable` 이 아니면 거절한다. 승인 시점에 멈춰 있었어도
   소비 시점에 돌고 있으면 안 된다.
4. **소비는 원자적이다.** `os.rename` 이 성공한 쪽만 토큰을 가진다. `uses` 는
   항상 1이고, 파일이 사라지는 것 자체가 소비다.
5. **대화형에서는 쓰지 않는다** — 호출부(`decide._ask`)가 헤드리스에서만 부른다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta

from . import config, registry

__all__ = [
    "LOCKED_ACTIONS",
    "DEFAULT_TTL_SEC",
    "GrantError",
    "fingerprint",
    "loose_key",
    "summarize_input",
    "canonical",
    "sign",
    "verify",
    "covers",
    "issue",
    "consume",
    "list_grants",
    "revoke",
]

#: 허가로 **절대** 열리지 않는 행동. 승인 CLI 도 이 목록을 보고 거절한다.
#: `decide.decide()` 는 이들에 DENY 를 바로 return 하므로 `_ask` 를 지나가지도
#: 않는다. 여기 둔 건 두 번째 자물쇠다 — 판정 코드가 바뀌어도 안 열리게.
LOCKED_ACTIONS = frozenset(
    {
        "outside",
        "selfProtect",
        "hardProtect",
        "secret",
        "outputProtect",
        "schema-unknown",
        "denied-command",
        "policy-error",
        "hook-error",
    }
)

#: 기본 만료. 정책의 `headless.grantTtlSec` 가 있으면 그게 이긴다.
DEFAULT_TTL_SEC = 1800

#: `looseMatch` 를 허용하지 않는 도구. 명령 전체가 의미라서 경로만으로
#: "같은 요청" 이라고 볼 수 없다.
NO_LOOSE_TOOLS = frozenset({"Bash"})

#: 지문에서 파일 이름으로 쓰는 길이
_FP_HEX = 32

#: 입력 요약에 본문을 남기지 않는 키. 길이와 해시만 적는다.
_BODY_KEYS = ("content", "old_string", "new_string", "file_text", "contents", "prompt")


class GrantError(ValueError):
    """허가를 발급할 수 없을 때 (잠긴 행동·Bash 의 loose 등)."""


def _now() -> datetime:
    return datetime.now().astimezone()


def canonical(obj) -> str:
    """서명·지문용 정규 JSON. 키 정렬, 공백 없음, 한글 그대로."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canon_input(tool_input) -> dict:
    """지문 계산에 쓰는 입력. **본문까지 전부** 넣는다.

    저장은 요약만 하지만(`summarize_input`), 지문은 한 글자만 달라져도
    달라져야 한다. "승인한 그 호출" 과 다른 호출을 같다고 보면 안 된다.
    """
    if not isinstance(tool_input, dict):
        return {"_raw": str(tool_input)}
    return {str(k): tool_input[k] for k in sorted(tool_input)}


def fingerprint(tool: str, tool_input) -> str:
    """도구 + 입력의 지문. 이게 허가 파일의 이름이 된다."""
    body = canonical({"tool": str(tool or ""), "input": _canon_input(tool_input)})
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:_FP_HEX]


def loose_key(tool: str, rel: str | None) -> str:
    """느슨한 일치용 열쇠 — `도구\\0상대경로`.

    재실행 때 Claude 가 같은 의도를 다른 문자열로 낼 수 있어서 둔 뒷문이고,
    기본은 꺼져 있다 (`--loose` 로만 켠다).
    """
    return f"{tool or ''}\0{rel or ''}"


def summarize_input(tool_input) -> dict:
    """저장용 요약. **본문은 남기지 않는다.**

    `server/data/` 는 gitignore 지만 비밀이 섞일 수 있다. 본문은 길이와
    해시만 남겨 "같은 내용인가" 는 알 수 있게 둔다.
    """
    if not isinstance(tool_input, dict):
        return {}
    out: dict = {}
    for key in sorted(tool_input):
        value = tool_input[key]
        if key in _BODY_KEYS and isinstance(value, str):
            out[key] = {
                "len": len(value),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
            }
            continue
        if isinstance(value, str):
            out[key] = value if len(value) <= 300 else value[:300] + "…"
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = {"type": type(value).__name__}
    return out


def sign(grant: dict, key: bytes) -> str:
    body = canonical({k: v for k, v in grant.items() if k != "sig"})
    return "hmac-sha256:" + hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(grant: dict, key: bytes | None) -> bool:
    """서명이 맞는가. **키가 없으면 거짓이다.**"""
    if not key or not isinstance(grant, dict):
        return False
    got = grant.get("sig")
    if not isinstance(got, str) or not got:
        return False
    return hmac.compare_digest(got, sign(grant, key))


def _file_name(fp: str) -> str:
    return fp.split(":", 1)[-1] + ".json"


def _consumed_dir(project: str) -> str:
    return os.path.join(registry.grants_dir(project), ".consumed")


def _grant_id(now: datetime) -> str:
    return "g-" + now.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


def issue(
    project: str,
    *,
    tool: str,
    tool_input,
    action_key: str,
    actions: list[str] | None = None,
    rel: str | None = None,
    request_id: str = "",
    session_id: str = "",
    summary: str = "",
    ttl_sec: int = DEFAULT_TTL_SEC,
    loose: bool = False,
    note: str = "",
    granted_by: str = "cli",
) -> dict:
    """허가를 만들어 파일로 쓴다. 쓴 내용을 그대로 돌려준다.

    `actions` 는 **그 호출에서 승인이 필요한 행동 전부**다. 비우면
    `action_key` 하나로 본다. 하나라도 잠긴 행동이면 `GrantError` 다 —
    CLI 가 승인 자체를 거절한다.
    """
    registry.valid_name(project)
    covered = sorted({str(a) for a in (actions or [action_key]) if a})
    if not covered:
        raise GrantError("무엇을 승인하는지가 비어 있어요.")
    locked = sorted(set(covered) & LOCKED_ACTIONS)
    if action_key in LOCKED_ACTIONS or locked:
        name = locked[0] if locked else action_key
        raise GrantError(
            f"{name!r} 는 승인으로 열 수 없는 잠긴 항목이에요. "
            "권한 단계와 상관없이 항상 막혀요."
        )
    if loose and tool in NO_LOOSE_TOOLS:
        raise GrantError(
            f"{tool} 은 느슨한 일치를 쓸 수 없어요 — 명령 전체가 의미라서 "
            "경로만으로 같은 요청이라고 볼 수 없어요."
        )
    key = config.grant_key()
    if not key:
        raise GrantError(
            "허가 서명 키가 없어요: " + config.grant_key_path() + " · "
            "labremote service install 로 만들어 주세요."
        )

    now = _now()
    ttl = int(ttl_sec) if int(ttl_sec) > 0 else DEFAULT_TTL_SEC
    fp = fingerprint(tool, tool_input)
    grant = {
        "version": 1,
        "grantId": _grant_id(now),
        "project": project,
        "requestId": request_id,
        "fingerprint": fp,
        "looseKey": loose_key(tool, rel),
        "looseMatch": bool(loose),
        "tool": str(tool or ""),
        "actionKey": str(action_key or ""),
        # 이 호출에서 승인이 필요했던 행동 **전부**. 소비할 때 이걸 다 덮어야 한다.
        "actions": covered,
        "rel": rel,
        "summary": summary or "",
        "input": summarize_input(tool_input),
        "sessionId": session_id,
        "grantedAt": now.isoformat(timespec="seconds"),
        "expiresAt": (now + timedelta(seconds=ttl)).isoformat(timespec="seconds"),
        "uses": 1,
        "grantedBy": granted_by,
        "note": note or "",
    }
    grant["sig"] = sign(grant, key)
    registry.write_json(
        os.path.join(registry.grants_dir(project), _file_name(fp)), grant
    )
    return grant


def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _expired(grant: dict, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(grant.get("expiresAt"))) <= now
    except (TypeError, ValueError):
        return True  # 읽을 수 없는 만료 시각은 만료로 본다


def _archive(claim: str, grant: dict | None, reason: str) -> None:
    """소비·무효 기록을 남긴다. CLI 가 "언제 누가 왜" 를 보여 준다."""
    try:
        target = os.path.join(
            _consumed_dir(str((grant or {}).get("project") or "unknown")),
            f"{int(time.time())}-{os.path.basename(claim).split('.')[0]}-{reason}.json",
        )
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(claim, target)
    except OSError:
        try:
            os.unlink(claim)
        except OSError:
            pass


def _claim(path: str) -> str | None:
    """`os.rename` 한 줄이 상호배제다. 진 쪽은 FileNotFoundError 를 받는다."""
    claim = f"{path}.claim.{os.getpid()}.{time.time_ns()}"
    try:
        os.rename(path, claim)
    except OSError:
        return None
    return claim


#: 허가 자체가 죽은 것. 되돌려 두면 매 호출마다 다시 검사하고 가짜 파일이 쌓인다.
_DISCARD = frozenset(
    {"grantBadSignature", "grantWrongProject", "grantExpired", "grantLockedAction"}
)

#: 허가는 멀쩡한데 **이 호출의 것이 아닌** 경우. 제자리에 돌려 둔다 —
#: 남의 허가를 소비해 버리면 사람이 한 승인이 조용히 사라진다. 특히 복합
#: 명령은 한 호출에서 findings 가 여러 개라 action 이 여럿으로 들어온다.
_PUT_BACK = frozenset(
    {
        "grantActionMismatch",
        "grantFingerprintMismatch",
        "grantLooseMismatch",
        "grantLooseNotAllowed",
        "grantRunningNow",
        "grantPrevLocked",
    }
)


def covers(grant: dict) -> set[str]:
    """이 허가가 덮는 행동. 옛 판(목록이 없는 것)은 `actionKey` 하나로 본다."""
    listed = grant.get("actions")
    if isinstance(listed, list) and listed:
        return {str(a) for a in listed}
    return {str(grant.get("actionKey") or "")}


def _usable(
    grant: dict,
    *,
    project: str,
    tool: str,
    fp: str,
    needs: list,
    running: bool,
    appendable: list,
    key: bytes | None,
    now: datetime,
) -> str:
    """쓸 수 있으면 빈 문자열, 아니면 거절 사유를 돌려준다.

    사유는 `_DISCARD`(허가가 죽었다) 또는 `_PUT_BACK`(이 호출의 허가가
    아니다) 중 하나로 분류된다.

    `needs` 는 지금 걸린 `(행동, 상대경로)` 목록이다. **하나라도 못 덮으면
    쓰지 않는다** — 사람이 본 그 호출이 아니라는 뜻이다.
    """
    if not verify(grant, key):
        return "grantBadSignature"
    if grant.get("project") != project:
        return "grantWrongProject"
    if _expired(grant, now):
        return "grantExpired"
    # 허가 자신이 잠긴 행동을 들고 있으면 영원히 못 쓴다.
    if covers(grant) & LOCKED_ACTIONS:
        return "grantLockedAction"
    if not needs:
        return "grantNothingToCover"
    actions = {action for action, _ in needs}
    if not actions <= covers(grant):
        return "grantActionMismatch"
    for action, rel in needs:
        # 승인할 때는 멈춰 있었어도 **쓸 때** 돌고 있으면 안 된다 (spec III-4).
        if action == "stop" and running:
            return "grantRunningNow"
        if action == "prev":
            leaf = str(rel or "").rsplit("/", 1)[-1]
            if leaf not in (appendable or []):
                return "grantPrevLocked"
    if grant.get("fingerprint") == fp:
        return ""
    if not grant.get("looseMatch"):
        return "grantFingerprintMismatch"
    if tool in NO_LOOSE_TOOLS:
        return "grantLooseNotAllowed"
    rels = {rel for _, rel in needs}
    if len(rels) != 1 or grant.get("looseKey") != loose_key(tool, rels.pop()):
        return "grantLooseMismatch"
    return ""


def consume(
    project: str,
    *,
    event: dict,
    needs,
    running: bool = False,
    appendable: list | None = None,
    log=None,
    now: datetime | None = None,
) -> dict | None:
    """이 호출에 쓸 수 있는 허가가 있으면 **소비하고** 돌려준다. 없으면 None.

    `needs` 는 지금 승인이 필요한 `(행동, 상대경로)` 목록이다. **호출당 한
    번만** 부른다 — `decide.resolve` 가 그렇게 부른다. finding 마다 부르면
    첫 번째가 허가를 태워 버려서 두 번째가 막힌다.

    `log` 를 주면 거절·소비마다 `{"event": ...}` 한 건으로 불린다
    (호출부가 `hook_events.jsonl` 에 적는다). 어떤 이유로든 예외를 올리지
    않는다 — 허가 확인이 실패하면 "허가 없음" 이고, 그러면 원래 판정대로
    막힌다.
    """
    try:
        return _consume(
            project,
            event=event or {},
            needs=[(str(a), r) for a, r in (needs or [])],
            running=running,
            appendable=list(appendable or []),
            log=log,
            now=now or _now(),
        )
    except Exception as exc:  # pragma: no cover - 어떤 버그든 열지 않는다
        if log:
            try:
                log({"event": "grantError", "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass
        return None


def _candidates(project: str, fp: str) -> list[str]:
    """정확히 일치하는 파일 먼저, 그 다음 느슨한 일치 후보."""
    folder = registry.grants_dir(project)
    exact = os.path.join(folder, _file_name(fp))
    out = [exact] if os.path.exists(exact) else []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(folder, name)
        if path not in out:
            out.append(path)
    return out


def _consume(project, *, event, needs, running, appendable, log, now):
    registry.valid_name(project)
    if not needs:
        return None
    # 잠긴 행동이 섞였으면 파일을 쳐다보지도 않는다.
    if {action for action, _ in needs} & LOCKED_ACTIONS:
        return None
    tool = str(event.get("tool_name") or "")
    fp = fingerprint(tool, event.get("tool_input"))
    key = config.grant_key()

    for path in _candidates(project, fp):
        claim = _claim(path)
        if claim is None:
            continue  # 남이 먼저 가져갔다
        grant = _read(claim)
        if grant is None:
            _archive(claim, None, "unreadable")
            if log:
                log({"event": "grantUnreadable", "file": os.path.basename(path)})
            continue
        why = _usable(
            grant,
            project=project,
            tool=tool,
            fp=fp,
            needs=needs,
            running=running,
            appendable=appendable,
            key=key,
            now=now,
        )
        if why:
            if why in _PUT_BACK:
                try:
                    os.rename(claim, path)
                except OSError:  # pragma: no cover - 되돌릴 수 없으면 치운다
                    _archive(claim, grant, why)
                continue
            _archive(claim, grant, why)
            if log:
                log(
                    {
                        "event": why,
                        "grantId": grant.get("grantId"),
                        "grantActions": sorted(covers(grant)),
                        "needed": sorted({a for a, _ in needs}),
                    }
                )
            continue

        _archive(claim, grant, "consumed")
        if log:
            log(
                {
                    "event": "grantConsumed",
                    "grantId": grant.get("grantId"),
                    "actions": sorted({a for a, _ in needs}),
                    "rels": sorted({r for _, r in needs if r}),
                    "loose": grant.get("fingerprint") != fp,
                }
            )
        grant["looseUsed"] = grant.get("fingerprint") != fp
        return grant
    return None


def list_grants(project: str) -> list[dict]:
    """살아 있는 허가 목록 (CLI 표시용). 서명이 틀린 것도 표시는 한다."""
    folder = registry.grants_dir(project)
    out: list[dict] = []
    key = config.grant_key()
    now = _now()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        grant = _read(os.path.join(folder, name))
        if grant is None:
            continue
        grant["signatureOk"] = verify(grant, key)
        grant["expired"] = _expired(grant, now)
        out.append(grant)
    return out


def revoke(project: str, grant_id: str) -> bool:
    """허가를 지운다. 승인을 되돌릴 때."""
    folder = registry.grants_dir(project)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return False
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(folder, name)
        grant = _read(path)
        if grant and grant.get("grantId") == grant_id:
            claim = _claim(path)
            if claim is None:
                return False
            _archive(claim, grant, "revoked")
            return True
    return False
