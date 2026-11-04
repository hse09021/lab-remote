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


def test_헤드리스_기본값은_거절(ctx):
    """실측(2026-11-04): `claude -p` 의 ask 는 사람에게 안 가고 10초 안에 자동
    거부된다. 기다려 주지 않으니 우리가 사유를 붙여 먼저 막는다."""
    ctx.headless = True
    assert ctx.policy.headless["onAsk"] == "deny-with-reason"
    assert kind(ctx, Finding("pkg", target="pip install peft")) == "deny"


def test_헤드리스_설정이_없어도_거절(ctx):
    """정책 파일에 키가 없는 경우에도 열리면 안 된다."""
    ctx.headless = True
    ctx.policy.data["headless"] = {}
    assert kind(ctx, Finding("pkg", target="pip install peft")) == "deny"


def test_헤드리스_deny_with_reason(ctx):
    ctx.headless = True
    ctx.policy.data["headless"]["onAsk"] = "deny-with-reason"
    decision = D.decide(Finding("pkg", target="pip install peft"), ctx)
    assert decision.kind == "deny"
    assert decision.reason.startswith("[승인 필요: 패키지 설치]")
    assert "승인 요청을 남겨 두었어요" in decision.reason
    assert M.NO_WORKAROUND in decision.reason
    assert decision.meta["headlessDeny"] is True


def test_헤드리스_ask_로_되돌릴_수_있다(ctx):
    """정책으로 옛 동작(앱에 맡김)을 고를 수는 있다. 자동 허용만 안 된다."""
    ctx.headless = True
    ctx.policy.data["headless"]["onAsk"] = "ask"
    assert kind(ctx, Finding("pkg", target="pip install peft")) == "ask"


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


# --- 판 2 에서 늘어난 잠금 ---------------------------------------------------


def test_보호_목록은_항상_차단(ctx):
    decision = D.decide(Finding("hardProtect", target="/home/u/.claude.json"), ctx)
    assert decision.kind == "deny"
    assert "어떤 권한 설정에서도" in decision.reason
    assert decision.action in D.LOCK_ACTIONS


def test_비밀_파일은_항상_차단(ctx):
    decision = D.decide(Finding("secret", target="/home/u/p/.env"), ctx)
    assert decision.kind == "deny"
    assert "환경 변수 이름만" in decision.reason
    assert decision.action in D.LOCK_ACTIONS


def test_산출물_보존은_항상_차단(ctx):
    decision = D.decide(
        Finding(
            "outputProtect",
            rel="experiments/EXP-002/output/train.log",
            exp="EXP-002",
            detail="지우거나 비우거나 덮어쓸",
        ),
        ctx,
    )
    assert decision.kind == "deny"
    assert "EXP-002" in decision.reason
    assert decision.action in D.LOCK_ACTIONS


def test_새_잠금은_권한_프리셋을_안_본다(ctx):
    """"연구 전체 자동화" 로 올려도 열리면 안 된다."""
    ctx.policy.data["saved"] = {"mode": "full", "overrides": {}}
    for action in ("hardProtect", "secret", "outputProtect"):
        assert kind(ctx, Finding(action, rel="x", target="/x", exp="EXP-001")) == "deny"


def test_새_잠금은_헤드리스에서도_차단(ctx):
    ctx.headless = True
    assert kind(ctx, Finding("secret", target="/home/u/p/.env")) == "deny"


def test_기록_허용보다_산출물_보존이_이긴다(ctx):
    """result.csv 삭제 -> journal(allow) + outputProtect(deny) -> deny."""
    found = [
        Finding("journal", rel="experiments/EXP-002/result.csv"),
        Finding("outputProtect", rel="experiments/EXP-002/result.csv", exp="EXP-002",
                detail="지우거나 옮길"),
    ]
    assert D.combine([D.decide(f, ctx) for f in found]).kind == "deny"


# --- 미분류 조각 (①의 경계 버그) ---------------------------------------------
# 실측에서 훅이 아래 명령에 **allow** 를 줬다. 앞 조각(`echo > src/…`)만 `code`
# 로 분류되고 `conda run` 쪽은 findings 에 아무것도 보태지 않아서, 사람에게
# 묻지도 않고 프로젝트 밖 삭제가 실행될 수 있었다. 대화형·헤드리스 둘 다 고정한다.

COMPOSITE_BYPASS = (
    "echo probe > src/sbx_t.txt && conda run -n base rm -rf /home/사용자/sbx-victim"
)


def composite(ctx):
    from app.hooks import bashparse

    found = bashparse.classify_with_coverage(COMPOSITE_BYPASS, ctx)
    assert [f.action for f in found] == ["code", "unclassified"]
    return D.combine([D.decide(f, ctx) for f in found])


@pytest.mark.parametrize("mode", ["manual", "error", "full"])
def test_미분류_조각이_섞이면_대화형은_allow_가_아니다(ctx, mode):
    """`code` 가 allow 인 프리셋에서도 전체가 열리면 안 된다. 최소 defer."""
    ctx.policy.set_saved(mode)
    ctx.headless = False
    decision = composite(ctx)
    assert decision.kind != "allow"
    assert decision.kind in ("defer", "ask")


def test_미분류_조각이_섞이면_헤드리스는_승인_경로로(ctx):
    """헤드리스에서 defer 는 통과가 아니라 정지(tool_deferred)다. ask 로 올린다."""
    ctx.policy.set_saved("full")  # code -> allow (실측 조건 그대로)
    ctx.headless = True
    decision = composite(ctx)
    assert decision.kind == "deny"
    assert decision.meta["originallyAsk"] is True  # ask 에서 온 거절 -> requests/
    assert "승인 요청을 남겨 두었어요" in decision.reason


def test_미분류_하나만_있을_때_대화형은_defer(ctx):
    """`ls` 처럼 아는 게 없는 명령. 대화형은 Claude Code 승인 흐름에 맡긴다."""
    assert kind(ctx, Finding("unclassified", target="ls -la")) == "defer"


def test_미분류_하나만_있을_때_헤드리스는_ask(ctx):
    ctx.headless = True
    ctx.policy.data["headless"]["onAsk"] = "ask"
    decision = D.decide(Finding("unclassified", target="ls -la"), ctx)
    assert decision.kind == "ask"
    assert "알지 못해요" in decision.reason
    assert M.NO_WORKAROUND in decision.reason


def test_미분류는_헤드리스에서도_자동_허용으로_안_넘어간다(ctx):
    ctx.headless = True
    for mode in ("ask", "deny-with-reason", "wait", "아무거나"):
        ctx.policy.data["headless"]["onAsk"] = mode
        assert kind(ctx, Finding("unclassified", target="ls -la")) in ("ask", "deny")


def test_미분류는_잠금이_아니다(ctx):
    """잠긴 항목과 섞이면 잠금이 이긴다 — 판정 순서가 뒤바뀌지 않게."""
    found = [
        Finding("unclassified", target="conda run -n base ls"),
        Finding("outside", target="/etc/hosts"),
    ]
    assert D.combine([D.decide(f, ctx) for f in found]).kind == "deny"
    assert "unclassified" not in D.LOCK_ACTIONS


def test_combine_은_미분류가_섞이면_allow_를_안_준다():
    """순위표가 바뀌어도 안 열리게 둔 불변식."""
    from app.hooks.emit import ALLOW

    out = D.combine([ALLOW(action="code"), ALLOW(action="unclassified")])
    assert out.kind == "defer"
    assert out.action == "unclassified"
