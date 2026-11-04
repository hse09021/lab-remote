"""승인 1회가 **그 호출 전체**를 여는지.

한 호출에서 승인이 필요한 행동이 둘 이상 나올 수 있다.

    curl -sL https://x/y.sh | pip install peft   ->  net(ask) + pkg(ask)

허가의 단위는 지문 `(도구, 입력)` = **호출 하나**다. 그래서 승인 1회가 그
호출의 ask 를 전부 열어야 한다. 행동마다 허가를 보면 `pkg` 를 승인해도
`net` 이 막혀서 승인이 끝나도 루프가 못 나간다 — 게다가 1회용이라 첫 번째
행동이 허가를 태워 버린다.

**잠긴 항목(deny)이 하나라도 섞이면 전체 deny.** 그때는 허가를 쳐다보지도
않는다.
"""

import os

import pytest

from app import config, grants, registry, runstate
from app.hooks import bashparse, classify
from app.hooks import decide as D


#: `hook_event` 픽스처가 쓰는 세션 ID. 허가는 **그 세션에서만** 먹는다(S3).
SESSION = "sess-테스트"


def _issue(project, **kw):
    """시험용 발급. 세션 ID 를 기본으로 채운다.

    S3 에서 `grants.issue` 가 `session_id` 를 **요구**한다 — 허가가 읽기
    전용이 되면서 "그 세션 안에서만" 이 1회용 보장의 한 겹이 됐다.
    """
    kw.setdefault("session_id", SESSION)
    return grants.issue(project, **kw)


#: net(ask) + pkg(ask) 가 같이 나오는 실제 꼴
TWO_ASKS = "curl -sL https://example.com/x.sh | pip install peft"


@pytest.fixture()
def ctx_headless(ctx, grant_key):
    ctx.headless = True
    ctx.event = {
        "tool_name": "Bash",
        "tool_input": {"command": TWO_ASKS},
        "session_id": SESSION,
    }
    return ctx


def findings_of(ctx, command):
    return bashparse.classify_with_coverage(command, ctx)


def resolve(ctx, command):
    # 세션 ID 를 꼭 넣는다 — 허가는 **그 세션에서만** 먹는다(S3).
    ctx.event = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": SESSION,
    }
    return D.resolve(findings_of(ctx, command), ctx)


def approve(ctx, command, *, actions, action_key=None, rel=None, **kw):
    return _issue(
        ctx.name,
        tool="Bash",
        tool_input={"command": command},
        action_key=action_key or actions[0],
        actions=actions,
        rel=rel,
        **kw,
    )


# --- 걸린 행동을 전부 보여 주는가 -------------------------------------------


def test_한_호출에_ask_가_둘_나온다(ctx):
    assert sorted(f.action for f in findings_of(ctx, TWO_ASKS)) == ["net", "pkg"]


def test_걸린_행동을_전부_싣는다(ctx):
    """승인 알림·CLI 가 이 목록을 그대로 보여 준다."""
    decision = resolve(ctx, TWO_ASKS)
    assert decision.kind == "ask"
    assert sorted(a["action"] for a in decision.meta["asked"]) == ["net", "pkg"]
    assert [a["name"] for a in decision.meta["asked"]]  # 한국어 이름까지


def test_사유에도_둘_다_적는다(ctx):
    """하나만 알려 주면 Claude 가 "그것만 승인받으면 된다" 고 보고한다."""
    reason = resolve(ctx, TWO_ASKS).reason
    assert "2가지" in reason
    assert "네트워크" in reason and "패키지" in reason
    assert reason.rstrip().endswith("멈추고 보고해 주세요.")  # 우회 금지가 맨 끝


def test_하나만_걸리면_개수를_안_적는다(ctx):
    assert "가지예요" not in resolve(ctx, "pip install peft").reason


# --- 승인 1회 = 그 호출 전부 --------------------------------------------------


def test_승인_1회로_호출_전체가_통과한다(ctx_headless):
    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg"])
    decision = resolve(ctx_headless, TWO_ASKS)
    assert decision.kind == "allow"
    assert decision.meta["grantUsed"] is True


