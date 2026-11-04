"""루프 한 바퀴 — A(설계) → B(실행) → C(분석).

PDF 9쪽은 *"한 번의 요청에서는 실험 루프를 정확히 1회 수행한다"* 이고 8단계 중
4번이 "실험 실행" 이다. 학습을 오케스트레이터가 직접 띄우기로 했으므로
**루프 1회는 유지하되 Claude 호출을 둘로 쪼갠다.**

| 토막 | 주체 | PDF 8단계 | 산출물 |
|---|---|---|---|
| **A · 설계** | `claude -p` | 1~3 | `EXP-NNN/config.yaml`, `run.json` (명세만) |
| **B · 실행** | 오케스트레이터 (Claude 없음) | 4 | `output/train.log`, `exit_code`, 체크포인트 |
| **C · 분석** | `claude -p` | 5~8 | `result.csv`·`analysis.md`·로그·`State.yaml` + Final Report |

**AI 의 말을 믿지 않는다** (spec III-4) — `result.csv` 에서 직접 읽은 값과
Final Report 의 성공 판정이 어긋나면 자동 진행을 멈추고 사람을 부른다.

Claude 를 띄우는 부분은 `runner` 를 주입받는다. 시험에서는 **가짜 Claude** 를
끼워 Claude 없이 루프를 완주시킨다.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from .. import loop_layout as L
from .. import notifier
from .. import loopstate, registry
from ..agent import launch as launch_mod
from ..agent import prompts as prompts_mod
from ..agent import report as report_mod
from ..agent import session as session_mod
from ..monitor import metrics as metrics_mod
from ..runner import cache as cache_mod
from ..runner import process as process_mod
from ..runner import spec as spec_mod
from ..store import events as E
from ..store import experiments as X
from ..store import jobs as J
from ..store import loops as LP
from . import approvals as approvals_mod
from ..git import ops as ops_mod
from . import gitflow, guards, projectguard

__all__ = [
    "EXP_RE",
    "next_experiment_id",
    "plan_step",
    "train_step",
    "review_step",
    "resume_step",
    "waiting_approval",
    "update_order",
]

#: `EXP-007`
EXP_RE = re.compile(r"\AEXP-([0-9]{3,})\Z")

#: PDF 9쪽 Update Order. C 토막이 끝나면 이게 다 갱신됐어야 한다.
UPDATE_ORDER = (
    ("result", "{exp}/result.csv"),
    ("analysis", "{exp}/analysis.md"),
    ("experiment_log", None),
    ("decision_log", None),
    ("state", None),
)


def next_experiment_id(conn, project: str, root: str) -> str:
    """다음 실험 번호. **한 번이라도 시작된 번호는 다시 쓰지 않는다.**"""
    used = {e["exp_id"] for e in X.listing(conn, project, limit=1000)}
    try:
        used |= {
            name
            for name in os.listdir(os.path.join(root, L.experiments_dir()))
            if EXP_RE.match(name)
        }
    except OSError:
        pass
    from .. import runstate

    used |= set(runstate.load(project).started or [])
    highest = 0
    for name in used:
        found = EXP_RE.match(name)
        if found:
            highest = max(highest, int(found.group(1)))
    return f"EXP-{highest + 1:03d}"


def waiting_approval(conn, project: str) -> list[dict]:
    """훅이 막아 둔 요청이 있나. **파일이 진실이다** (`requests/`)."""
    approvals_mod.sync(conn, project)
    return approvals_mod.pending(conn, project)


def resume_step(ctx, conn, session_id: str, *, request: dict | None = None) -> dict:
    """승인이 난 뒤 **처음부터 다시 돌리지 않고** 이어 간다 (계획 6-1).

    프롬프트가 *"같은 도구·같은 입력으로 한 번만"* 이라고 못박는다 — 입력이
    달라지면 지문이 안 맞아 허가가 또 안 먹는다.
    """
    item = request or {}
    file_info = item.get("file") or {}
    names = [
        a.get("name") or a.get("action")
        for a in (file_info.get("actions") or [])
        if a.get("name") or a.get("action")
    ]
    prompt = prompts_mod.render(
        "resume_after_approval",
        {
            "request": str(file_info.get("request") or item.get("request") or ""),
            "actions": " · ".join(names) or str(item.get("action_key") or ""),
            "context": ctx.context,
        },
    )
    LP.set_state(conn, ctx.project, "planning")
    got = _claude(ctx, conn, prompt=prompt, session_id=session_id, resume=True)
    return {"ok": bool(got.get("ok")), "stage": "resume", "sessionId": session_id, "result": got}


def guard_git(ctx, conn, exc) -> None:
    """`.git` 이 거부됐다 — 멈추고 사람을 부른다.

    오케스트레이터의 git 은 **샌드박스 밖에서 사용자 권한으로** 돈다. `.git`
    에 `core.hooksPath`·`filter.*` 같은 게 심겼으면 그걸 실행해 주는 셈이다.
    되돌릴 수 없으니(무엇이 정본인지 모른다) **멈추고 사람이 본다.**
    """
    text = str(exc)
    E.add(conn, ctx.project, "보안", ".git 설정이 위험해서 git 을 돌리지 않았어요", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("gitguard", ctx.project),
            title=f".git 설정이 위험해요 · {ctx.project}",
            body=text[:1500],
        )
    except Exception:
        pass
    LP.set_state(
        conn, ctx.project, "blocked",
        stop_reason=".git 이 코드를 실행하게 만드는 설정을 가졌어요 — git 을 돌리지 않았어요",
    )


def guard_project(ctx, conn, *, when: str, block: bool = True) -> dict:
    """프로젝트 설정이 정본과 다르면 **되돌리고 알린다.** — 보안 경계다.

    작업 디렉터리는 샌드박스에서 언제나 쓰기 가능하므로(M4) AI 가 쓴 코드가
    `.claude/settings.json` 에 훅을 써 넣거나 `sandbox.enabled:false` 로
    다음 세션의 샌드박스를 끌 수 있다 — 실측에서 둘 다 됐다(M6).

    런처는 그 파일을 안 읽지만(`--setting-sources user`), **맨손 `claude`** 로
    열면 읽힌다. 그래서 되돌린다.

    | 부르는 자리 | `block` | 왜 |
    |---|---|---|
    | 루프 시작 전 | False | 이미 손댄 흔적이다. 되돌리고 계속한다 |
    | Claude 세션 종료 직후 | **True** | 그 세션이 범인이다. 멈추고 사람을 부른다 |
    | 기록 커밋 전 | **True** | 오염을 커밋에 넣지 않는다 |
    """
    got = projectguard.restore(ctx.root, ctx.project)
    if got.get("ok"):
        return got
    text = projectguard.describe(got)
    E.add(conn, ctx.project, "보안", f"프로젝트 설정이 바뀌어 있었어요 ({when}) — 되돌렸어요", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("projectguard", when),
            title=f"프로젝트 설정이 바뀌어 있었어요 · {ctx.project}",
            body=text,
            fields=[
                ("언제", when),
                ("되돌린 파일", ", ".join(got.get("restored") or []) or "없음"),
                ("증거", got.get("evidence") or "[못 남겼어요]"),
            ],
        )
    except Exception:
        # 알림 실패가 루프를 멈추지 않는다 (notify 의 예외 삼킴 원칙).
        pass
    if block:
        LP.set_state(
            conn, ctx.project, "blocked",
            stop_reason=f"프로젝트 설정이 바뀌어 있었어요 ({when}) — 되돌렸어요",
        )
    return got


def _claude(ctx, conn, *, prompt: str, session_id: str, resume: bool) -> dict:
    """Claude 를 한 번 띄운다. `ctx.runner` 가 실제 실행을 맡는다."""
    run = launch_mod.AgentRun(
        project=ctx.project,
        root=ctx.root,
        prompt=prompt,
        session_id=session_id,
        permission_mode=ctx.permission_mode,
        headless=True,
        resume=resume,
        cache_dir=ctx.cache_dir,
    )
    made = launch_mod.plan(run, preset=ctx.preset)
    got = ctx.runner(made)
    # 세션이 끝난 **직후**가 가장 짧은 창이다. 이 세션이 쓴 코드가 프로젝트
    # 설정을 고쳤으면 다음 세션(과 사람의 대화형 세션)이 그걸 읽는다.
    guard_project(ctx, conn, when="Claude 세션 종료 직후")
    return got


def plan_step(ctx, conn) -> dict:
    """A · 설계. Claude 가 `run.json` 까지 쓴다."""
    # 루프를 시작하기 전에 프로젝트 설정을 정본으로 맞춘다. 지난 루프나
    # 사람의 대화형 세션 뒤에 남은 흔적이 있을 수 있다. 되돌리고 **계속**한다.
    guard_project(ctx, conn, when="루프 시작 전", block=False)
    verdict = guards.check_loop(conn, ctx.project, ctx.root)
    if not verdict.ok:
        LP.set_state(
            conn, ctx.project, "stopped" if verdict["stop"] else "paused", stop_reason=verdict["reason"]
        )
        return {"ok": False, "stage": "plan", "reason": verdict["reason"], "stop": verdict["stop"]}

    exp_id = next_experiment_id(conn, ctx.project, ctx.root)
    loop_no = LP.bump_loop(conn, ctx.project)
    LP.set_state(conn, ctx.project, "planning")
    try:
        gitflow.start_experiment(ctx.root, exp_id, running=False)
    except ops_mod.GitRefused as exc:
        guard_git(ctx, conn, exc)
        return {
            "ok": False, "stage": "plan", "blocked": True,
            "reason": str(exc).splitlines()[0],
        }

    session_id = session_mod.new_id()
    prompt = prompts_mod.render(
        "loop_plan",
        {"loop_no": loop_no, "next_exp": exp_id, "context": ctx.context},
    )
    got = _claude(ctx, conn, prompt=prompt, session_id=session_id, resume=False)
    X.upsert(conn, ctx.project, exp_id, state="planned", branch=gitflow.branch_name(exp_id))

    # 훅이 막아 둔 요청이 있으면 거기서 멈춘다. 사람이 승인하면 **이어 간다.**
    waiting = waiting_approval(conn, ctx.project)
    if waiting:
        LP.set_state(conn, ctx.project, "waiting_approval")
        E.add(
            conn, ctx.project, "승인",
            f"{len(waiting)}건의 승인을 기다려요", tone="attention", ref=exp_id,
        )
        return {
            "ok": False,
            "stage": "plan",
            "experimentId": exp_id,
            "loopNo": loop_no,
            "sessionId": session_id,
            "waiting": waiting,
            "reason": f"승인을 기다려요 ({len(waiting)}건)",
            "result": got,
        }

    E.add(conn, ctx.project, "설계", f"{exp_id} 를 설계했어요", ref=exp_id)
    return {
        "ok": bool(got.get("ok")),
        "stage": "plan",
        "experimentId": exp_id,
        "loopNo": loop_no,
        "sessionId": session_id,
        "result": got,
    }


def train_step(ctx, conn, exp_id: str) -> dict:
    """B · 실행. **Claude 는 끼지 않는다.**"""
    config = guards.read_config(ctx.root)
    verdict = guards.check_train(ctx.root, cache_dir=ctx.cache_dir, config=config)
    if not verdict.ok:
        return {"ok": False, "stage": "train", "reason": verdict["reason"], "blocked": True}

    try:
        spec = spec_mod.load(ctx.project, ctx.root, exp_id)
    except spec_mod.SpecError as exc:
        X.set_state(conn, ctx.project, exp_id, "failed")
        E.add(conn, ctx.project, "실행", f"{exp_id} 의 run.json 을 믿을 수 없어요: {exc}", tone="bad", ref=exp_id)
        return {"ok": False, "stage": "train", "reason": str(exc), "blocked": True}

    job_id = J.add(conn, ctx.project, "train", experiment_id=exp_id, timeout_sec=spec.timeout_sec)
    J.lease(conn, ctx.project, kinds=("train",))
    LP.set_state(conn, ctx.project, "running", current_job_id=job_id)
    X.set_state(conn, ctx.project, exp_id, "running")

    launched = ctx.launcher(spec)
    J.start(conn, job_id, pid=launched.pid, pgid=launched.pgid, log_path=launched.log_path)
    loopstate.set_running(ctx.project, exp_id, pid=launched.pid, root=ctx.root)
    E.add(conn, ctx.project, "실행", f"{exp_id} 을 시작했어요", ref=exp_id)

    outcome = ctx.waiter(launched, spec)
    J.finish(
        conn,
        job_id,
        "done" if outcome.state == "done" else ("timeout" if outcome.state == "timeout" else "failed"),
        exit_code=outcome.exit_code,
        error=None if outcome.state == "done" else outcome.state,
    )
    X.upsert(conn, ctx.project, exp_id, gpu_sec=int(outcome.seconds))
    loopstate.set_idle(ctx.project, root=ctx.root)
    return {
        "ok": outcome.state == "done",
        "stage": "train",
        "experimentId": exp_id,
        "jobId": job_id,
        "outcome": outcome,
        "spec": spec,
    }


def update_order(root: str, exp_id: str) -> dict:
    """PDF 9쪽 Update Order 7개가 실제로 갱신됐는가.

    **AI 가 "기록했어요" 라고 적어도 파일을 직접 본다.**
    """
    exp_dir = os.path.join(root, L.experiments_dir(), exp_id)
    wanted = {
        "result.csv": os.path.join(exp_dir, "result.csv"),
        "analysis.md": os.path.join(exp_dir, "analysis.md"),
        L.LOOP_LAYOUT["experiment_log"]: os.path.join(root, L.LOOP_LAYOUT["experiment_log"]),
        L.LOOP_LAYOUT["decision_log"]: os.path.join(root, L.LOOP_LAYOUT["decision_log"]),
        L.LOOP_LAYOUT["state"]: os.path.join(root, L.LOOP_LAYOUT["state"]),
    }
    missing = []
    for name, path in wanted.items():
        try:
            if os.path.getsize(path) <= 0:
                missing.append(name)
        except OSError:
            missing.append(name)
    return {"ok": not missing, "missing": missing, "checked": sorted(wanted)}


def review_step(ctx, conn, exp_id: str, outcome) -> dict:
    """C · 분석. 끝나고 **AI 의 말과 숫자를 대조한다.**"""
    LP.set_state(conn, ctx.project, "reviewing")
    session_id = session_mod.new_id()
    prompt = prompts_mod.render(
        "loop_review",
        {
            "loop_no": LP.get(conn, ctx.project).get("loop_no") or 0,
            "exp_id": exp_id,
            "exit_state": getattr(outcome, "state", "unknown"),
            "exit_code": getattr(outcome, "exit_code", None),
            "elapsed": f"{getattr(outcome, 'seconds', 0):.0f}초",
            "context": ctx.context,
        },
    )
    got = _claude(ctx, conn, prompt=prompt, session_id=session_id, resume=False)

    report = report_mod.parse(str(got.get("text") or ""))
    said = report_mod.success_of(report)
    numbers = _numbers(ctx.root, exp_id)
    order = update_order(ctx.root, exp_id)

    disagree = said is not None and numbers["success"] is not None and said != numbers["success"]
    X.upsert(
        conn,
        ctx.project,
        exp_id,
        state="done" if getattr(outcome, "state", "") == "done" else "failed",
        report=str(report["fields"].get("result") or "")[:500],
        metric_name=numbers.get("metric"),
        metric_value=numbers.get("value"),
    )
    if numbers.get("value") is not None:
        X.record_result(
            conn,
            ctx.project,
            exp_id,
            metric_name=numbers.get("metric") or "loss",
            metric_value=numbers["value"],
        )
    # 커밋에 오염이 들어가지 않게 **커밋 전에** 한 번 더 본다.
    guard_project(ctx, conn, when="기록 커밋 전")
    try:
        gitflow.record_and_return(ctx.root, exp_id, running=False)
    except ops_mod.GitRefused as exc:
        # `.git` 이 코드를 실행하게 만드는 설정을 가졌다. **커밋하지 않는다.**
        guard_git(ctx, conn, exc)

    if disagree:
        LP.set_state(
            conn, ctx.project, "blocked",
            stop_reason=f"AI 의 성공 판정({said})과 result.csv 판정({numbers['success']})이 달라요",
        )
        E.add(conn, ctx.project, "검수", "AI 의 판정과 숫자가 어긋나요 — 사람 확인이 필요해요", tone="bad", ref=exp_id)
    return {
        "ok": bool(got.get("ok")) and not disagree and order["ok"],
        "stage": "review",
        "experimentId": exp_id,
        "report": report,
        "saidSuccess": said,
        "numbers": numbers,
        "updateOrder": order,
        "disagree": disagree,
        "result": got,
    }


def _numbers(root: str, exp_id: str) -> dict:
    """`result.csv` 에서 **직접** 읽은 값. AI 의 말과 대조할 근거다."""
    path = os.path.join(root, L.experiments_dir(), exp_id, "result.csv")
    got = metrics_mod.read_result(path)
    rows = got["rows"]
    series = metrics_mod.series_of(rows, "loss", "val") or metrics_mod.series_of(rows, "loss")
    value = next((r["value"] for r in reversed(series) if r["value"] is not None), None)
    threshold = _threshold(root)
    success = None
    if value is not None and threshold is not None:
        success = value <= threshold
    return {
        "metric": "loss" if series else None,
        "value": value,
        "threshold": threshold,
        "success": success,
        "format": got["format"],
        "warnings": got["warnings"],
    }


def _threshold(root: str):
    """`Config.yaml` 의 `goal.threshold`. 자리표시면 `None`.

    **`docs/Evaluation.md` 는 읽기만 한다** — 실행 중에는 잠겨 있다.
    """
    goal = guards.read_config(root).get("goal")
    goal = goal if isinstance(goal, dict) else {}
    text = str(goal.get("threshold") or "").strip()
    if not text or text.startswith("["):
        return None
    try:
        return float(text)
    except ValueError:
        return None
