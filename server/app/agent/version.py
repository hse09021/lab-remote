"""📌 Claude Code 판 기록 — **도구 이름이 바뀌면 방어에 틈이 생긴다.**

## 왜 필요한가

2.1.317 → 2.1.318 이 **저절로** 바뀌었습니다. 그리고 그 판에서
서브에이전트 도구 이름이 `Task` → `Agent` 로 달라져 있었습니다 —
`--disallowedTools Task` 가 무효가 되어 **서브에이전트가 열린 채로 돌았고,
우리는 몰랐습니다.** 조용한 실패였습니다.

같은 일이 또 일어나지 않게 두 가지를 합니다.

1. **우리가 띄우는 `claude` 는 자동 업데이트를 하지 않습니다** —
   `DISABLE_AUTOUPDATER=1` (`launch.SAFE_ENV`). 번들의 판정 코드를 읽어
   확인했습니다:

       if (DISABLE_UPDATES) …;  if (DISABLE_AUTOUPDATER) …;
       if (config.autoUpdates === false && (installMethod !== "native" || …))

   이 설치는 `native` 라 **설정의 `autoUpdates:false` 는 무시될 수
   있습니다.** 그래서 환경 변수가 유일하게 믿을 만한 길입니다.

   ⚠ 이건 **우리가 띄우는 프로세스만** 막습니다. 사람이 자기 터미널에서
   `claude` 를 쓰면 그쪽이 바이너리를 갈아 버립니다 — 그래서 2번이 필요합니다.

2. **마지막으로 도구 목록을 실측한 판을 기록**하고, 지금 판과 다르면
   `doctor` 가 ⚠ 를 띄우고 **헤드리스 루프를 멈춥니다.**

## 왜 멈추나 (제안이 아니라 기본값으로 둔 이유)

판이 바뀌었을 때 생기는 틈은 **조용합니다** — `Task` 가 그랬습니다. 루프는
사람이 안 보는 동안 몇 시간씩 돕니다. 그 사이에 "서브에이전트가 꺼져 있다"
는 기록이 거짓이 되는 게 가장 나쁜 경우입니다.

멈추는 비용은 **명령 하나**입니다.

    labremote tools              # 지금 판과 기록을 대조
    labremote tools --probe      # 세션에 도구 목록을 물어 다시 재고 기록
    labremote tools --accept     # 목록이 같다고 보고 판만 기록 (사람이 확인한 뒤)

대화형(`labremote claude`)은 **막지 않습니다** — 사람이 보고 있고, 막으면
재는 것도 못 합니다.
"""

from __future__ import annotations

import json
import os
import subprocess

from .. import registry

__all__ = [
    "RECORD_NAME",
    "record_path",
    "current",
    "recorded",
    "record",
    "check",
    "probe_tools",
]

#: `server/data/agent/` 아래 — 샌드박스 안에서 쓰기가 실패한다(M1b).
RECORD_NAME = "claude_version.json"

PROBE_TIMEOUT_SEC = 20


def record_path() -> str:
    return os.path.join(registry.data_dir(), "agent", RECORD_NAME)


def current(binary: str = "claude") -> str:
    """`claude --version` 의 판 번호. 못 읽으면 빈 문자열.

    출력 꼴: `2.1.318 (Claude Code)`
    """
    try:
        done = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    head = (done.stdout or "").strip().split()
    return head[0] if head else ""


