"""분석(C)이 도는 동안의 잠금 — 실측 2026-11-05 에서 둘이 같이 틀렸다.

학습이 끝나자마자 `set_idle` 이라 `experimentId` 가 `None` 이 됐다. 그러면

1. 방금 끝난 실험이 **"이전 실험"** 이 된다 → C 가 자기 `analysis.md` 를
   쓰려는데 `prev` 잠금에 걸려 승인 대기로 멈췄다.
2. `running` 이 거짓이 되니 **`stop` 잠금도 풀렸다** → 결과를 본 뒤에
   `docs/Evaluation.md` 를 고칠 수 있었다. spec 이 금지하는 바로 그것이다.
"""

import os

from app import loopstate, runstate


def test_분석_중에는_자기_폴더에_쓸_수_있다(project, project_root):
    runstate.set_running("hook-sandbox", "EXP-001", pid=os.getpid())
    runstate.set_idle("hook-sandbox")
    runstate.set_running("hook-sandbox", "EXP-002", pid=os.getpid())

    loopstate.set_reviewing("hook-sandbox", "EXP-002", root=project_root)
    state = runstate.load("hook-sandbox")
    assert state.experiment_id == "EXP-002"
    assert state.running is True
    assert state.stale is False, "pid 가 없다고 좀비로 잡으면 안 돼요"
    assert set(state.started) == {"EXP-001", "EXP-002"}

    current = loopstate.read_current(project_root)
    assert current["current_experiment"] == "EXP-002"
    # 이전 실험만 잠겨 있다고 적혀 있어야 한다
    locked = " ".join(current["locked_now"])
    assert "EXP-001" in locked and "EXP-002/**" not in locked


def test_분석_중에도_평가_기준은_잠겨_있다(project, project_root):
    """결과를 본 뒤에 기준을 바꾸지 않아요 (spec)."""
    loopstate.set_reviewing("hook-sandbox", "EXP-002", root=project_root)
    current = loopstate.read_current(project_root)
    locked = " ".join(current["locked_now"])
    assert "docs/Evaluation.md" in locked
    assert "specifications/Config.yaml" in locked


def test_분석이_끝나면_표시가_내려간다(project, project_root):
    loopstate.set_reviewing("hook-sandbox", "EXP-002", root=project_root)
    loopstate.set_idle("hook-sandbox", root=project_root)
    state = runstate.load("hook-sandbox")
    assert state.running is False and state.experiment_id is None


def _findings(project, project_root, rel):
    """그 파일에 쓰려 할 때 훅이 무엇으로 분류하나 — 지금 runstate 로."""
    from app import runstate as R
    from app.hooks.classify import Ctx, classify_event

    ctx = Ctx(
        root=project_root,
        cwd=project_root,
        name="hook-sandbox",
        policy=project,
        run=R.load("hook-sandbox"),
        event={},
    )
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": os.path.join(project_root, rel), "content": "한 줄"},
        "cwd": project_root,
    }
    return [f.action for f in classify_event(event, ctx)]


def test_분석_중_자기_analysis_는_prev_가_아니다(project, project_root):
    """이게 막혀서 루프가 승인 대기로 멈췄다 (실측 2026-11-05)."""
    runstate.set_running("hook-sandbox", "EXP-001", pid=os.getpid())
    runstate.set_idle("hook-sandbox")
    runstate.set_running("hook-sandbox", "EXP-002", pid=os.getpid())
    loopstate.set_reviewing("hook-sandbox", "EXP-002", root=project_root)

    mine = _findings(project, project_root, "experiments/EXP-002/analysis.md")
    assert "prev" not in mine, mine
    assert "journal" in mine, mine

    # 이전 실험은 **그대로 잠겨 있다**
    old = _findings(project, project_root, "experiments/EXP-001/analysis.md")
    assert "prev" in old, old


def _decision(project, project_root, rel):
    from app import runstate as R
    from app.hooks import decide as D
    from app.hooks.classify import Ctx, Finding

    ctx = Ctx(
        root=project_root,
        cwd=project_root,
        name="hook-sandbox",
        policy=project,
        run=R.load("hook-sandbox"),
        event={},
    )
    return D.decide(Finding("stop", rel=rel), ctx).kind


def test_분석_중_Evaluation_은_막힌다(project, project_root):
    """결과를 본 뒤에 기준을 바꾸지 않아요 — 전에는 여기가 열려 있었다.

    `stop` 은 두 갈래다. 실험 중이면 **deny**, 멈춰 있으면 `ask`(승인 경로).
    학습이 끝나자마자 idle 이 되면 **결과를 보고 나서 승인만 받아 기준을
    고칠 수 있다** — 분석이 끝날 때까지 deny 로 둬야 한다.
    """
    runstate.set_running("hook-sandbox", "EXP-002", pid=os.getpid())
    loopstate.set_reviewing("hook-sandbox", "EXP-002", root=project_root)
    assert _decision(project, project_root, "docs/Evaluation.md") == "deny"
    assert _decision(project, project_root, "specifications/Config.yaml") == "deny"

    # 분석이 끝나면 승인 경로로 내려온다 (사람이 고칠 수 있어야 한다)
    loopstate.set_idle("hook-sandbox", root=project_root)
    assert _decision(project, project_root, "docs/Evaluation.md") == "ask"
