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
LOCK_ACTIONS = {
    "outside",
    "prev",
    "stop",
    "selfProtect",
    "hardProtect",
    "secret",
    "outputProtect",
}


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

    # 정책으로도 못 연다. extraWritableRoots 예외보다 앞에서 판정됐다.
    if action == "hardProtect":
        return DENY(M.with_guard(M.hard_protect(str(finding.target))), **base)

    # 읽기까지 막는 유일한 분류
    if action == "secret":
        return DENY(M.with_guard(M.secret(str(finding.target))), **base)

    # 원본 출력 보존. 돌고 있는 실험도 대상이다.
    if action == "outputProtect":
        return DENY(
            M.with_guard(
                M.output_protect(
                    str(finding.rel), str(finding.exp), finding.detail or "바꿀"
                )
            ),
            **base,
        )

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

    # --- 분류 못 한 세그먼트 (①의 경계 버그) -------------------------------
    # 미분류 세그먼트는 findings 에 아무것도 보태지 않아서
    #   echo x > src/t.txt && conda run -n base rm -rf <프로젝트 밖>
    # 이 앞 조각(code) 하나만으로 **allow** 가 됐다 — 사람에게 묻지도 않고.
    # 이제 미분류 자체가 Finding 으로 올라오고, 여기서 allow 보다 센 판정을 준다.
    if action == "unclassified":
        if not ctx.headless:
            # 대화형: Claude Code 기본 승인 흐름으로 넘긴다 — 사람이 보고 고른다.
            # 훅이 함부로 allow 를 주지 않는다는 이 모듈의 원칙 그대로다.
            return DEFER(**base)
        # 헤드리스: defer 는 통과가 아니라 **정지**다 (실측 — `ls -1` 조차
        # tool_deferred 로 끝나고 기록도 안 남는다). 승인 경로로 올린다.
        return _maybe_headless(
            ASK(M.with_guard(M.unclassified(str(finding.target))), **base), ctx, label
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

    **자동 허용으로는 절대 안 넘어간다.** 기본값은 `deny-with-reason` 이다 —
    실측(2026-11-04)에서 `claude -p` 의 ask 는 사람에게 가지 않고 10초 안에
    자동 거부됐다. 기다려 주지 않으므로 우리가 사유를 붙여 먼저 막고,
    호출부가 승인 요청을 `data/requests/` 에 남기고 Discord 로 알린다.
    """
    if decision.kind != "ask" or not ctx.headless:
        return decision
    mode = (getattr(ctx.policy, "headless", {}) or {}).get(
        "onAsk", "deny-with-reason"
    )
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

    **미분류 조각이 하나라도 있으면 결과가 allow 일 수 없다.** 순위표만으로도
    그렇게 되지만(defer·ask 가 allow 보다 세다) 불변식을 여기 한 줄로 못박는다 —
    ①에서 이 경계가 조용히 뚫렸던 자리라서, 순위표가 바뀌어도 안 열리게 둔다.
    """
    if not decisions:
        return DEFER()
    winner = max(decisions, key=lambda d: d.rank)
    if winner.kind == "allow" and any(d.action == "unclassified" for d in decisions):
        # 여기 오면 unclassified 판정이 allow 로 나왔다는 뜻이다. 열지 않는다.
        return DEFER(label=winner.label, action="unclassified")
    return winner
