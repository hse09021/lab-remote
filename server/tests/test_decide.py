"""Finding -> Decision 시험."""

import os

import pytest

from app.hooks import decide as D
from app.hooks import messages as M
from app.hooks.classify import Finding


def kind(ctx, finding):
    return D.decide(finding, ctx).kind


def reason(ctx, finding):
    return D.decide(finding, ctx).reason


# --- 우회 금지 지시 ---------------------------------------------------------


@pytest.mark.parametrize(
    "finding",
    [
        Finding("outside", target="/etc/hosts"),
        Finding("selfProtect", rel=".claude/settings.json"),
        Finding("prev", rel="experiments/EXP-006/config.yaml", exp="EXP-006"),
        Finding("prev", rel="experiments/EXP-006/analysis.md", exp="EXP-006"),
        Finding("stop", rel="docs/Evaluation.md"),
        Finding("pkg", target="pip install peft"),
        Finding("net", target="https://x"),
        Finding("suspicious", target="eval ..."),
        Finding("unparsed", target="echo '"),
        Finding("schema-unknown", detail="키 없음"),
        Finding("denied-command", target="claude"),
    ],
)
def test_모든_거절과_승인_사유에_우회_금지가_붙는다(ctx, finding):
    """실측에서 Claude 가 거절당하자 다른 도구로 돌아갔다. 사유로 막는다."""
    decision = D.decide(finding, ctx)
    assert decision.kind in ("deny", "ask"), decision.kind
    assert M.NO_WORKAROUND in decision.reason


def test_허용은_사유가_필요_없다(ctx):
    decision = D.decide(Finding("journal", rel="logs/Decision_log.md"), ctx)
    assert decision.kind == "allow"


# --- 잠긴 3개 + 추가 잠금 ----------------------------------------------------


def test_폴더_밖은_언제나_차단(ctx):
    for mode in ("manual", "error", "full"):
        ctx.policy.set_saved(mode)
        assert kind(ctx, Finding("outside", target="/etc/hosts")) == "deny"


def test_훅_정책_파일_보호(ctx):
    assert kind(ctx, Finding("selfProtect", rel="logs/Approval_log.csv")) == "deny"


def test_이전_실험_폴더는_차단_분석노트는_승인(ctx):
    assert kind(ctx, Finding("prev", rel="experiments/EXP-006/config.yaml", exp="EXP-006")) == "deny"
    assert kind(ctx, Finding("prev", rel="experiments/EXP-006/analysis.md", exp="EXP-006")) == "ask"


def test_종료_조건은_실행_중일_때만_차단(ctx):
    ctx.run.running = True
    ctx.run.experiment_id = "EXP-007"
    decision = D.decide(Finding("stop", rel="docs/Evaluation.md"), ctx)
    assert decision.kind == "deny"
    assert "EXP-007" in decision.reason

    ctx.run.running = False
    assert kind(ctx, Finding("stop", rel="docs/Evaluation.md")) == "ask"


def test_실행_상태_파일이_없으면_승인_경로(ctx):
    """"안 돌고 있음" 으로 보지만 allow 가 아니라 ask 라서 안전하다."""
    assert ctx.run.missing is False  # 픽스처는 기본값
    ctx.run.missing = True
    assert kind(ctx, Finding("stop", rel="specifications/Config.yaml")) == "ask"


# --- 정책 ------------------------------------------------------------------


def test_권한_단계를_따른다(ctx):
    finding = Finding("code", rel="src/train.py")
    ctx.policy.set_saved("manual")
    assert kind(ctx, finding) == "ask"
    ctx.policy.set_saved("error")
    assert kind(ctx, finding) == "allow"
    ctx.policy.set_saved("full")
    assert kind(ctx, finding) == "allow"


def test_기록은_수동제어에서도_허용(ctx):
    """spec IV: 기록은 권한 단계와 상관없이 항상."""
    ctx.policy.set_saved("manual")
    assert kind(ctx, Finding("journal", rel="logs/Experiment_log.csv")) == "allow"


def test_사유에_행동_이름이_한국어로_들어간다(ctx):
    assert "패키지 설치" in reason(ctx, Finding("pkg", target="pip install peft"))


# --- 헤드리스 ---------------------------------------------------------------


def test_헤드리스_기본값은_ask_그대로(ctx):
    ctx.headless = True
    assert ctx.policy.headless["onAsk"] == "ask"
    assert kind(ctx, Finding("pkg", target="pip install peft")) == "ask"


def test_헤드리스_deny_with_reason(ctx):
    ctx.headless = True
    ctx.policy.data["headless"]["onAsk"] = "deny-with-reason"
    decision = D.decide(Finding("pkg", target="pip install peft"), ctx)
    assert decision.kind == "deny"
    assert decision.reason.startswith("[승인 필요: 패키지 설치]")
    assert M.NO_WORKAROUND in decision.reason
    assert decision.meta["headlessDeny"] is True


def test_헤드리스여도_자동_허용으로는_안_넘어간다(ctx):
    """어떤 설정이든 ask 가 allow 로 바뀌면 안 된다."""
    ctx.headless = True
    for mode in ("ask", "deny-with-reason", "wait", "아무거나"):
        ctx.policy.data["headless"]["onAsk"] = mode
        assert kind(ctx, Finding("pkg", target="pip install peft")) in ("ask", "deny")


def test_대화형이면_헤드리스_설정을_안_본다(ctx):
    ctx.headless = False
    ctx.policy.data["headless"]["onAsk"] = "deny-with-reason"
    assert kind(ctx, Finding("pkg", target="pip install peft")) == "ask"


# --- combine ---------------------------------------------------------------


def test_가장_제한적인_것이_이긴다(ctx):
    """EXP-006 의 config.yaml -> prev(deny) + hparam(ask) -> deny."""
    found = [
        Finding("prev", rel="experiments/EXP-006/config.yaml", exp="EXP-006"),
        Finding("hparam", rel="experiments/EXP-006/config.yaml"),
    ]
    assert D.combine([D.decide(f, ctx) for f in found]).kind == "deny"


def test_빈_목록은_defer(ctx):
    assert D.combine([]).kind == "defer"


def test_순위(ctx):
    from app.hooks.emit import ALLOW, ASK, DEFER, DENY

    assert D.combine([ALLOW(), DEFER()]).kind == "defer"
    assert D.combine([ALLOW(), ASK()]).kind == "ask"
    assert D.combine([ASK(), DENY()]).kind == "deny"
