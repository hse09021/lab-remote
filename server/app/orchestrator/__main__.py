"""`python -m app.orchestrator` — 오케스트레이터 루프.

systemd 사용자 서비스가 이걸 띄운다 (`labremote service install`).
개발 중에는 `labremote up --foreground` 로 같은 루프를 터미널에서 돌린다.

**어떤 예외도 루프를 멈추지 못한다.** 멈추면 "자리를 비워도 돈다" 가
거짓말이 된다. 실패는 세어 두고 백오프로 다시 한다.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

from .. import db, registry
from ..store import loops as LP
from . import approvals as approvals_mod
from . import approvals as AP_ORCH
from . import commands as commands_mod
from . import installs as installs_mod
from . import recovery as recovery_mod
from .loop import (
    UsageWait,
    design_landed,
    next_experiment_id,
    numbering_note,
    plan_step,
    resume_step,
    review_step,
    train_step,
    waiting_approval,
)
from .runner_ctx import LoopCtx

__all__ = [
    "main", "once", "stop_reason", "line_for", "log_path", "say",
]

#: 한 바퀴 돌고 쉬는 시간
IDLE_SEC = 10.0


def usable_grants(project: str, *, request: dict | None = None) -> list[dict]:
    """사람이 승인해 둔, 아직 안 쓴 허가.

    `request` 를 주면 **그 요청의 것만** 고른다. 전에는 아무 허가 하나라도
    쓸 수 있으면 재개했다 — 다른 요청의 허가로 엉뚱한 세션을 이어 가는 길이다.
    """
    from .. import grants as grants_mod

    out = [
        g
        for g in grants_mod.list_grants(project)
        if g.get("signatureOk") and not g.get("expired")
    ]
    if not request:
        return out
    wanted_session = str(request.get("session_id") or "")
    wanted_request = str(request.get("request_id") or "")
    picked = [
        g for g in out
        if (not wanted_request or str(g.get("requestId") or "") == wanted_request)
        or (not wanted_session or str(g.get("sessionId") or "") == wanted_session)
    ]
    return picked


#: 이어 갈 수 없는 상태 — 이미 돌았거나 돌고 있는 것.
DONE_STATES = ("done", "failed", "running")


def _resuming_experiment(conn, project: str, root: str) -> str:
    """이어 갈 실험 — 설계가 **실제로 떨어진** 가장 최근 것.

    **`run.json` 이 근거다.** DB 의 `state` 만으로는 둘 다 틀린다.

    * `planned` 인데 `run.json` 이 없을 수 있다 — 설계 전에 멈춘 번호다.
      그걸 집어 가면 B 토막이 `SpecError` 로 바로 실패하고 실패 기록만
      하나 더 남는다 (실측 2026-11-05: EXP-003~005 가 그 상태였다).
    * `stopped` 인데 `run.json` 이 **있을** 수 있다 — 설계가 승인 대기로
      끊겼다가 재개가 명세까지 써 준 경우다. 이건 이어 가야 한다.

    찾았으면 `planned` 로 되돌려 둔다. 이제 사실과 맞는다.
    """
    from ..store import experiments as X

    for row in X.listing(conn, project):
        exp_id = str(row.get("exp_id") or "")
        if str(row.get("state") or "") in DONE_STATES:
            continue
        if design_landed(root, exp_id):
            if row.get("state") != "planned":
                X.upsert(conn, project, exp_id, state="planned", report=None)
            return exp_id
    return ""


def _preset_of(project: str) -> str:
    """정책의 권한 단계. 못 읽으면 `full` 로 둔다 (지금까지의 기본값).

    **지어내지 않는다** — 못 읽은 것과 `full` 을 구별할 길이 없으면 적어도
    런처의 검사를 지나가게 둬서 다른 점검이 돌게 한다.
    """
    from .. import policy as policy_mod

    try:
        return str(policy_mod.load(project).effective_mode() or "full")
    except Exception:
        return "full"


def _design_ready(project: str, root: str, exp_id: str) -> str:
    """설계가 **우리 검증을 통과했나.** 통과하면 빈 문자열, 아니면 사유.

    `run.json` 은 보안 경계라 **AI 의 확인을 믿지 않는다** — 어차피
    `runner/spec.py` 가 다시 다 본다 (entrypoint 화이트리스트·args 가 문자열
    배열인지·env 키·timeout). 그래서 AI 가 자기 명세를 확인하려다 막혀도
    **우리는 판단할 재료가 이미 다 있다.**
    """
    from ..runner import spec as spec_mod

    if not exp_id:
        return "실험 번호가 없어요"
    if not design_landed(root, exp_id):
        return "run.json 이 없어요"
    try:
        spec_mod.load(project, root, exp_id)
    except spec_mod.SpecError as exc:
        return f"run.json 을 믿을 수 없어요: {exc}"
    return ""


def _advance_past_approval(conn, project: str, root: str, exp_id: str) -> bool:
    """설계가 다 됐으면 **승인을 기다리지 않고** B 로 간다.

    왜: 설계가 끝난 **뒤에** 막힌 호출은 설계에 필요한 게 아니었다. 실측
    2026-11-05 에 Claude 가 `run.json` 을 다 쓰고 나서 그걸 **자기가**
    확인하려고 `python -I -c "…json.load…"` 를 돌렸고, `python -c` 는 늘
    `ask` 라 헤드리스에서 막혔다. 명세는 완전했는데 사람이 쓸모없는 승인을
    눌러 줘야 루프가 움직였다.

    그냥 지나가는 게 아니다 — **우리 검증을 통과했을 때만** 간다
    (`_design_ready`). 닫는 이유는 `Approval_log.csv` 와 감사 진본에 남는다.
    """
    if _design_ready(project, root, exp_id):
        return False
    closed = 0
    for row in waiting_approval(conn, project):
        AP_ORCH.abandon(
            conn, project, str(row.get("request_id") or ""),
            reason=(
                f"{exp_id} 설계가 이미 끝났어요 (run.json 이 검증을 통과했어요) · "
                "설계 뒤에 막힌 호출이라 승인 없이 실행으로 넘어갔어요"
            ),
        )
        closed += 1
    return closed > 0


def once(conn, project: str, root: str, **kw) -> dict:
    """루프 한 바퀴: A -> B -> C.

    **대기 중이면 설계부터 다시 하지 않는다.** 승인이 난 그 자리에서
    `--resume` 으로 이어 간다 (계획 6-1). 처음부터 다시 돌리면 사용량도
    쓰고, 이미 만든 실험 폴더가 둘이 된다.

    사용량 한도로 기다리는 중이면 **AI 세션을 띄우지 않는다.** 돌고 있는
    학습은 건드리지 않는다 (spec V).
    """
    try:
        return _once(conn, project, root, **kw)
    except UsageWait as waiting:
        # 한도 대기는 **실패가 아니다.** 기다리면 풀린다. 루프를 멈추지
        # 않고(상태만 `usage_limited`) 긴 간격으로 계속 다시 해 본다.
        return {
            "ok": False,
            "steps": [],
            "stoppedAt": "usage",
            "reason": waiting.state.get("reason") or str(waiting),
        }


def _once(conn, project: str, root: str, **kw) -> dict:
    # 🔑 **프리셋은 정책에서 읽는다** (9단계 1번에서 드러난 구멍).
    #
    # `LoopCtx.preset` 의 기본값이 `"full"` 이라, 프로젝트가 수동제어여도
    # 런처에는 `full` 이라고 말하고 있었다. 그러면
    # `launch.check_mode(headless=True, preset="manual")` 의 거부가 **한 번도
    # 안 돈다.** 대신 훅은 진짜 정책(`manual`)을 보고 `code`·`hparam` 까지
    # 전부 `ask` → 헤드리스 거절로 떨어뜨린다.
    if "preset" not in kw:
        kw["preset"] = _preset_of(project)
    if "context" not in kw:
        # 번호 상황을 **우리가** 말해 준다. Claude 는 `lab.db` 를 못 읽어서
        # "planned 라는데 폴더가 없다" 를 혼자서는 풀 수 없다.
        #
        # 이번에 쓸 번호는 **빼고** 말한다. 안 빼면 프롬프트가 자기 모순이다.
        working = _resuming_experiment(conn, project, root) or next_experiment_id(
            conn, project, root
        )
        kw["context"] = numbering_note(conn, project, root, exclude=[working])
    ctx = LoopCtx(project=project, root=root, **kw)
    steps: list[dict] = []
    planned: dict | None = None

    def stopped(stage: str, **extra) -> dict:
        return {"ok": False, "steps": steps, "stoppedAt": stage, **extra}

    # 📦 **설치 승인부터 본다.**
    #
    # 설치가 끝났으면 그걸 기다리던 세션을 이어 간다 (프롬프트가
    # `Install_result.json` 을 읽게 한다). 아직 승인을 안 했으면 **설계
    # 세션을 띄우지 않는다** — Claude 는 같은 요청을 또 쓸 뿐이고 사용량만
    # 쓴다. 이 연결이 통째로 없었다 (실측 2026-11-05).
    settled = installs_mod.resumable(conn, project)
    if settled:
        row = settled[0]
        steps.append(
            resume_step(
                ctx, conn, str(row.get("session_id") or ""),
                request={
                    "request": str(row.get("request") or ""),
                    "action_key": "설치 요청",
                },
            )
        )
        left = waiting_approval(conn, project)
        if left:
            return stopped("approval", waiting=left)
        exp_id = _resuming_experiment(conn, project, root)
        if exp_id:
            planned = {"ok": True, "stage": "resume", "experimentId": exp_id}
            steps.append(planned)

    if planned is None:
        open_installs = installs_mod.pending(conn, project)
        if open_installs:
            names = ", ".join(
                str(r.get("request") or "") for r in open_installs[:3]
            )
            return stopped(
                "install",
                waiting=open_installs,
                reason=(
                    f"설치 승인을 기다려요 ({len(open_installs)}건): {names} · "
                    "`labremote installs list <프로젝트>`"
                ),
            )

    waiting = waiting_approval(conn, project) if planned is None else []
    if waiting:
        item = waiting[0]
        if usable_grants(project, request=item):
            # 사람이 승인했고 허가가 살아 있다 — **그 자리에서** 이어 간다.
            session_id = str(
                item.get("session_id") or (item.get("file") or {}).get("sessionId") or ""
            )
            request_id = str(item.get("request_id") or "")
            steps.append(resume_step(ctx, conn, session_id, request=item))

            # 🔑 재개했는데 요청이 그대로면 닫는다.
            #
            # 재개가 끝나면서 허가는 지워진다(S3). 요청을 열어 두면 다음
            # 바퀴는 "요청 열림 + 허가 없음" 이라 바로 멈추고, 사람이 또
            # 승인해도 같은 자리로 돌아온다 — **풀릴 길이 없다.** 실측에서
            # 재개한 세션이 도구를 한 번도 안 부르고 끝났다 (2026-11-05).
            still = {
                str(r.get("request_id") or "") for r in waiting_approval(conn, project)
            }
            if request_id and request_id in still:
                AP_ORCH.abandon(
                    conn, project, request_id,
                    reason=(
                        "재개가 끝났는데 요청이 그대로 열려 있어요 "
                        "(같은 호출을 다시 안 했거나, 이제 허가 없이도 통과했어요)"
                    ),
                )
                still.discard(request_id)
            if still:
                return stopped("approval", waiting=waiting_approval(conn, project))
            exp_id = _resuming_experiment(conn, project, root)
            if not exp_id:
                return stopped(
                    "resume",
                    reason=(
                        "이어 갔는데 설계가 안 끝났어요 (run.json 이 없어요) · "
                        "다음 바퀴에서 같은 번호로 설계부터 가요"
                    ),
                )
            planned = {"ok": True, "stage": "resume", "experimentId": exp_id}
            steps.append(planned)
        else:
            # 허가가 없다. 세 갈래다.
            ready_exp = _resuming_experiment(conn, project, root)
            if ready_exp and _advance_past_approval(conn, project, root, ready_exp):
                # (1) **설계는 이미 끝났다.** 승인을 기다릴 이유가 없다 —
                #     설계 뒤에 막힌 호출이었다 (실측: AI 의 run.json 자기 검증).
                planned = {"ok": True, "stage": "plan", "experimentId": ready_exp}
                steps.append(planned)
            elif str(item.get("state") or "") == "approved":
                # (2) 승인은 났는데 허가가 지나갔다 = 재개가 이미 다녀갔다.
                #     열어 두면 다음 바퀴마다 여기서 멈추고 풀릴 길이 없다.
                AP_ORCH.abandon(
                    conn, project, str(item.get("request_id") or ""),
                    reason="승인했지만 허가가 이미 지나갔어요 (재개가 그 호출을 다시 안 했어요)",
                )
                left = waiting_approval(conn, project)
                if left:
                    return stopped("approval", waiting=left)
                # planned 는 None — 아래에서 설계부터 평소대로 간다.
            else:
                # (3) 아직 승인 전이다. **그대로 기다린다** — 그게 승인
                #     대기의 본래 뜻이다.
                return stopped("approval", waiting=waiting)

    if planned is None:
        planned = plan_step(ctx, conn)
        steps.append(planned)
        if planned.get("waiting"):
            moved = _advance_past_approval(
                conn, project, root, str(planned.get("experimentId") or "")
            )
            if not moved:
                return stopped("approval", waiting=planned.get("waiting"))
            planned = dict(planned, ok=True, waiting=None)
            steps[-1] = planned
        if not planned.get("ok"):
            return stopped("plan")

    exp_id = planned["experimentId"]
    trained = train_step(ctx, conn, exp_id)
    steps.append(trained)
    if trained.get("blocked"):
        return stopped("train", experimentId=exp_id)

    reviewed = review_step(ctx, conn, exp_id, trained.get("outcome"))
    steps.append(reviewed)
    return {
        "ok": bool(reviewed.get("ok")),
        "steps": steps,
        "stoppedAt": None if reviewed.get("ok") else "review",
        "experimentId": exp_id,
    }


#: 앞단 실행(`up --once`·`--foreground`)도 여기에 같이 남긴다.
LOG_NAME = "orchestrator.log"


def log_path() -> str:
    return os.path.join(registry.data_dir(), "logs", LOG_NAME)


def say(line: str) -> None:
    """화면과 로그에 **같은 문장**을 남긴다.

    systemd 는 `StandardOutput=append:` 로 로그를 받지만 앞단 실행은 터미널로
    흘러가 버린다 — 그래서 나중에 원인을 찾을 수가 없었다 (실측 2026-11-05:
    `orchestrator.log` 가 아예 없었다). **쓰기 실패가 루프를 멈추지는
    않는다.**
    """
    print(line, flush=True)
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass


def _skip_reason(state: dict) -> str:
    if state.get("paused"):
        return "사람이 멈춰 뒀어요: " + str(state.get("paused_reason") or "사유 없음")
    if str(state.get("state") or "") in ("stopped", "done", "blocked"):
        return (
            f"루프 상태가 {state.get('state')} 예요: "
            + str(state.get("stop_reason") or "사유 없음")
            + " · `labremote queue resume <프로젝트>` 로 다시 열어요"
        )
    return ""


def _field(obj, name: str):
    """`outcome` 은 dataclass 일 수도 dict 일 수도 있다."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _join(head: str, tail: str) -> str:
    return " · ".join(x for x in (head, tail) if x)


