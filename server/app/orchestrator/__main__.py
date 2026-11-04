"""`python -m app.orchestrator` — 오케스트레이터 루프.

systemd 사용자 서비스가 이걸 띄운다 (`labremote service install`).
개발 중에는 `labremote up --foreground` 로 같은 루프를 터미널에서 돌린다.

**어떤 예외도 루프를 멈추지 못한다.** 멈추면 "자리를 비워도 돈다" 가
거짓말이 된다. 실패는 세어 두고 백오프로 다시 한다.
"""

from __future__ import annotations

import sys
import time

from .. import db, registry
from ..store import loops as LP
from . import approvals as approvals_mod
from . import recovery as recovery_mod
from .loop import plan_step, resume_step, review_step, train_step, waiting_approval
from .runner_ctx import LoopCtx

__all__ = ["main", "once"]

#: 한 바퀴 돌고 쉬는 시간
IDLE_SEC = 10.0


def usable_grants(project: str) -> list[dict]:
    """사람이 승인해 둔, 아직 안 쓴 허가."""
    from .. import grants as grants_mod

    return [
        g
        for g in grants_mod.list_grants(project)
        if g.get("signatureOk") and not g.get("expired")
    ]


def _resuming_experiment(conn, project: str) -> str:
    """이어 갈 실험 — 설계만 끝난 가장 최근 것."""
    from ..store import experiments as X

    for row in X.listing(conn, project):
        if row.get("state") == "planned":
            return row["exp_id"]
    return ""


def once(conn, project: str, root: str, **kw) -> dict:
    """루프 한 바퀴: A -> B -> C.

    **대기 중이면 설계부터 다시 하지 않는다.** 승인이 난 그 자리에서
    `--resume` 으로 이어 간다 (계획 6-1). 처음부터 다시 돌리면 사용량도
    쓰고, 이미 만든 실험 폴더가 둘이 된다.
    """
    ctx = LoopCtx(project=project, root=root, **kw)
    steps = []

    waiting = waiting_approval(conn, project)
    if waiting:
        # **허가가 있을 때만** 다시 띄운다. 승인도 안 났는데 띄우면 같은
        # 자리에서 또 막히고 사용량만 쓴다.
        if not usable_grants(project):
            return {"ok": False, "steps": steps, "stoppedAt": "approval", "waiting": waiting}
        session_id = str(
            waiting[0].get("session_id")
            or (waiting[0].get("file") or {}).get("sessionId")
            or ""
        )
        resumed = resume_step(ctx, conn, session_id, request=waiting[0])
        steps.append(resumed)
        if waiting_approval(conn, project):
            return {"ok": False, "steps": steps, "stoppedAt": "approval"}
        exp_id = _resuming_experiment(conn, project)
        if not exp_id:
            # 설계가 아직 안 끝났다. 다음 바퀴에서 설계부터 간다.
            return {"ok": False, "steps": steps, "stoppedAt": "resume"}
        planned = {"ok": True, "stage": "resume", "experimentId": exp_id}
        steps.append(planned)
    else:
        planned = plan_step(ctx, conn)
        steps.append(planned)
        if planned.get("waiting"):
            return {"ok": False, "steps": steps, "stoppedAt": "approval"}
        if not planned.get("ok"):
            return {"ok": False, "steps": steps, "stoppedAt": "plan"}

    exp_id = planned["experimentId"]
    trained = train_step(ctx, conn, exp_id)
    steps.append(trained)
    if trained.get("blocked"):
        return {"ok": False, "steps": steps, "stoppedAt": "train"}

    reviewed = review_step(ctx, conn, exp_id, trained.get("outcome"))
    steps.append(reviewed)
    return {
        "ok": bool(reviewed.get("ok")),
        "steps": steps,
        "stoppedAt": None if reviewed.get("ok") else "review",
        "experimentId": exp_id,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rounds = None
    if "--once" in argv:
        rounds = 1
    done = 0
    with db.open_db() as conn:
        report = recovery_mod.recover(conn)
        if report["notes"]:
            print("복구:", " · ".join(report["notes"]))
        while rounds is None or done < rounds:
            for root, name in sorted(registry.load().items()):
                try:
                    approvals_mod.sync(conn, name)
                    state = LP.ensure(conn, name)
                    if state.get("paused") or state.get("state") in ("stopped", "done", "blocked"):
                        continue
                    got = once(conn, name, root)
                    print(f"{name}: {'완주' if got['ok'] else '멈춤 · ' + str(got['stoppedAt'])}")
                except Exception as exc:  # 루프는 멈추지 않는다
                    print(f"{name}: 한 바퀴가 실패했어요 — {type(exc).__name__}: {exc}")
            done += 1
            if rounds is not None and done >= rounds:
                break
            time.sleep(IDLE_SEC)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
