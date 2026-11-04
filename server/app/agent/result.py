"""`claude -p --output-format json` 출력 읽기.

### 출력 앞에 쓰레기가 붙는다 (실측)

0단계에서 `json.load` 가 `Expecting value: line 1 column 1` 로 깨졌다. 출력이
이렇게 시작했다:

    Warning: no stdin data received in 3s...
    {"type":"result", ...}

그래서 **첫 `{` 부터 마지막 `}` 까지를 꺼내 쓴다.** 그리고 띄울 때 항상
`stdin=DEVNULL` 을 준다 (그 경고 자체를 없앤다).

### 실패는 원문을 **그대로** 보관한다

한도에 걸릴 때 `claude -p` 가 무엇을 내놓는지 아직 못 봤다. 그래서 원인을
가르지 않고 원문과 종료코드를 쌓는다. 나중에 실제로 걸리면 그 문구로
"한도 대기" 를 구분한다 (`~/.config/labremote/usage_patterns.json`).
"""

from __future__ import annotations

import json
import re

__all__ = [
    "JSON_RE",
    "AgentResult",
    "parse",
    "denials",
    "looks_like_usage_limit",
    "STALL_REASONS",
]

#: 앞뒤에 붙은 경고를 건너뛰고 JSON 덩어리만 꺼낸다
JSON_RE = re.compile(r"\{.*\}", re.S)

#: 아무것도 못 하고 끝난 것. 실측: 헤드리스에서 훅의 `defer` 가 이렇게 끝난다.
STALL_REASONS = frozenset({"tool_deferred"})


class AgentResult(dict):
    """읽어 낸 결과. 원문을 항상 들고 있는다."""

    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))

    @property
    def text(self) -> str:
        return str(self.get("text") or "")

    @property
    def stalled(self) -> bool:
        """도구가 막혀 아무것도 못 하고 끝났나."""
        return str(self.get("stopReason") or "") in STALL_REASONS


def parse(raw: str, *, exit_code: int | None = None) -> AgentResult:
    """출력 한 덩어리를 읽는다. **던지지 않는다.**

    JSON 을 못 읽어도 원문과 종료코드는 남긴다 — 나중에 한도 문구를 뽑을
    유일한 재료다.
    """
    text = raw if isinstance(raw, str) else str(raw or "")
    out = AgentResult(
        ok=False,
        raw=text,
        exitCode=exit_code,
        text="",
        stopReason=None,
        sessionId=None,
        model=None,
        isError=None,
        subtype=None,
        numTurns=None,
        denials=[],
        usage={},
        costUsd=None,
        parseError=None,
    )
    found = JSON_RE.search(text)
    if not found:
        out["parseError"] = "출력에서 JSON 을 찾지 못했어요"
        return out
    try:
        data = json.loads(found.group(0))
    except (ValueError, TypeError) as exc:
        out["parseError"] = f"JSON 을 읽지 못했어요: {exc}"
        return out
    if not isinstance(data, dict):
        out["parseError"] = "JSON 이 객체가 아니에요"
        return out

    out["json"] = data
    out["text"] = str(data.get("result") or "")
    out["stopReason"] = data.get("stop_reason")
    out["sessionId"] = data.get("session_id")
    out["isError"] = data.get("is_error")
    out["subtype"] = data.get("subtype")
    out["numTurns"] = data.get("num_turns")
    out["denials"] = data.get("permission_denials") or []
    out["usage"] = data.get("usage") or {}
    out["costUsd"] = data.get("total_cost_usd")
    out["model"] = _model_of(data)
    # 종료코드가 0이고, is_error 가 아니고, 정지가 아니어야 성공이다.
    out["ok"] = (
        (exit_code in (None, 0))
        and not data.get("is_error")
        and str(data.get("stop_reason") or "") not in STALL_REASONS
    )
    return out


def denials(result) -> list[dict]:
    """`permission_denials` 를 정규화한다. — **승인 내용의 출처다.**

    ## 왜 여기서 가져오나 (원칙 (나))

    사람이 승인할 때 보는 내용과 지문은 **오케스트레이터가 자기 자식
    프로세스에서 직접 받은 것**이어야 한다. 훅이 쓴 요청 파일을 거치면
    믿어야 할 것이 하나 늘고, 훅이 파일을 못 썼을 때(디스크·크래시)
    오케스트레이터가 무엇이 막혔는지 모른다.

    > ℹ️ 원래 계획은 *"훅의 요청 파일을 AI 가 꾸밀 수 있다"* 를 이유로 들었다.
    > **그 이유는 M1 으로 사라졌다** — `server/data/requests/` 는 샌드박스
    > 안에서 쓰기가 실패하므로(M1b) AI 코드가 못 고친다. 남은 이유는
    > 위의 둘, 그리고 **본문을 여기서만 볼 수 있다**는 것이다.

    요청 파일에는 본문을 저장하지 않는다(비밀이 섞일 수 있다). 그래서
    `approve` 가 지문을 **다시 계산할 수 없고** 훅이 계산한 값을 믿어야
    했다. `permission_denials` 에는 `tool_input` 전체가 있으므로
    오케스트레이터가 **직접 계산**한다.

    ## 모양 (M2 실측 2026-11-05)

    ```json
    { "tool_name": "Bash",
      "tool_use_id": "toolu_01MLut…",
      "tool_input": {"command": "pip install peft", "description": "…"} }
    ```

    칸은 **셋뿐이다. 사유가 없다.** 그래서 사유는 훅의 요청 파일에서 가져와
    *"훅 참고(검증 안 됨)"* 로 따로 표시한다.
    """
    rows = []
    items = result.get("denials") if isinstance(result, dict) else None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool_name") or "")
        if not tool:
            continue
        tool_input = item.get("tool_input")
        rows.append(
            {
                "tool": tool,
                # Claude Code 가 넣는 값. AI 가 못 고친다.
                "toolUseId": str(item.get("tool_use_id") or ""),
                "toolInput": tool_input if isinstance(tool_input, dict) else {},
                # [미확인] 사유 칸은 2.1.318 의 `permission_denials` 에 없다
                "reason": "",
            }
        )
    return rows


def _model_of(data: dict) -> str | None:
    """쓰인 모델. `--model` 을 지정하지 않으므로 **결과에서 읽어** 기록한다."""
    for key in ("model", "modelUsed"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("model", "modelUsed"):
            value = usage.get(key)
            if isinstance(value, str) and value:
                return value
    info = data.get("modelInfo")
    if isinstance(info, dict) and isinstance(info.get("id"), str):
        return info["id"]
    return None


def looks_like_usage_limit(result: AgentResult, patterns) -> str:
    """사용량 한도로 보이는가. 맞으면 걸린 **패턴 문자열**을 돌려준다.

    패턴을 코드에 박지 않는다 — 한도 메시지를 아직 못 봤고, 틀린 패턴은
    인증 만료 같은 다른 오류를 한도로 오인해 **영원히 기다리게** 만든다.
    기본은 빈 목록이라 아무것도 한도로 보지 않는다.
    """
    haystack = " ".join(
        str(x) for x in (result.get("raw") or "", result.get("text") or "")
    ).lower()
    for pattern in patterns or []:
        text = str(pattern).strip().lower()
        if text and text in haystack:
            return str(pattern)
    return ""