def stop_reason(got: dict) -> str:
    """한 바퀴의 결과에서 **멈춘 이유 한 줄**을 뽑는다.

    `멈춤 · plan` 만 찍으면 사람이 로그를 뒤져야 안다 — 그게 이번 실측에서
    실제로 일어났다. 사유는 이미 `steps` 안에 있는데 **화면에 안 나왔다.**
    """
    if got.get("ok"):
        return ""
    if got.get("reason"):
        return str(got["reason"])

    stage = got.get("stoppedAt")
    steps = got.get("steps") or []

    if stage == "approval":
        waiting = got.get("waiting") or []
        for step in reversed(steps):
            if not waiting and step.get("waiting"):
                waiting = step["waiting"]
        if waiting:
            first = waiting[0] or {}
            action = str(first.get("action_key") or "").strip()
            # `request` 는 사람이 읽는 짧은 줄이다 (전문은 `approvals show`).
            what = str(first.get("request") or "").strip().replace("\n", " ")
            if len(what) > 70:
                what = what[:69] + "…"
            bits = " · ".join(x for x in (action, what) if x)
            tail = f": {bits}" if bits else ""
            more = f" 외 {len(waiting) - 1}건" if len(waiting) > 1 else ""
            return (
                f"승인을 기다려요 ({len(waiting)}건){tail}{more} · "
                "`labremote approvals list <프로젝트>`"
            )
        return "승인을 기다려요"

    # 🔑 **학습이 실패했으면 그 말을 먼저 한다.**
    #
    # 실패해도 C(분석)는 돌린다 — 실패도 기록이다. 그런데 그러면 멈춘 자리가
    # `review` 가 되고 사유도 "기록이 덜 갱신됐어요" 가 된다. 실측에서
    # 진짜 원인(`systemd-run` 이 버스를 못 찾아 학습이 즉사)이 **한 칸 뒤로
    # 밀려** 사람이 로그를 직접 뒤져야 했다.
    head = ""
    for step in steps:
        # `ok` 가 **명시적으로 거짓**일 때만. 칸이 없는 걸 실패로 읽으면
        # 사유를 지어내는 셈이다.
        if step.get("stage") != "train" or step.get("ok") is not False:
            continue
        outcome = step.get("outcome")
        state = _field(outcome, "state") or step.get("reason") or "실패"
        code = _field(outcome, "exit_code")
        bits = f"학습이 안 됐어요 ({state}"
        if code is not None:
            bits += f" · 종료코드 {code}"
        exp = step.get("experimentId")
        where = f"experiments/{exp}/output/train.log" if exp else "output/train.log"
        head = bits + f") · {where} 를 보세요"
        break

    for step in reversed(steps):
        if stage and step.get("stage") != stage:
            continue
        if step.get("reason"):
            return _join(head, str(step["reason"]))
        if step.get("disagree"):
            said = step.get("saidSuccess")
            numbers = step.get("numbers") or {}
            return _join(
                head,
                f"AI 의 판정({said})과 result.csv 판정({numbers.get('success')})이 달라요",
            )
        order = step.get("updateOrder") or {}
        if order and not order.get("ok"):
            missing = ", ".join(str(x) for x in (order.get("missing") or [])) or "일부"
            return _join(head, f"기록이 덜 갱신됐어요: {missing}")
        break
    return head


