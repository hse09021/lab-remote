"""루프 한 바퀴 — A(설계) → B(실행) → C(분석).

**Claude 를 안 띄우고** 돌린다. `LoopCtx` 가 띄우는 것들을 주입받아서,
가짜 Claude + 가짜 학습으로 루프를 완주시킨다 (계획의 결정).
"""

import json
import os
import shutil

import pytest

from app import loopstate, registry, runstate
from app.orchestrator import gitflow, guards
from app.orchestrator.__main__ import once
from app.orchestrator.loop import next_experiment_id, update_order
from app.orchestrator.runner_ctx import LoopCtx
from app.runner import process as process_mod
from app.runner import spec as spec_mod
from app.store import events as E
from app.store import experiments as X
from app.store import jobs as J
from app.store import loops as LP

FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_train.py")


# --- 가짜 주변 장치 -------------------------------------------------------------


class FakeClaude:
    """`claude -p` 대신. 호출마다 미리 정한 답을 돌려주고, 부수효과를 남긴다."""

    def __init__(self, project_root):
        self.root = project_root
        self.calls = []
        self.on_plan = None
        self.on_review = None
        self.on_resume = None

    def __call__(self, made):
        prompt = made["argv"][-1]
        self.calls.append({"prompt": prompt, "argv": made["argv"], "env": made["env"]})
        if "설계 (A)" in prompt:
            text = self.on_plan(self.root, prompt) if self.on_plan else ""
        elif "승인이 났어요" in prompt:
            text = self.on_resume(self.root, prompt) if self.on_resume else "이어서 했어요"
        else:
            text = self.on_review(self.root, prompt) if self.on_review else ""
        return {"ok": True, "text": text, "stopReason": "end_turn", "raw": text}


def write_config(root, *, entrypoints, threshold="1.5", limits=""):
    listed = ", ".join(entrypoints)
    body = "\n".join(
        [
            "goal:",
            "  metric: loss",
            '  threshold: "' + str(threshold) + '"',
            "",
            "limits:",
            (limits.rstrip("\n") if limits else "  max_runs: 20"),
            "",
            "env:",
            '  conda: "[환경 이름]"',
            "",
            "run:",
            "  entrypoints: [" + listed + "]",
            "  envAllow: []",
            "  resumeArg: --resume-from",
            "  timeoutSec: 120",
            "  graceSec: 2",
            "",
        ]
    )
    path = os.path.join(root, "specifications", "Config.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def exp_id_of(prompt):
    """프롬프트에서 실험 ID 를 뽑는다 (`` `experiments/EXP-001/` `` 처럼 적혀 있다)."""
    import re

    found = re.search(r"EXP-[0-9]{3,}", prompt)
    assert found, prompt[:200]
    return found.group(0)


def plan_writes_run_json(root, prompt):
    """AI 가 `run.json` 을 쓰는 걸 흉내 낸다."""
    exp_id = exp_id_of(prompt)
    folder = os.path.join(root, "experiments", exp_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"entrypoint": "src/train.py", "args": ["--epochs", "2", "--out", folder]}, fh)
    with open(os.path.join(folder, "config.yaml"), "w", encoding="utf-8") as fh:
        fh.write("lr: 1e-4\n")
    return f"{exp_id} 를 설계했어요"


def review_writes_journal(root, prompt, *, success="충족"):
    """AI 가 Update Order 를 채우고 Final Report 를 적는 걸 흉내 낸다."""
    exp_id = exp_id_of(prompt)
    folder = os.path.join(root, "experiments", exp_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "analysis.md"), "w", encoding="utf-8") as fh:
        fh.write("# 분석\n잘 됐어요.\n")
    for rel, text in (
        ("logs/Experiment_log.csv", f"{exp_id},done\n"),
        ("logs/Decision_log.md", f"- {exp_id} 를 돌렸어요\n"),
        ("state/State.yaml", f"current_experiment: {exp_id}\n"),
    ):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    return (
        "분석을 마쳤어요.\n\n## Final Report\n"
        f"- 실험 ID: {exp_id}\n- 검증한 가설: 된다\n- 변경한 조작변인: lr\n"
        "- 실행 상태: 정상 종료\n- 주요 결과: loss 1.0\n"
        f"- 성공 기준 충족 여부: {success}\n- 생성·수정한 파일: result.csv\n"
        "- 다음 행동: 다음 실험\n- 사람의 검토 필요 여부: 아니요\n"
    )


