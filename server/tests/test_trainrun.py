"""🏋 학습 직접 실행은 **프리셋과 무관하게** 막는다 (`trainrun`).

## 왜 떼어 냈나 (2026-11-05, 9단계)

`full` 프리셋은 `newexp` 를 **자동 허용**한다. entrypoint 직접 실행이 `newexp`
였으니, `full` 로 올리는 순간 Claude 가 학습을 혼자 돌릴 수 있었다. 그러면 셋이
깨진다.

1. 오케스트레이터의 GPU 큐와 **동시에** GPU 를 쓴다 — `ux_jobs_running` 은
   우리 큐만 지키고 큐 밖의 프로세스는 못 막는다
2. 10분 넘는 Bash 문제가 다시 생긴다
3. `run.json` 검증·샌드박스·타임아웃·체크포인트 회수가 **전부 지나간다**

그래서 `ctx.policy.resolve()` 에 **닿지 않는** 자리에서 끝낸다.
"""

import pytest

from app import grants
from app.hooks import bashparse, decide as decide_mod, messages as M


def actions(ctx, command):
    return sorted(f.action for f in bashparse.classify_with_coverage(command, ctx))


def _decision(ctx, command, *, headless):
    found = bashparse.classify_with_coverage(command, ctx)
    ctx.headless = headless
    ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    return decide_mod.resolve(found, ctx)


def verdict(ctx, command, *, headless=True):
    return _decision(ctx, command, headless=headless).kind


def reason(ctx, command, *, headless=True):
    return _decision(ctx, command, headless=headless).reason


ENTRYPOINT_FORMS = [
    "src/train.py",
    "./src/train.py",
    "bash src/train.py --lr 1e-4",
    "python src/train.py --epochs 3",
    "conda run -n hook-sandbox src/train.py",
    "nohup python src/train.py &",
    "timeout 600 python src/train.py",
]

LAUNCHERS = [
    "torchrun --nproc_per_node 2 anything.py",
    "accelerate launch anything.py",
    "deepspeed anything.py",
    "sbatch job.sh",
    "srun python anything.py",
    "tmux new -d 'python train_loop.py'",
]


@pytest.fixture()
def ready(ctx):
    ctx.policy.data["bash"]["entrypoints"] = ["src/train.py"]
    return ctx


# --- 분류 ------------------------------------------------------------------------


@pytest.mark.parametrize("command", ENTRYPOINT_FORMS)
def test_entrypoint_은_어떤_꼴이든_trainrun(ready, command):
    assert "trainrun" in actions(ready, command), command


@pytest.mark.parametrize("command", LAUNCHERS)
def test_런처는_entrypoint_목록_없이도_trainrun(ctx, command):
    assert ctx.policy.bash["entrypoints"] == []
    assert "trainrun" in actions(ctx, command), command


def test_실험_폴더_만들기는_trainrun_이_아니다(ready):
    """`newexp`(실험 준비)는 그대로다 — `full` 에서 허용되어야 한다."""
    assert "trainrun" not in actions(ready, "mkdir -p experiments/EXP-009")
    assert "trainrun" not in actions(ready, "python src/plot.py")
    assert actions(ready, "python src/plot.py") == ["newexp"]


def test_pytest_와_분석_스크립트는_안_막힌다(ready):
    """여기까지 막으면 C 토막(분석)이 못 돈다."""
    assert "trainrun" not in actions(ready, "pytest tests/")
    assert "trainrun" not in actions(ready, "python src/analyze.py")


# --- 헤드리스: 프리셋과 무관하게 deny ---------------------------------------------


@pytest.mark.parametrize("preset", ["manual", "error", "full"])
@pytest.mark.parametrize("command", ENTRYPOINT_FORMS[:4] + LAUNCHERS[:3])
def test_헤드리스는_어느_프리셋에서도_거절한다(ready, preset, command):
    """**이게 이 파일의 요점이다.** `full` 에서도 열리지 않아야 한다."""
    from app import policy as policy_mod

    ready.policy.set_saved(preset)
    policy_mod.save(ready.policy)
    ready.policy = policy_mod.load(ready.policy.name)
    ready.policy.data["bash"]["entrypoints"] = ["src/train.py"]

    assert verdict(ready, command, headless=True) == "deny", (preset, command)


def test_거절_사유가_run_json_을_가리킨다(ready):
    text = reason(ready, "python src/train.py --epochs 3", headless=True)
    assert "run.json" in text
    assert "명세만" in text
    # 승인으로도 안 열린다는 걸 Claude 에게 알려 준다 — 안 그러면 승인을
    # 기다리며 멈춰 있거나 다른 명령으로 돌아간다
    assert "승인으로도 열리지 않아요" in text


def test_full_에서_newexp_는_여전히_허용된다(ready):
    """실험 준비를 막으면 루프가 못 돈다 — 떼어 낸 것은 학습 실행뿐이다."""
    from app import policy as policy_mod

    ready.policy.set_saved("full")
    policy_mod.save(ready.policy)
    ready.policy = policy_mod.load(ready.policy.name)
    ready.policy.data["bash"]["entrypoints"] = ["src/train.py"]

    assert ready.policy.resolve("newexp") == "allow"
    assert verdict(ready, "python src/plot.py", headless=True) == "allow"


# --- 대화형: ask ----------------------------------------------------------------


def test_대화형은_사람에게_묻는다(ready):
    """사람이 보고 있으면 "지금은 직접 돌리겠다" 가 있을 수 있다."""
    assert verdict(ready, "python src/train.py", headless=False) == "ask"
    text = reason(ready, "python src/train.py", headless=False)
    assert "run.json" in text
    assert "승인해 주세요" in text


# --- 허가로도 안 열린다 ----------------------------------------------------------


def test_허가_목록에_들어_있다():
    """`decide` 가 바로 DENY 하므로 `_ask` 를 지나가지도 않지만, 결과 JSON 의
    `permission_denials` 로 승인 행은 생긴다 — CLI 가 거절해야 한다."""
    assert "trainrun" in grants.LOCKED_ACTIONS


def test_승인_CLI_가_거절한다(conn, project, project_root):
    from app.orchestrator import approvals as AP_ORCH
    from app.store import approvals as AP

    AP.open_request(conn, "hook-sandbox", "toolu_tr", tool="Bash",
                    action_key="trainrun", session_id="s1", source="denials",
                    fingerprint="sha256:x")
    conn.commit()
    with pytest.raises(grants.GrantError):
        AP_ORCH.approve(conn, "hook-sandbox", "toolu_tr")


def test_잠긴_행동_목록에_들어_있다():
    assert "trainrun" in decide_mod.LOCK_ACTIONS


def test_이름이_있다():
    """승인 로그에 `trainrun` 이 그대로 찍히면 사람이 못 읽는다."""
    assert M.LABELS["trainrun"] == "학습 직접 실행"


def test_정책_판단에_닿지_않는다(ready, monkeypatch):
    """`ctx.policy.resolve` 를 부르면 프리셋이 끼어들 틈이 생긴다."""
    called = []
    monkeypatch.setattr(
        type(ready.policy), "resolve",
        lambda self, action: called.append(action) or "allow",
    )
    assert verdict(ready, "python src/train.py", headless=True) == "deny"
    assert "trainrun" not in called