def recorded() -> dict:
    """마지막으로 실측한 기록. 없으면 빈 dict."""
    try:
        with open(record_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(version: str, *, tools: list[str] | None = None, note: str = "") -> dict:
    """판과 (알면) 도구 목록을 기록한다."""
    from datetime import datetime

    payload = {
        "version": str(version or ""),
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
    }
    if tools is not None:
        payload["tools"] = sorted(tools)
    os.makedirs(os.path.dirname(record_path()), exist_ok=True)
    registry.write_json(record_path(), payload)
    return payload


def check(binary: str = "claude") -> dict:
    """지금 판이 기록과 같은가. `{"ok", "current", "recorded", "reason"}`.

    **던지지 않는다** — `doctor` 와 `guards` 가 같은 함수를 쓴다.
    """
    now = current(binary)
    saved = recorded()
    out = {
        "ok": False,
        "current": now,
        "recorded": str(saved.get("version") or ""),
        "at": str(saved.get("at") or ""),
        "reason": "",
    }
    if not now:
        out["reason"] = f"{binary} --version 을 읽을 수 없어요"
        return out
    if not out["recorded"]:
        out["reason"] = (
            f"도구 목록을 실측한 판 기록이 없어요 (지금 {now}) · "
            "labremote tools --probe 로 재고 기록해 주세요"
        )
        return out
    if out["recorded"] != now:
        out["reason"] = (
            f"Claude Code 판이 바뀌었어요: {out['recorded']} → {now} "
            f"(마지막 실측 {out['at']}) · 도구 이름이 바뀌면 방어에 틈이 생겨요 "
            "— labremote tools --probe 로 도구 목록을 다시 재 주세요"
        )
        return out
    out["ok"] = True
    return out


#: 세션에 물어볼 때 쓰는 프롬프트. 도구를 **쓰지 말고** 이름만 적게 한다.
PROBE_PROMPT = (
    "지금 이 세션에서 실제로 호출할 수 있는 도구의 정확한 이름을 전부 "
    "나열해 주세요. 지연 로드(deferred) 목록에 있는 것도 같이 적어 주세요. "
    "도구를 쓰지 말고, 설명 없이 한 줄에 이름 하나씩만 적어 주세요."
)

#: 이름으로 받아들일 꼴. 글머리표·괄호 주석을 걷어낸다.
import re as _re

_NAME_RE = _re.compile(r"^[-*\s]*([A-Za-z][A-Za-z0-9_]{1,63})\b")


def parse_tools(text: str) -> list[str]:
    """세션이 적어 준 목록에서 도구 이름만 뽑는다."""
    out = []
    for line in (text or "").splitlines():
        got = _NAME_RE.match(line.strip())
        if got:
            out.append(got.group(1))
    return sorted(dict.fromkeys(out))


def probe_tools(project: str, *, runner=None) -> dict:
    """세션에 **직접 물어** 도구 목록을 받는다.

    번들에 문자열이 있어도 노출되지 않는다(실측: `Glob`·`Grep`·`TodoWrite` 가
    그랬다). 그래서 세션에 묻는 것이 유일하게 믿을 만한 출처다.

    `runner` 는 시험에서 바꿔 끼운다.
    """
    from . import launch as launch_mod
    from . import session as session_mod

    root = registry.root_of(project)
    if not root:
        return {"ok": False, "reason": f"등록된 프로젝트가 아니에요: {project}"}

    run = launch_mod.AgentRun(
        project=project,
        root=root,
        prompt=PROBE_PROMPT,
        session_id=session_mod.new_id(),
        headless=True,
        # 🔑 제약을 **푼다.** 우리 허용 목록을 켠 채로 물으면 그 10개만
        # 보여서 새로 생긴 도구를 영영 못 찾는다. 훅·샌드박스·
        # `--permission-prompts none` 은 그대로 걸려 있고, 프롬프트는
        # "도구를 쓰지 말고 이름만" 이다.
        probe=True,
    )
    try:
        made = launch_mod.plan(run, preset="full")
    except launch_mod.LaunchRefused as exc:
        return {"ok": False, "reason": str(exc)}

    if runner is not None:
        got = runner(made)
    else:
        try:
            done = subprocess.run(
                made["argv"], capture_output=True, text=True,
                timeout=300, env=made["env"], cwd=made["cwd"],
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "reason": f"세션을 띄우지 못했어요: {exc}"}
        try:
            payload = json.loads((done.stdout or "").strip() or "{}")
        except ValueError:
            return {"ok": False, "reason": (done.stderr or done.stdout or "")[:300]}
        got = {"ok": done.returncode == 0, "result": payload.get("result") or ""}

    if not got.get("ok"):
        return {"ok": False, "reason": str(got.get("reason") or "세션이 실패했어요")}
    tools = parse_tools(str(got.get("result") or ""))
    if not tools:
        return {"ok": False, "reason": "도구 이름을 못 읽었어요", "raw": got.get("result")}
    return {"ok": True, "tools": tools, "raw": got.get("result")}


def compare(tools: list[str]) -> dict:
    """받은 목록을 우리 분류·허용 목록과 대조한다."""
    from ..hooks import classify
    from . import launch as launch_mod

    live = set(tools)
    known = set(classify.TOOLS_2_1_318)
    allowed = set(launch_mod.ALLOWED_TOOLS)
    off = set(launch_mod.DISALLOWED_TOOLS)

    return {
        # 🔴 새로 생긴 도구 — 분류에 없다. 허용 목록 덕에 노출은 안 되지만
        # 분류·문서에 적어야 한다. **이게 가장 중요하다.**
        "new": sorted(live - known),
        # 🔴 쓰겠다고 한 것이 없다 — 루프가 깨진다 (이름이 바뀐 경우)
        "missingAllowed": sorted(allowed - live),
        # ⚪ 이 세션에 안 보인 도구. **경보가 아니다** — 도구 노출은 계정·
        # 환경에 따라 다르다. 실측: `Artifact`·`ArtifactComments`·
        # `ArtifactData`·`SendFeedback` 은 넓은 환경에서는 보이고 런처가
        # 좁힌 환경에서는 **안 보였다**. 없는 도구를 끄는 것은 해롭지 않고,
        # 나타날 때를 위해 목록에 남겨 둔다.
        "absent": sorted(known - live),
        "absentDisallowed": sorted(off - live),
    }