def line_for(name: str, got: dict) -> str:
    """사람이 보는 한 줄. `--once` 출력과 로그가 **같은 문장**을 쓴다."""
    if got.get("ok"):
        exp = got.get("experimentId")
        return f"{name}: 완주" + (f" · {exp}" if exp else "")
    why = stop_reason(got)
    head = f"{name}: 멈춤 · {got.get('stoppedAt')}"
    return head + (f" · {why}" if why else "")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rounds = None
    if "--once" in argv:
        rounds = 1
    done = 0
    with db.open_db() as conn:
        report = recovery_mod.recover(conn)
        if report["notes"]:
            say("복구: " + " · ".join(report["notes"]))
        while rounds is None or done < rounds:
            # 📮 **웹이 보낸 명령을 먼저 집는다.**
            #
            # `store/commands.py` 는 다 만들어져 있었는데 집어가는 쪽이
            # 없었다 (실측 2026-11-05) — 웹이 `pause_loop` 을 INSERT 해도
            # 아무 일도 안 일어났다. 맨 앞에서 집어야 `pause_loop` 이
            # **이번 바퀴부터** 먹는다.
            for item in commands_mod.drain(conn):
                got = item.get("result") or {}
                mark = "✔" if got.get("ok") else "✘"
                say(
                    f"{item.get('project') or '-'}: 명령 {mark} {item.get('kind')}"
                    f" · {got.get('note') or ''}"
                )

            for root, name in sorted(registry.load().items()):
                try:
                    approvals_mod.sync(conn, name)
                    state = LP.ensure(conn, name)
                    skipped = _skip_reason(state)
                    if skipped:
                        # 전에는 **아무 줄도 안 찍었다.** 사람은 왜 조용한지
                        # 알 수 없었다.
                        say(f"{name}: 안 돌았어요 · {skipped}")
                        continue
                    got = once(conn, name, root)
                    say(line_for(name, got))
                except Exception as exc:  # 루프는 멈추지 않는다
                    say(f"{name}: 한 바퀴가 실패했어요 — {type(exc).__name__}: {exc}")
            done += 1
            if rounds is not None and done >= rounds:
                break
            time.sleep(IDLE_SEC)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
