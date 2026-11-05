"""Finding + 정책 + 실행 상태 -> Decision.

`allow` 는 아껴 쓴다. 우리 규칙에 안 걸리는 건 `allow` 가 아니라 `defer` 다 —
훅이 함부로 allow 를 주면 Claude Code 자체 보호장치까지 건너뛴다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

from .. import grants
from . import messages as M
from .classify import Ctx, Finding
from .emit import ALLOW, ASK, DEFER, DENY, Decision

__all__ = ["decide", "combine", "resolve"]

#: 잠긴 항목에서 온 결정인지 (승인 로그 handledBy 에 쓴다)
LOCK_ACTIONS = {
    "trainrun",
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

    # --- 프로젝트 밖 읽기 ---------------------------------------------------
    # 네트워크가 열려 있으니 **읽힌 건 곧 나갈 수 있다.** 대화형은 그대로
    # 두고(①의 동작), 헤드리스에서는 승인을 받는다.
    if action == "readOutside":
        if not ctx.headless:
            return DEFER(**base)
        return _maybe_headless(
            ASK(M.with_guard(M.read_outside(str(finding.target))), **base), ctx, label
        )

    # --- 허용 목록에 있는 명령 (헤드리스 전용) ------------------------------
    # 실측: 헤드리스에서 `defer` 는 통과가 아니라 **정지**다(tool_deferred).
    # `ls` 조차 아무것도 못 하고 끝난다. 그래서 아는 명령은 allow 를 준다.
    # 대화형에서는 defer 가 정상 동작하므로 그대로 둔다 — 훅이 함부로 allow 를
    # 주지 않는다는 이 모듈의 원칙을 헤드리스에서만 접는다.
    if action in ("bashAllowed", "readAllowed", "toolAllowed"):
        if ctx.headless:
            return ALLOW(**base)
        return DEFER(**base)

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

    # --- 학습 직접 실행: **정책보다 앞에서** 판정한다 ----------------------
    #
    # `full` 프리셋은 `newexp` 를 자동 허용한다. entrypoint 직접 실행이
    # `newexp` 였을 때는 그게 곧 "Claude 가 학습을 혼자 돌려도 된다" 였다.
    # 그러면 GPU 큐와 동시에 GPU 를 쓰고, 10분 넘는 Bash 문제가 다시 생기고,
    # `run.json` 검증·샌드박스·타임아웃·체크포인트가 전부 지나간다.
    #
    # 그래서 `ctx.policy.resolve()` 에 **닿지 않게** 여기서 끝낸다 —
    # 권한 단계를 올려도 안 열린다.
    if action == "trainrun":
        if ctx.headless:
            return DENY(M.with_guard(M.trainrun_headless(str(finding.target))), **base)
        # 대화형은 사람이 보고 있다. 승인창을 띄운다.
        return ASK(M.with_guard(M.trainrun_interactive(str(finding.target))), **base)

    # --- 코드 실행: 소켓 차단 확인 전이면 **정책보다 앞에서** 승인으로 ---------
    #
    # 잠금은 아니다 — 사람이 그 명령 하나를 보고 승인할 수 있다(1회용 허가).
    if action == "coderun":
        return _maybe_headless(
            ASK(M.with_guard(M.coderun_unverified(str(finding.target), ctx.name)), **base),
            ctx, label,
        )

    # --- 정책이 정하는 것 ---------------------------------------------------
    permission = ctx.policy.resolve(action)
    what = finding.rel or finding.target or ""
    if permission == "allow":
        return ALLOW(**base)
    if permission == "block":
        return DENY(M.with_guard(M.block_action(label, str(what))), **base)
    return _maybe_headless(ASK(M.with_guard(M.ask_action(label, str(what), action=finding.action)), **base), ctx, label)


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


def resolve(findings: list[Finding], ctx: Ctx) -> Decision:
    """Finding 목록 -> 최종 Decision **하나**. 1회용 허가까지 여기서 본다.

    ### 왜 finding 마다가 아니라 여기인가

    허가의 단위는 **도구 호출 하나**다(지문이 `(도구, 입력)`). 한 호출에서
    승인이 필요한 행동이 둘 이상 나올 수 있다.

        curl -sL https://x/y.sh | pip install peft   ->  net(ask) + pkg(ask)

    `decide()` 안에서 행동마다 허가를 보면 `pkg` 를 승인해도 `net` 이 그대로
    막혀 **승인이 끝나도 루프가 못 나간다.** 게다가 1회용이라 첫 번째 행동이
    허가를 태워 버린다. 그래서 호출 단위로 한 번만 본다.

    ### 순서

    1. 행동마다 `decide()` — 허가는 아직 보지 않는다.
    2. **잠긴 항목(deny)이 하나라도 있으면 허가를 쳐다보지 않는다.**
       승인 1회로 잠금이 열리는 길을 아예 없앤다.
    3. 대화형이면 그대로 둔다 — 허가는 헤드리스에서만 쓴다.
    4. 걸린 ask 를 **전부** 덮는 허가가 있으면 그것들만 allow 로 바꾼다.
    5. `combine()`.
    """
    decisions = [decide(f, ctx) for f in findings]
    if not decisions:
        return DEFER()
    asked = [d for d in decisions if _is_ask(d)]
    out = _with_grant(decisions, asked, ctx)
    winner = combine(out)
    if asked:
        # 무엇이 걸렸는지 전부 싣는다 — 승인 알림·CLI·사유가 같은 목록을 본다.
        winner.meta.setdefault(
            "asked",
            [
                {"action": d.action, "name": d.label, "rel": d.rel}
                for d in asked
            ],
        )
        if len(asked) > 1 and winner.kind in ("ask", "deny"):
            winner.reason = M.add_before_guard(
                winner.reason, M.also_needed([d.label for d in asked])
            )
    for source in out:
        if source.meta.get("grantLog"):
            winner.meta.setdefault("grantLog", source.meta["grantLog"])
        if source.meta.get("grantUsed"):
            winner.meta["grantUsed"] = True
            winner.meta["grant"] = source.meta.get("grant")
    return winner


def _is_ask(decision: Decision) -> bool:
    """승인을 받아야 하는 건이었나.

    헤드리스에서는 `_maybe_headless` 가 이미 deny 로 바꿔 놨으므로
    `originallyAsk` 표식을 같이 본다. 그 표식이 없는 deny 는 **잠긴 항목**이다.
    """
    return decision.kind == "ask" or bool(decision.meta.get("originallyAsk"))


def _locked(decisions: list[Decision]) -> list[Decision]:
    return [d for d in decisions if d.kind == "deny" and not _is_ask(d)]


def _with_grant(
    decisions: list[Decision], asked: list[Decision], ctx: Ctx
) -> list[Decision]:
    """허가가 있으면 ask 였던 것들을 allow 로 바꿔 돌려준다."""
    if not asked or not getattr(ctx, "headless", False):
        return decisions
    if _locked(decisions):
        return decisions  # 잠긴 항목이 섞였다. 허가를 보지도 않는다.

    needs = sorted({(d.action, d.rel or "") for d in asked})
    log: list[dict] = []
    used = grants.consume(
        ctx.name,
        event=ctx.event,
        needs=[(action, rel or None) for action, rel in needs],
        running=bool(getattr(ctx.run, "running", False)),
        appendable=ctx.paths_cfg.get("prevAppendable") or [],
        log=log.append,
    )
    if not used:
        if log:
            decisions[0].meta.setdefault("grantLog", log)
        return decisions

    grant_id = str(used.get("grantId") or "")
    out: list[Decision] = []
    for decision in decisions:
        if not _is_ask(decision):
            out.append(decision)
            continue
        # ⚠ `headlessDeny`·`originallyAsk` 를 **물려받지 않는다.** 그 표식이
        # 남으면 통과한 호출이 승인 요청을 다시 열고 "승인 대기" 알림까지
        # 보낸다 (회귀 테스트: test_25_승인_1회로_호출_전체가_통과한다).
        kept = {
            k: v
            for k, v in decision.meta.items()
            if k not in ("headlessDeny", "originallyAsk")
        }
        out.append(
            ALLOW(
                M.grant_used(decision.label, grant_id),
                label=decision.label,
                action=decision.action,
                rel=decision.rel,
                meta={
                    **kept,
                    "grant": grant_id,
                    "grantUsed": True,
                    "grantLoose": bool(used.get("looseUsed")),
                    "grantLog": log,
                },
            )
        )
    return out


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
