"""Finding + 정책 + 실행 상태 -> Decision.

`allow` 는 아껴 쓴다. 우리 규칙에 안 걸리는 건 `allow` 가 아니라 `defer` 다 —
훅이 함부로 allow 를 주면 Claude Code 자체 보호장치까지 건너뛴다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

from . import messages as M
from .classify import Ctx, Finding
from .emit import ALLOW, ASK, DEFER, DENY, Decision

__all__ = ["decide", "combine"]

#: 잠긴 항목에서 온 결정인지 (승인 로그 handledBy 에 쓴다)
LOCK_ACTIONS = {"outside", "prev", "stop", "selfProtect"}


def _name(ctx: Ctx, key: str) -> str:
    """승인 로그에 쓸 한국어 이름."""
    if key in M.LABELS:
        return M.LABELS[key]
    try:
        return ctx.policy.action_name(key)
    except Exception:
        return key


def decide(finding: Finding, ctx: Ctx) -> Decision:
    action = finding.action
    label = _name(ctx, action)
    base = dict(label=label, action=action, rel=finding.rel)

    # --- 훅 자신의 문제: 열지 않고 닫는다 ---------------------------------
    if action == "schema-unknown":
        return DENY(M.with_guard(M.SCHEMA_UNKNOWN), **base)

    if action == "denied-command":
        return DENY(M.with_guard(M.denied_command(str(finding.target))), **base)

    # --- 잠긴 항목 ---------------------------------------------------------
    if action == "selfProtect":
        return DENY(M.with_guard(M.self_protect(str(finding.rel))), **base)

    if action == "outside":
        return DENY(M.with_guard(M.outside(str(finding.target))), **base)

    if action == "prev":
        appendable = (ctx.paths_cfg.get("prevAppendable") or [])
        leaf = str(finding.rel or "").rsplit("/", 1)[-1]
        if leaf in appendable:
            return _maybe_headless(
                ASK(M.with_guard(M.prev_appendable(str(finding.rel), str(finding.exp))), **base),
                ctx,
                label,
            )
        return DENY(M.with_guard(M.prev_locked(str(finding.rel), str(finding.exp))), **base)

    if action == "stop":
        # spec III-4: 실험 진행 중에는 차단, 멈춰 있으면 승인을 거쳐 수정 가능
        if getattr(ctx.run, "running", False):
            exp = getattr(ctx.run, "experiment_id", None)
            return DENY(M.with_guard(M.stop_running(str(finding.rel), exp)), **base)
        return _maybe_headless(
            ASK(M.with_guard(M.stop_idle(str(finding.rel))), **base), ctx, label
        )

    # --- 기록은 늘 허용 (spec IV) ------------------------------------------
    if action == "journal":
        return ALLOW(**base)

    # --- 해석 못 한 명령 ---------------------------------------------------
    if action == "suspicious":
        return _maybe_headless(
            ASK(M.with_guard(M.suspicious(str(finding.target))), **base), ctx, label
        )
    if action == "unparsed":
        return _maybe_headless(
            ASK(M.with_guard(M.unparsed(str(finding.target))), **base), ctx, label
        )

    # --- 정책이 정하는 것 ---------------------------------------------------
    permission = ctx.policy.resolve(action)
    what = finding.rel or finding.target or ""
    if permission == "allow":
        return ALLOW(**base)
    if permission == "block":
        return DENY(M.with_guard(M.block_action(label, str(what))), **base)
    return _maybe_headless(ASK(M.with_guard(M.ask_action(label, str(what))), **base), ctx, label)


def _maybe_headless(decision: Decision, ctx: Ctx, label: str) -> Decision:
    """헤드리스에서 승인창을 띄울 수 없을 때.

    **자동 허용으로는 절대 안 넘어간다.** 정책 `headless.onAsk` 가
    "deny-with-reason" 이면 사유를 붙여 거절하고, 호출부가 Discord 로
    "승인 대기" 를 알린다. 기본값은 "ask" 다 (①단계).
    """
    if decision.kind != "ask" or not ctx.headless:
        return decision
    mode = (getattr(ctx.policy, "headless", {}) or {}).get("onAsk", "ask")
    if mode != "deny-with-reason":
        return decision
    return DENY(
        M.with_guard(M.headless_ask(label, decision.reason)),
        label=decision.label,
        action=decision.action,
        rel=decision.rel,
        meta={**decision.meta, "headlessDeny": True, "originallyAsk": True},
    )


def combine(decisions: list[Decision]) -> Decision:
    """가장 제한적인 것이 이긴다: deny > ask > defer > allow.

    예: EXP-007 이 도는 중 experiments/EXP-006/config.yaml 수정
        -> {prev(deny), hparam(ask)} -> prev 의 deny.
    """
    if not decisions:
        return DEFER()
    winner = max(decisions, key=lambda d: d.rank)
    if winner.kind == "allow":
        # 모두 allow 여도, 우리가 확실히 아는 것만 allow 로 돌려준다.
        return winner
    return winner