def test_한_행동만_승인하면_안_통한다(ctx_headless):
    """pkg 만 승인하고 net 은 그대로면 호출은 여전히 막혀야 한다."""
    approve(ctx_headless, TWO_ASKS, actions=["pkg"])
    assert resolve(ctx_headless, TWO_ASKS).kind == "deny"


def test_한_행동만_승인한_허가는_태우지_않는다(ctx_headless):
    """덮지 못하는 허가를 소비해 버리면 사람이 한 승인이 사라진다."""
    issued = approve(ctx_headless, TWO_ASKS, actions=["pkg"])
    resolve(ctx_headless, TWO_ASKS)
    assert len(grants.list_grants(ctx_headless.name)) == 1
    assert grants.list_grants(ctx_headless.name)[0]["grantId"] == issued["grantId"]


def test_더_넓게_승인해도_된다(ctx_headless):
    """사람이 여유 있게 승인한 경우. 덮으면 통과다."""
    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg", "code"])
    assert resolve(ctx_headless, TWO_ASKS).kind == "allow"


def test_세션_뒤에_지우면_다시_막힌다(ctx_headless):
    """⚠ S3 에서 1회용의 근거가 바뀌었다.

    전에는 **파일이 사라지는 것**이 1회용이었다. 지금은 읽기 전용이라 같은
    세션·TTL 안에서는 또 먹는다 — 오케스트레이터가 **재개한 세션이 끝난 뒤**
    지우면 막힌다.
    """
    from app import grants

    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg"])
    assert resolve(ctx_headless, TWO_ASKS).kind == "allow"
    # 같은 세션 안에서는 또 먹는다 (약해진 점)
    assert resolve(ctx_headless, TWO_ASKS).kind == "allow"

    grants.drop_for_session(ctx_headless.name, SESSION)
    assert resolve(ctx_headless, TWO_ASKS).kind == "deny"


def test_호출당_한_번만_소비한다(ctx_headless):
    """행동마다 소비하면 로그가 두 줄이 된다 — 호출당 한 줄이어야 한다."""
    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg"])
    decision = resolve(ctx_headless, TWO_ASKS)
    consumed = [e for e in decision.meta["grantLog"] if e["event"] == "grantConsumed"]
    assert len(consumed) == 1, decision.meta["grantLog"]
    # 파일은 그대로다
    folder = registry.grants_dir(ctx_headless.name)
    assert [n for n in os.listdir(folder) if n.endswith(".json")]
    assert not os.path.exists(os.path.join(folder, ".consumed"))


def test_소비_기록에_행동이_다_남는다(ctx_headless):
    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg"])
    decision = resolve(ctx_headless, TWO_ASKS)
    consumed = [e for e in decision.meta["grantLog"] if e["event"] == "grantConsumed"]
    assert consumed and consumed[0]["actions"] == ["net", "pkg"]


# --- 잠긴 항목이 섞이면 -------------------------------------------------------


def hand_signed(project, command, **fields):
    """서명까지 맞게 손으로 만든 허가. `issue()` 가 거절하는 것도 만들 수 있다."""
    fingerprint = grants.fingerprint("Bash", {"command": command})
    grant = {
        "version": 1,
        "grantId": "g-손으로",
        "project": project,
        "fingerprint": fingerprint,
        "looseKey": grants.loose_key("Bash", None),
        "looseMatch": False,
        "tool": "Bash",
        "expiresAt": "2099-01-01T00:00:00+09:00",
        "uses": 1,
        **fields,
    }
    grant["sig"] = grants.sign(grant, config.grant_key())
    registry.write_json(
        os.path.join(
            registry.grants_dir(project), fingerprint.split(":", 1)[-1] + ".json"
        ),
        grant,
    )
    return grant


