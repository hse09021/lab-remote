"""③(웹)이 보낸 명령을 **집어서 실제로 한다.**

`store/commands.py` 는 다 만들어져 있었는데 **집어가는 쪽이 없었다**
(실측 2026-11-05). 웹이 `pause_loop` 을 INSERT 해도 아무 일도 일어나지
않는다 — 화면에는 "멈췄어요" 라고 뜨고 루프는 계속 돈다. 기록은 됐는데
코드가 안 도는, 이 저장소가 계속 찾아내는 그 모양이다.

## 경계

- **종류는 `store/commands.KINDS` 로 고정**이다. 모르는 종류는 `push` 가
  거절하므로 임의 문자열이 여기까지 오지 않는다.
- `payload` 에서 읽는 것은 **숫자와 짧은 문자열뿐**이다. 경로·명령·환경
  변수는 받지 않는다 — 웹이 오케스트레이터에게 "무엇을 실행하라" 고 말할
  수 있으면 훅과 샌드박스를 통째로 우회한다.
- 한 번에 몇 건만 처리한다(`MAX_PER_ROUND`). 큐가 쌓여도 루프가 멈추지
  않게.
- **어떤 예외도 루프를 멈추지 못한다.** 실패는 `commands.result` 에
  적고 다음으로 간다.
"""

from __future__ import annotations

from .. import loopstate, registry
from ..runner import process as process_mod
from ..store import commands as C
from ..store import events as E
from ..store import experiments as X
from ..store import jobs as J
from ..store import loops as LP

__all__ = ["MAX_PER_ROUND", "drain", "apply_one"]

#: 한 바퀴에 처리하는 최대 건수.
MAX_PER_ROUND = 20

#: 학습을 끊을 때 체크포인트를 저장할 틈.
STOP_GRACE_SEC = 30


def _int(value) -> int | None:
    try:
        got = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return got if got > 0 else None


def _text(value, limit: int = 200) -> str:
    return str(value or "").replace("\n", " ")[:limit]


def _project_of(command: dict) -> str:
    return str(command.get("project") or "")


def apply_one(conn, command: dict) -> dict:
    """명령 한 건. `{"ok", "note"}` 를 돌려주고 **던지지 않는다.**"""
    kind = str(command.get("kind") or "")
    payload = command.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    project = _project_of(command)

    if kind in ("pause_loop", "resume_loop", "queue_experiment", "stop_experiment"):
        if not project:
            return {"ok": False, "note": "프로젝트 이름이 없어요"}
        if not registry.root_of(project):
            return {"ok": False, "note": f"등록된 프로젝트가 아니에요: {project}"}

    if kind == "pause_loop":
        reason = _text(payload.get("reason")) or "웹에서 멈췄어요"
        LP.pause(conn, project, reason=reason)
        E.add(conn, project, "루프", f"웹에서 멈췄어요: {reason}", tone="attention")
        return {"ok": True, "note": f"멈췄어요: {reason}"}

    if kind == "resume_loop":
        before = LP.get(conn, project) or {}
        LP.resume(conn, project)
        E.add(conn, project, "루프", "웹에서 다시 열었어요")
        note = "다시 열었어요"
        if str(before.get("state") or "") in LP.LATCHED:
            note += f" (걸쇠도 풀었어요: {before.get('state')})"
        return {"ok": True, "note": note}

    if kind == "queue_experiment":
        job_id = J.add(conn, project, "plan")
        E.add(conn, project, "큐", f"웹에서 설계 작업을 넣었어요 [{job_id}]")
        return {"ok": True, "note": f"작업을 넣었어요: {job_id}", "jobId": job_id}

    if kind == "cancel_job":
        job_id = _int(payload.get("jobId") or payload.get("job_id"))
        if job_id is None:
            return {"ok": False, "note": "jobId 가 없어요"}
        job = J.get(conn, job_id)
        if job is None:
            return {"ok": False, "note": f"그런 작업이 없어요: {job_id}"}
        if job["state"] in ("done", "failed", "cancelled", "timeout"):
            return {"ok": False, "note": f"이미 끝난 작업이에요: {job['state']}"}
        if job.get("running_slot") is not None:
            # 돌고 있는 건 `stop_experiment` 가 할 일이다. 큐에서 지우기만
            # 하면 프로세스가 **고아로 남는다.**
            return {
                "ok": False,
                "note": "돌고 있는 작업이에요 — stop_experiment 로 보내 주세요",
            }
        J.cancel(conn, job_id, error="웹에서 취소했어요")
        E.add(conn, str(job["project"]), "큐", f"웹에서 취소했어요 [{job_id}]", tone="attention")
        return {"ok": True, "note": f"취소했어요: {job_id}"}

    if kind == "stop_experiment":
        return _stop_experiment(conn, project, payload)

    if kind == "reload_policy":
        # 정책은 **매번 새로 읽는다** (`policy.load`). 다시 읽을 게 없다.
        # 거짓으로 "다시 읽었어요" 라고 적지 않는다.
        return {"ok": True, "note": "정책은 매 판정마다 새로 읽어요 — 할 일이 없어요"}

    return {"ok": False, "note": f"처리하는 쪽이 없어요: {kind}"}