@pytest.fixture(autouse=True)
def healthy_gpu(monkeypatch):
    """루프 시험은 GPU 와 무관하다. 드라이버는 정상이라고 둔다 —
    **가드 자체**는 `test_orchestrator_guards.py` 에서 따로 잰다."""
    from app.monitor import gpu

    monkeypatch.setattr(
        gpu,
        "driver_state",
        lambda: {"ok": True, "kernel": "595", "userland": "595", "mismatch": False,
                 "rebootPending": False, "rebootPackages": [], "reason": "", "exitCode": 0},
    )


@pytest.fixture()
def ready(project, project_root, sandboxed, conn):
    os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
    shutil.copy(FAKE, os.path.join(project_root, "src", "train.py"))
    for sub in ("logs", "state", "experiments"):
        os.makedirs(os.path.join(project_root, sub), exist_ok=True)
    # 공통 픽스처가 만들어 두는 빈 EXP-007 을 치운다 — 번호가 008 부터 시작한다
    shutil.rmtree(os.path.join(project_root, "experiments", "EXP-007"), ignore_errors=True)
    write_config(project_root, entrypoints=["src/train.py"])
    registry.register(project_root, "hook-sandbox")
    LP.ensure(conn, "hook-sandbox")
    return project_root


@pytest.fixture()
def fake(ready):
    claude = FakeClaude(ready)
    claude.on_plan = plan_writes_run_json
    claude.on_review = review_writes_journal
    return claude


def ctx_for(root, claude, **kw):
    return dict(
        preset="full",
        runner=claude,
        launcher=lambda spec: process_mod.launch(spec, use_sandbox=False, cache_dir=""),
        waiter=lambda launched, spec: process_mod.wait(
            launched, timeout_sec=spec.timeout_sec, grace_sec=1, poll_sec=0.05
        ),
        **kw,
    )


# --- 루프 1회 완주 ---------------------------------------------------------------


def test_루프_한_바퀴를_완주한다(conn, ready, fake):
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is True, got
    assert got["experimentId"] == "EXP-001"
    assert [s["stage"] for s in got["steps"]] == ["plan", "train", "review"]


def test_Claude_를_두_번만_띄운다(conn, ready, fake):
    """A 와 C 뿐이다. **B 는 Claude 가 끼지 않는다.**"""
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert len(fake.calls) == 2
    assert "설계 (A)" in fake.calls[0]["prompt"]
    assert "분석 (C)" in fake.calls[1]["prompt"]


def test_학습_산출물이_남는다(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    exp = os.path.join(ready, "experiments", "EXP-001")
    assert os.path.exists(os.path.join(exp, "result.csv"))
    assert os.path.exists(os.path.join(exp, "output", "train.log"))
    assert process_mod.read_exit_code(os.path.join(exp, "output", "exit_code")) == 0


def test_실험_기록이_DB_에_남는다(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    row = X.get(conn, "hook-sandbox", "EXP-001")
    assert row["state"] == "done"
    assert row["metric_value"] is not None
    assert row["gpu_sec"] >= 0
    assert LP.get(conn, "hook-sandbox")["loop_no"] == 1


def test_실행_중_표시가_켜졌다_꺼진다(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert runstate.load("hook-sandbox").running is False
    # 한 번이라도 시작된 실험은 영구히 남는다
    assert "EXP-001" in (runstate.load("hook-sandbox").started or [])
    current = loopstate.read_current(ready)
    assert current["running"] is False
    assert "EXP-001" in current["started_experiments"]


def test_두_바퀴_돌면_실험_번호가_올라간다(conn, ready, fake):
    assert once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))["experimentId"] == "EXP-001"
    assert once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))["experimentId"] == "EXP-002"


def test_시작된_번호를_다시_쓰지_않는다(conn, ready):
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    runstate.set_idle("hook-sandbox")
    assert next_experiment_id(conn, "hook-sandbox", ready) == "EXP-008"


# --- 종료 조건 (AI 의 말을 믿지 않는다) -------------------------------------------


def test_최대_실행_횟수에_닿으면_멈춘다(conn, ready, fake):
    write_config(ready, entrypoints=["src/train.py"], limits="  max_runs: 1\n")
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False and got["stoppedAt"] == "plan"
    assert "최대 실행 횟수" in got["steps"][0]["reason"]
    assert LP.get(conn, "hook-sandbox")["state"] == "stopped"


