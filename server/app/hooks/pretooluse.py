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
from .. import notify, paths, policy as policy_mod, registry, runstate
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
            action="우회 시도",
            request=M.bypass_attempt(bypass["rel"], bypass["before"], bypass["now"]),
            result="차단",
            handled_by=M.BY_LOCK,
        )

    # 권한 우회 모드로 떠 있으면 그 사실 자체를 남긴다 (실측 항목).
    if str(event.get("permission_mode") or "") not in ("", "default", "plan", "acceptEdits"):
        A.append_row(
            log,
            action="권한 우회 모드",
            request=f"permission_mode={event.get('permission_mode')}",
            result="차단",
            handled_by=M.BY_SYSTEM,
        )

    if decision.kind == "allow":
        A.append_row(log, action=label, request=request, result="허용", handled_by=M.BY_POLICY)
    elif decision.kind == "deny":
        locked = decision.action in decide_mod.LOCK_ACTIONS
        A.append_row(
            log,
            action=label,
            request=request,
            result="차단",
            handled_by=M.BY_LOCK if locked else M.BY_POLICY,
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
            },
        )
        A.append_row(
            log,
            action=label,
            request=request,
            result="대기 중",
            pending=True,
            handled_by=M.BY_APP,
        )
        if decision.rel:
            A.remember_denied(ctx.name, session_id, decision.rel, tool, prompt_id)

    # 헤드리스에서 승인창을 못 띄워 거절한 경우 — 조용히 멈추지 않게 알린다.
    if decision.meta.get("headlessDeny") and (ctx.policy.headless or {}).get("notifyDiscord", True):
        result = notify.send(
            f"[lab.remote] 승인 대기 · {ctx.name}\n{label} · {request}\n"
            "자동 실행이라 사람에게 물어볼 수 없어 일단 막았어요."
        )
        A.log_event(events, {"event": "notify", "result": result})


def _request_summary(event: dict) -> str:
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "url", "notebook_path", "query"):
            if tool_input.get(key):
                return str(tool_input[key])
    return str(event.get("tool_name") or "")


def handle(event: dict) -> Decision:
    """판정만. 기록과 출력은 main 이 한다."""
    ctx = _ctx_from(event)
    if ctx is None:
        return DEFER()  # 등록된 실험 프로젝트가 아니면 간섭하지 않는다

    findings = classify.classify_event(event, ctx)
    if not findings:
        return DEFER()
    decision = decide_mod.combine([decide_mod.decide(f, ctx) for f in findings])
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