def _stop_experiment(conn, project: str, payload: dict) -> dict:
    """돌고 있는 학습을 끊는다. **프로세스 그룹째로** (손자까지)."""
    job = J.running(conn)
    if job is None or str(job.get("project") or "") != project:
        return {"ok": False, "note": "돌고 있는 학습이 없어요"}
    wanted = _text(payload.get("experimentId") or payload.get("exp_id"), 32)
    if wanted and wanted != str(job.get("experiment_id") or ""):
        return {
            "ok": False,
            "note": f"지금 도는 건 {job.get('experiment_id')} 예요 ({wanted} 아니에요)",
        }

    pgid = _int(job.get("pgid")) or _int(job.get("pid"))
    how = "pgid 가 없어서 신호를 못 보냈어요"
    if pgid:
        try:
            how = process_mod.terminate_group(pgid, grace_sec=STOP_GRACE_SEC)
        except Exception as exc:  # 신호 실패가 루프를 멈추지 않는다
            how = f"신호를 못 보냈어요: {type(exc).__name__}: {exc}"

    exp_id = str(job.get("experiment_id") or "")
    J.set_state(conn, int(job["id"]), "cancelled", error="웹에서 중단했어요")
    if exp_id:
        X.set_state(conn, project, exp_id, "stopped")
    try:
        loopstate.set_idle(project, root=registry.root_of(project))
    except Exception:
        pass
    LP.set_state(conn, project, "idle")
    E.add(
        conn, project, "실행",
        f"웹에서 {exp_id or '학습'} 을 중단했어요 ({how})",
        tone="attention", ref=exp_id or None,
    )
    return {"ok": True, "note": f"중단했어요: {exp_id or '학습'} · {how}"}


def drain(conn, *, limit: int = MAX_PER_ROUND) -> list[dict]:
    """대기 중인 명령을 집어 처리한다. 처리한 것들을 돌려준다.

    루프의 맨 앞에서 부른다 — `pause_loop` 이 **이번 바퀴부터** 먹어야
    한다 (다음 작업부터 멈춘다는 약속).
    """
    out: list[dict] = []
    for _ in range(max(1, int(limit))):
        command = C.take(conn)
        if command is None:
            break
        try:
            got = apply_one(conn, command)
        except Exception as exc:  # 어떤 예외도 루프를 멈추지 못한다
            got = {"ok": False, "note": f"{type(exc).__name__}: {exc}"}
        C.done(
            conn,
            int(command["id"]),
            result=got,
            state="done" if got.get("ok") else "failed",
        )
        out.append({**command, "result": got})
    return out