def test_GPU_시간을_다_쓰면_멈춘다(conn, ready, fake):
    """누적치를 본다 — 가짜 학습은 금방 끝나니 쓴 시간을 손으로 채워 넣는다."""
    write_config(ready, entrypoints=["src/train.py"], limits="  gpu_hours: 1\n")
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    X.upsert(conn, "hook-sandbox", "EXP-001", gpu_sec=2 * 3600)  # 2시간 썼다고 치자
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False
    assert "GPU 시간" in got["steps"][0]["reason"]
    assert got["steps"][0]["stop"] is True


def test_마감이_지나면_멈춘다(conn, ready, fake):
    write_config(ready, entrypoints=["src/train.py"], limits='  deadline: "2020-01-01"\n')
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert "마감" in got["steps"][0]["reason"]
    assert got["steps"][0]["stop"] is True


def test_사람이_멈춰_두면_안_돈다(conn, ready, fake):
    LP.pause(conn, "hook-sandbox", reason="잠깐 멈춰요")
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False
    assert "사람이 멈춰 뒀어요" in got["steps"][0]["reason"]
    assert fake.calls == []  # Claude 를 아예 안 띄운다


def test_자리표시_종료_조건은_없는_것으로_본다(conn, ready, fake):
    write_config(ready, entrypoints=["src/train.py"], limits='  max_runs: "[최대 실행 횟수]"\n')
    assert once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))["ok"] is True


# --- AI 의 말과 숫자를 대조한다 (spec III-4) ---------------------------------------


def test_판정이_어긋나면_멈추고_사람을_부른다(conn, ready, fake):
    """`result.csv` 의 loss 는 임계값을 못 넘었는데 AI 가 "충족" 이라고 적은 경우."""
    write_config(ready, entrypoints=["src/train.py"], threshold="0.0001")
    fake.on_review = lambda root, prompt: review_writes_journal(root, prompt, success="충족")
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False
    review = got["steps"][-1]
    assert review["disagree"] is True
    assert review["saidSuccess"] is True and review["numbers"]["success"] is False
    assert LP.get(conn, "hook-sandbox")["state"] == "blocked"


def test_판정이_맞으면_그냥_간다(conn, ready, fake):
    write_config(ready, entrypoints=["src/train.py"], threshold="99")
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    review = got["steps"][-1]
    assert review["disagree"] is False
    assert review["numbers"]["success"] is True


def test_임계값이_자리표시면_대조하지_않는다(conn, ready, fake):
    write_config(ready, entrypoints=["src/train.py"], threshold="[임계값]")
    review = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))["steps"][-1]
    assert review["numbers"]["threshold"] is None
    assert review["disagree"] is False


# --- Update Order 검수 ------------------------------------------------------------


def test_기록이_빠지면_알아챈다(conn, ready, fake):
    fake.on_review = lambda root, prompt: "## Final Report\n- 실험 ID: EXP-001\n"
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    order = got["steps"][-1]["updateOrder"]
    assert order["ok"] is False
    assert "analysis.md" in order["missing"]
    assert got["ok"] is False


def test_기록이_다_있으면_통과(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert update_order(ready, "EXP-001")["ok"] is True


# --- run.json 이 보안 경계다 --------------------------------------------------------


def test_허락_안_된_entrypoint_면_안_돌린다(conn, ready, fake):
    def bad_plan(root, prompt):
        exp_id = exp_id_of(prompt)
        folder = os.path.join(root, "experiments", exp_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "run.json"), "w", encoding="utf-8") as fh:
            json.dump({"entrypoint": "/bin/sh", "args": ["-c", "echo 나쁜짓"]}, fh)
        return "설계했어요"

    fake.on_plan = bad_plan
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False and got["stoppedAt"] == "train"
    assert "허락된 entrypoint" in got["steps"][1]["reason"]
    assert X.get(conn, "hook-sandbox", "EXP-001")["state"] == "failed"


def test_run_json_이_없으면_안_돌린다(conn, ready, fake):
    fake.on_plan = lambda root, prompt: "설계만 하고 run.json 을 안 썼어요"
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False and got["stoppedAt"] == "train"
    assert "run.json 이 없어요" in got["steps"][1]["reason"]


# --- 띄우는 인자 ------------------------------------------------------------------


def test_헤드리스로_띄운다(conn, ready, fake):
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    argv = fake.calls[0]["argv"]
    assert "--permission-prompts" in argv and "none" in argv
    assert argv[argv.index("--disallowedTools") + 1] == "Task"
    assert fake.calls[0]["env"]["LABREMOTE_HEADLESS"] == "1"
    assert "ANTHROPIC_API_KEY" not in fake.calls[0]["env"]


