"""PreToolUse 엔트리포인트 — stdin JSON -> stdout JSON, 언제나 exit 0.

흐름
  1 stdin 을 읽는다. 못 읽으면 deny.
  2 cwd 가 등록된 실험 프로젝트인가? 아니면 defer (간섭하지 않음).
  3 정책·실행 상태를 읽는다. 못 믿으면 deny (fail-closed).
  4 분류 -> 판정 -> 가장 제한적인 것.
  5 기록 (CSV + JSONL + 대기 건 + 필요하면 Discord).
  6 stdout 에 JSON 하나.

어떤 예외든 deny + 사유로 바꾼다. 조용히 문이 열리면 "Hooks 로 강제" 가
거짓말이 된다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
import sys

from .. import approval_log as A
from .. import embed, grants, notify, paths, policy as policy_mod, registry, runstate
from . import classify, debug, decide as decide_mod
from . import messages as M
from .emit import DEFER, DENY, Decision, emit

__all__ = ["main", "handle"]

#: 오케스트레이터가 `claude -p` 를 띄울 때 넣는다. stdin 으로는 구분할 수 없다.
HEADLESS_ENV = "LABREMOTE_HEADLESS"


def _ctx_from(event: dict):
    """등록된 프로젝트면 Ctx, 아니면 None."""
    cwd = str(event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    found = registry.lookup(cwd)
    if not found:
        return None
    root, name = found
    pol = policy_mod.load(name)  # PolicyError 는 위에서 deny 로 바뀐다
    return classify.Ctx(
        root=root,
        cwd=paths.real(cwd),
        name=name,
        policy=pol,
        run=runstate.load(name),
        event=event,
        headless=os.environ.get(HEADLESS_ENV) == "1",
        # 설정을 **매번 읽는다.** 사람이 꺼 두면 그 다음 호출부터 바로
        # 코드 실행이 닫힌다 (fail-closed).
        sandbox=bool(policy_mod.sandbox_state(root).get("ok")),
    )


def _bypass_note(ctx, decision: Decision, findings: list) -> dict | None:
    """같은 세션에서 막힌 대상에 다른 도구로 다시 왔는가.

    실측(2.1.317): Edit 거절 -> Bash sed -> Write 순으로 같은 파일을 노렸다.
    """
    session = str(ctx.event.get("session_id") or "")
    tool = str(ctx.event.get("tool_name") or "")
    for finding in findings:
        if not finding.rel or not finding.writes:
            continue
        before = A.recall_denied(ctx.name, session, finding.rel)
        if before and before.get("tool") and before["tool"] != tool:
            return {"rel": finding.rel, "before": before["tool"], "now": tool}
    return None


#: 판정할 것이 없는 allow. 이 줄은 `hook_events.jsonl` 에 남기지 않는다 —
#: S5 로 훅이 모든 도구에 뜨면서 이것들이 로그의 대부분이 된다.
#: **승인 로그 CSV(`Approval_log.csv`)에는 그대로 남는다** — 거기가 기록
#: 의무의 대상이고, 체인·앵커로 지키는 쪽이다.
QUIET_ACTIONS = frozenset(
    {
        "readAllowed",   # 프로젝트 안 읽기
        "toolAllowed",   # 읽기 전용 도구 (Glob·TodoWrite·ToolSearch…)
        "bashAllowed",   # 허용 목록에 있는 명령
        "journal",        # 기록 파일 쓰기 (항상 허용)
    }
)


def _record(ctx, event: dict, findings: list, decision: Decision) -> None:
    """CSV + JSONL + 대기 건. 기록이 실패해도 판정은 그대로 나간다."""
    log = A.log_path(ctx.root, ctx.policy)
    events = A.event_path(ctx.root, ctx.policy)
    tool = str(event.get("tool_name") or "")
    tool_use_id = str(event.get("tool_use_id") or "")
    prompt_id = str(event.get("prompt_id") or "")
    session_id = str(event.get("session_id") or "")

    request = decision.rel or _request_summary(event)
    label = decision.label or tool
    bypass = _bypass_note(ctx, decision, findings)

    # 🔑 matcher 가 **모든 도구**가 되면서(S5) 훅이 도구 호출마다 뜬다. 그
    # 대가로 `hook_events.jsonl` 이 폭증한다 — `Read`·`Glob`·`TodoWrite` 가
    # 압도적으로 많고, 그 줄에는 **판정할 것이 아무것도 없다.**
    #
    # 그래서 **아무 소득 없는 allow 는 안 남긴다.** 남기는 기준:
    #   - 막힌 것(deny)·물은 것(ask)·허가로 통과한 것 → 전부 남긴다
    #   - 우회 시도·훅 오류 → 전부 남긴다
    #   - `QUIET_ACTIONS` 의 allow → **안 남긴다** (승인 로그 CSV 에는 남는다)
    if not (
        decision.kind == "allow"
        and not bypass
        and decision.action in QUIET_ACTIONS
        and not decision.meta
    ):
        A.log_event(
            events,
            {
                "event": "PreToolUse",
                "tool": tool,
                "toolUseId": tool_use_id,
                "promptId": prompt_id,
                "sessionId": session_id,
                "permissionMode": event.get("permission_mode"),
                "decision": decision.kind,
                "action": decision.action,
                "rel": decision.rel,
                "findings": [
                    {"action": f.action, "rel": f.rel, "target": f.target, "detail": f.detail}
                    for f in findings
                ],
                "reason": decision.reason,
                "headless": ctx.headless,
                "runState": {
                    "running": getattr(ctx.run, "running", False),
                    "experimentId": getattr(ctx.run, "experiment_id", None),
                    "stale": getattr(ctx.run, "stale", False),
                },
                **({"bypassAttempt": bypass} if bypass else {}),
            },
        )

    if bypass:
        A.append_row(
            log,
            project=ctx.name,
            action="우회 시도",
            request=M.bypass_attempt(bypass["rel"], bypass["before"], bypass["now"]),
            result="차단",
            handled_by=M.BY_LOCK,
            tool_use_id=tool_use_id,
        )

    # 평소와 다른 권한 모드로 떠 있으면 그 사실 자체를 남긴다 (실측 항목).
    # ⚠ **막은 게 아니다.** 판정은 permission_mode 를 읽지 않는다 — 잠금은
    # 그대로 deny, ask 는 그대로 Claude 앱의 승인창으로 간다. 그래서 결과 칸은
    # `기록` 이다. 2.1.317 은 사용자 설정에 defaultMode 가 없으면 auto 로 뜬다.
    mode_now = str(event.get("permission_mode") or "")
    if mode_now not in ("", "default", "plan", "acceptEdits"):
        A.append_row(
            log,
            project=ctx.name,
            action="권한 우회 모드",
            request=f"permission_mode={mode_now} · 훅 판정은 {decision.kind}",
            result="기록",
            handled_by=M.BY_SYSTEM,
            tool_use_id=tool_use_id,
        )

    # 1회용 허가를 보며 생긴 일(소비·서명 불일치·만료)을 남긴다.
    for entry in decision.meta.get("grantLog") or []:
        A.log_event(events, {"tool": tool, "toolUseId": tool_use_id, **entry})

    if decision.kind == "allow" and decision.meta.get("grantUsed"):
        # 사람이 승인한 허가로 통과했다. 정책이 열어 준 것과 구분해 적는다.
        A.append_row(
            log,
            project=ctx.name,
            action=label,
            request=request,
            result="허용 · 1회용 승인",
            handled_by=M.BY_GRANT,
            tool_use_id=tool_use_id,
        )
        A.close_request(
            ctx.name,
            tool_use_id or f"{prompt_id}:{tool}",
            result="소비됨",
            grant_id=str(decision.meta.get("grant") or ""),
        )
    elif decision.kind == "allow":
        A.append_row(
            log,
            project=ctx.name,
            action=label,
            request=request,
            result="허용",
            handled_by=M.BY_POLICY,
            tool_use_id=tool_use_id,
        )
    elif decision.kind == "deny":
        locked = decision.action in decide_mod.LOCK_ACTIONS
        A.append_row(
            log,
            project=ctx.name,
            action=label,
            request=request,
            result="차단",
            handled_by=M.BY_LOCK if locked else M.BY_POLICY,
            tool_use_id=tool_use_id,
        )
        if decision.rel:
            A.remember_denied(ctx.name, session_id, decision.rel, tool, prompt_id)
    elif decision.kind == "ask":
        A.open_pending(
            ctx.name,
            tool_use_id or f"{prompt_id}:{tool}",
            {
                "promptId": prompt_id,
                "sessionId": session_id,
                "tool": tool,
                "action": label,
                "request": request,
                "rel": decision.rel,
                **_agent_of(event),
            },
        )
        A.append_row(
            log,
            project=ctx.name,
            action=label,
            request=request,
            result="대기 중",
            pending=True,
            handled_by=M.BY_APP,
            tool_use_id=tool_use_id,
        )
        if decision.rel:
            A.remember_denied(ctx.name, session_id, decision.rel, tool, prompt_id)

    # 헤드리스에서 승인창을 못 띄워 거절한 경우 — 조용히 멈추지 않게 알린다.
    # 대기 건(pending/)이 아니라 **승인 요청(requests/)** 으로 남긴다. 닫아 줄
    # 주체가 Claude 앱이 아니라 ②의 승인 대기열이라, 대기 폴더에 두면 영원히
    # 안 닫히는 대기 건이 된다.
    if decision.meta.get("headlessDeny"):
        asked = decision.meta.get("asked") or [
            {"action": decision.action, "name": label, "rel": decision.rel}
        ]
        tool_input = event.get("tool_input")
        A.open_request(
            ctx.name,
            tool_use_id or f"{prompt_id}:{tool}",
            {
                "promptId": prompt_id,
                "sessionId": session_id,
                "tool": tool,
                "action": label,
                "request": request,
                "rel": decision.rel,
                "reason": decision.reason,
                # --- ②가 1회용 허가를 발급하는 데 필요한 것 ---
                # 걸린 행동을 **전부** 싣는다. 한 호출에 ask 가 둘 이상일 수
                # 있고(net + pkg), 승인 1회가 그 전부를 열어야 한다.
                "actionKey": decision.action,
                "actions": asked,
                "fingerprint": grants.fingerprint(tool, tool_input),
                "looseKey": grants.loose_key(tool, decision.rel),
                # 본문은 저장하지 않는다 — 길이와 해시만.
                "toolSummary": grants.summarize_input(tool_input),
                "cwd": event.get("cwd"),
                "permissionMode": event.get("permission_mode"),
                "runState": {
                    "running": getattr(ctx.run, "running", False),
                    "experimentId": getattr(ctx.run, "experiment_id", None),
                },
                **_agent_of(event),  # ②의 대기열이 누가 낸 요청인지 알아야 한다
            },
        )
        if (ctx.policy.headless or {}).get("notifyDiscord", True):
            result = notify.send_payload(
                _approval_embed(ctx, asked, request, decision), kind="approval"
            )
            A.log_event(events, {"event": "notify", "result": result})


def _approval_embed(ctx, asked: list, request: str, decision: Decision) -> dict:
    """승인 대기 알림. **걸린 행동 전부와 사유 전문**을 싣는다 (①의 숙제 2번).

    평문으로 보내면 2000자에서 잘려 사유가 사라진다. 임베드 필드는 1024자씩
    나눠 담는다 (`app/embed.py`).
    """
    names = " · ".join(a.get("name") or a.get("action") or "?" for a in asked)
    fields = [("걸린 행동", names), ("대상", request), ("훅 사유", decision.reason)]
    rels = [a.get("rel") for a in asked if a.get("rel")]
    if rels:
        fields.insert(2, ("파일", "\n".join(dict.fromkeys(rels))))
    return embed.build(
        "approval",
        project=ctx.name,
        title="승인이 필요해요",
        body=f"{len(asked)}가지 승인이 필요해요." if len(asked) > 1 else "",
        fields=fields,
        # 🔑 `show` 를 먼저 적는다 — **전문을 보고** 승인해야 한다.
        # 알림은 길이 제한이 있어 잘릴 수 있고, 잘리면 임베드가 그 사실을
        # 표시하지만(`embed.TRUNC_FIELD`) 전문은 `show` 에만 있다 (9단계 1번).
        footer=(
            "labremote approvals show <프로젝트> <요청ID> 로 **전문을 본 뒤** "
            "approve 로 승인해 주세요. 목록은 approvals list 예요."
        ),
    )


def _agent_of(event: dict) -> dict:
    """대기 건에 남길 에이전트 정보.

    **구분자는 `agent_id` 하나다.** 실측(2026-11-04)과 2.1.317 번들의 스키마
    설명이 근거다:

        agent_id   "Present only when the hook fires from within a subagent
                    (e.g., a tool called by an AgentTool worker). Absent for
                    the main thread, **even in --agent sessions**."
        agent_type "Present when the hook fires from within a subagent
                    (alongside agent_id), **or on the main thread of a session
                    started with --agent** (without agent_id)."

    그래서 `agent_type` 으로 구분하면 `--agent` 로 띄운 메인 세션의 대기 건이
    영원히 안 닫힌다. `agentType` 은 사람이 보는 표시용으로만 남긴다.
    """
    return {
        "agentId": str(event.get("agent_id") or ""),
        "agentType": str(event.get("agent_type") or ""),
    }


def _request_summary(event: dict) -> str:
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "url", "notebook_path", "query"):
            if tool_input.get(key):
                return str(tool_input[key])
    return str(event.get("tool_name") or "")


def _close_previous_turn(ctx) -> None:
    """같은 세션의 **이전 응답** 대기 건을 닫는다 (Stop 이 안 돈 경우의 안전망).

    PC 터미널에서 승인을 거부하면 턴이 끊겨 Stop 이 돌지 않는다
    (`userprompt.py` 의 설명). UserPromptSubmit 훅이 1차로 닫지만, 그 훅이
    아직 설치 안 된 경우에도 대기 뱃지가 거짓으로 켜져 있지 않게 여기서 한 번
    더 본다. **지금 응답(`prompt_id`)의 대기 건은 건드리지 않는다.**

    기록이 실패해도 판정은 그대로 나가야 하므로 예외를 전부 삼킨다.
    """
    session_id = str(ctx.event.get("session_id") or "")
    prompt_id = str(ctx.event.get("prompt_id") or "")
    if not session_id or not prompt_id:
        return
    try:
        A.close_stale(
            ctx.name,
            ctx.root,
            ctx.policy,
            session_id=session_id,
            keep_prompt_id=prompt_id,
            main_only=True,  # 서브에이전트는 자기 턴이 끝나도 계속 돈다
            by="PreToolUse",
        )
    except Exception:
        pass


def handle(event: dict) -> Decision:
    """판정만. 기록과 출력은 main 이 한다."""
    ctx = _ctx_from(event)
    if ctx is None:
        return DEFER()  # 등록된 실험 프로젝트가 아니면 간섭하지 않는다

    _close_previous_turn(ctx)

    findings = classify.classify_event(event, ctx)
    if not findings:
        return DEFER()
    # 행동마다 판정하고 **호출 단위로** 1회용 허가를 본다 (decide.resolve 주석).
    decision = decide_mod.resolve(findings, ctx)
    _record(ctx, event, findings, decision)
    return decision


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return emit(DENY(M.with_guard(M.BAD_INPUT)))

    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("JSON 객체가 아니에요")
    except Exception:
        return emit(DENY(M.with_guard(M.BAD_INPUT)))

    if os.environ.get("LABREMOTE_HOOK_DUMP") == "1":
        try:
            debug.dump(raw)
        except Exception:
            pass

    try:
        decision = handle(event)
    except policy_mod.PolicyError as exc:
        decision = DENY(M.with_guard(M.policy_error(str(exc))), action="policy-error")
    except Exception as exc:  # 어떤 버그든 열지 않고 닫는다
        decision = DENY(M.with_guard(M.HOOK_ERROR), action="hook-error")
        _log_internal_error(event, exc, raw)

    return emit(decision)


def _log_internal_error(event: dict, exc: Exception, raw: str) -> None:
    try:
        found = registry.lookup(str(event.get("cwd") or ""))
        if not found:
            return
        root, _ = found
        A.log_event(
            A.event_path(root),
            {
                "event": "hook-error",
                "error": f"{type(exc).__name__}: {exc}",
                "tool": event.get("tool_name"),
                "rawKeys": sorted(event) if isinstance(event, dict) else None,
                "rawLength": len(raw),
            },
        )
    except Exception:
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