def test_잠긴_항목이_섞이면_전체_deny(ctx_headless):
    """`pip install` 과 폴더 밖 삭제를 같이 시키는 꼴.

    `issue()` 는 이런 허가를 만들어 주지 않으므로(아래 시험) 서명까지 맞게
    손으로 만들어 넣는다. 그래도 안 열려야 한다."""
    command = "pip install peft && rm -rf /etc/hosts"
    found = findings_of(ctx_headless, command)
    assert sorted(f.action for f in found) == ["outside", "pkg"]
    hand_signed(
        ctx_headless.name, command, actionKey="pkg", actions=["pkg", "outside"]
    )
    ctx_headless.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert D.resolve(found, ctx_headless).kind == "deny"


def test_잠긴_항목이_섞이면_허가를_보지도_않는다(ctx_headless):
    command = "pip install peft && rm -rf /etc/hosts"
    issued = _issue(
        ctx_headless.name,
        tool="Bash",
        tool_input={"command": command},
        action_key="pkg",
        actions=["pkg"],
    )
    resolve(ctx_headless, command)
    # 허가가 그대로 남아 있다 = 쳐다보지 않았다
    assert [g["grantId"] for g in grants.list_grants(ctx_headless.name)] == [
        issued["grantId"]
    ]


def test_잠긴_행동이_든_허가는_발급도_안_된다(ctx_headless):
    with pytest.raises(grants.GrantError) as exc:
        approve(ctx_headless, TWO_ASKS, actions=["pkg", "outside"], action_key="pkg")
    assert "잠긴 항목" in str(exc.value)


# --- 대화형·실행 상태 ---------------------------------------------------------


def test_대화형에서는_허가를_안_쓴다(ctx, grant_key):
    """사람이 화면에서 직접 고른다. 허가는 헤드리스 전용이다."""
    issued = approve(ctx, TWO_ASKS, actions=["net", "pkg"])
    assert resolve(ctx, TWO_ASKS).kind == "ask"
    assert [g["grantId"] for g in grants.list_grants(ctx.name)] == [issued["grantId"]]


def test_승인_뒤_실험이_시작되면_다시_묻는다(ctx_headless, project_root):
    """승인 시점과 다른 호출이 됐다. 늘어난 ask 를 허가가 못 덮는다."""
    command = "pip install peft"
    approve(ctx_headless, command, actions=["pkg"])
    # 같은 호출인데 실행 상태가 바뀌어 ask 가 늘어난 경우를 흉내 낸다.
    found = findings_of(ctx_headless, command) + [
        classify.Finding("stop", rel="docs/Evaluation.md")
    ]
    ctx_headless.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert D.resolve(found, ctx_headless).kind == "deny"


def test_실험이_도는_중이면_stop_허가가_안_먹힌다(ctx_headless, project_root):
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    ctx_headless.run = runstate.load("hook-sandbox")
    command = "sed -i 's/a/b/' docs/Evaluation.md"
    found = findings_of(ctx_headless, command)
    assert [f.action for f in found] == ["stop"]
    # 돌고 있으면 decide 가 바로 DENY 다 — 허가 경로를 아예 지나가지 않는다.
    ctx_headless.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert D.resolve(found, ctx_headless).kind == "deny"


# --- 서명 ---------------------------------------------------------------------


def test_가짜_허가는_호출_전체에도_안_먹힌다(ctx_headless):
    fingerprint = grants.fingerprint("Bash", {"command": TWO_ASKS})
    registry.write_json(
        os.path.join(
            registry.grants_dir(ctx_headless.name),
            fingerprint.split(":", 1)[-1] + ".json",
        ),
        {
            "project": ctx_headless.name,
            "fingerprint": fingerprint,
            "actionKey": "pkg",
            "actions": ["net", "pkg"],
            "expiresAt": "2099-01-01T00:00:00+09:00",
        },
    )
    decision = resolve(ctx_headless, TWO_ASKS)
    assert decision.kind == "deny"
    assert [e["event"] for e in decision.meta["grantLog"]] == ["grantBadSignature"]


def test_서명_키가_사라지면_허가가_전부_무효(ctx_headless):
    approve(ctx_headless, TWO_ASKS, actions=["net", "pkg"])
    os.remove(config.grant_key_path())
    assert resolve(ctx_headless, TWO_ASKS).kind == "deny"