def test_세션_ID_를_미리_정한다(conn, ready, fake):
    from app.agent import session

    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    argv = fake.calls[0]["argv"]
    assert session.is_valid(argv[argv.index("--session-id") + 1])


# --- 승인 대기 → 허가 → 이어 가기 (계획 6-1) --------------------------------------


def make_request(project_root, command="pip install peft", request_id="toolu_1"):
    """훅이 헤드리스에서 막았을 때 남기는 요청 파일을 그대로 흉내 낸다."""
    from app import approval_log as A
    from app import grants

    A.open_request(
        "hook-sandbox",
        request_id,
        {
            "tool": "Bash",
            "action": "패키지 설치",
            "actionKey": "pkg",
            "actions": [{"action": "pkg", "name": "패키지 설치"}],
            "request": command,
            "reason": "패키지 설치는 승인이 필요해요",
            "fingerprint": grants.fingerprint("Bash", {"command": command}),
            "looseKey": grants.loose_key("Bash", None),
            "toolSummary": {"command": command},
            "sessionId": "0f0c",
        },
    )


def test_승인을_기다리면_거기서_멈춘다(conn, ready, fake):
    def plan_then_block(root, prompt):
        make_request(root)
        return "pip install 을 하려다 막혔어요"

    fake.on_plan = plan_then_block
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False and got["stoppedAt"] == "approval"
    assert LP.get(conn, "hook-sandbox")["state"] == "waiting_approval"
    # 학습은 시작하지 않았다
    assert J.listing(conn, "hook-sandbox", states=("running",)) == []


def test_승인하면_이어_간다(conn, ready, fake, grant_key):
    """처음부터 다시 돌리지 않고 `--resume` 으로 이어 간다."""
    from app import approval_log as A
    from app.orchestrator import approvals as AP

    blocked = {"done": False}

    def plan_once(root, prompt):
        if not blocked["done"]:
            blocked["done"] = True
            make_request(root)
            return "막혔어요"
        return plan_writes_run_json(root, prompt)

    def resume_writes(root, prompt):
        """사람이 승인했다. 훅이 허가를 소비하면 요청 파일이 닫힌다."""
        A.close_request("hook-sandbox", "toolu_1", result="소비됨")
        plan_writes_run_json(root, "experiments/EXP-001/")
        return "이어서 했고 run.json 까지 썼어요"

    fake.on_plan = plan_once
    fake.on_resume = resume_writes

    # 1) 막힌다. **승인 전에는 다시 안 띄운다** — 같은 자리에서 또 막힐 뿐이다.
    first = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert first["stoppedAt"] == "approval"
    assert [c for c in fake.calls if "승인이 났어요" in c["prompt"]] == []

    # 2) 사람이 승인한다
    AP.sync(conn, "hook-sandbox")
    grant = AP.approve(conn, "hook-sandbox", "toolu_1")
    assert grant["actions"] == ["pkg"]

    # 3) 다음 바퀴에서 `--resume` 으로 이어 가고 완주한다
    second = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert second["ok"] is True, second
    assert second["experimentId"] == "EXP-001"  # 새 실험을 또 만들지 않았다
    resumed = [c for c in fake.calls if "승인이 났어요" in c["prompt"]]
    assert resumed, [c["prompt"][:30] for c in fake.calls]
    argv = resumed[0]["argv"]
    assert "--resume" in argv and "--session-id" not in argv


def test_이어_갈_때_같은_입력을_쓰라고_못박는다(conn, ready, fake, grant_key):
    from app.agent import prompts

    text = prompts.render(
        "resume_after_approval", {"request": "pip install peft", "actions": "패키지 설치", "context": ""}
    )
    assert "같은 도구·같은 입력으로 한 번만" in text
    assert "한 번 쓰면 사라지니" in text


def test_같은_요청이_반복되면_알아챈다(conn, ready, fake):
    """무한 반복 방지 — 상한을 넘으면 사람이 봐야 한다."""
    from app.orchestrator import approvals as AP
    from app.store import approvals as APS

    make_request(ready)
    for _ in range(AP.MAX_ATTEMPTS + 1):
        AP.sync(conn, "hook-sandbox")
    assert AP.too_many(APS.by_request(conn, "hook-sandbox", "toolu_1")) is True
