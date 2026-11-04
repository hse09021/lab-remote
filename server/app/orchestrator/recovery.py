"""재부팅·재시작 뒤 이어받기.

학습은 `start_new_session` 으로 떼어 놔서 **오케스트레이터가 죽어도 안 죽는다.**
그래서 올라올 때 "무엇이 아직 돌고 있고, 무엇이 끝났는지" 를 다시 맞춰야 한다.

판정 순서 (plan 1-5)

1. `jobs` 의 `running`·`leased` 를 훑어 `pid` + `/proc/<pid>/stat` 의
   **starttime** 으로 생존 확인 (pid 재사용 오판 방지)
2. 죽었으면 `output/exit_code` 로 정상 종료였는지 판정
3. 체크포인트가 있으면 `resume` 로 다시 큐에, 없으면 `failed` 기록 후 새 폴더
4. `runstate` 정리 + `state/Current.yaml` 다시 쓰기
5. Discord 로 "재부팅 뒤 복구했어요" **1회**
"""

from __future__ import annotations

import os

from .. import loop_layout as L
from .. import loopstate, registry, runstate
from ..runner import process as process_mod
from ..store import experiments as X
from ..store import jobs as J

__all__ = ["CHECKPOINT_GLOBS", "latest_checkpoint", "recover"]

#: 이어 돌릴 수 있는 체크포인트. 이름 순서가 곧 우선순위다.
CHECKPOINT_GLOBS = ("final.*", "best.*", "epoch_*", "step_*", "last.*")


def latest_checkpoint(output_dir: str) -> str:
    """이어 돌릴 체크포인트. 없으면 빈 문자열."""
    import fnmatch

    try:
        names = sorted(os.listdir(output_dir))
    except OSError:
        return ""
    for pattern in CHECKPOINT_GLOBS:
        found = sorted(n for n in names if fnmatch.fnmatch(n, pattern))
        if found:
            return os.path.join(output_dir, found[-1])
    return ""


def _exp_output(root: str, exp_id: str) -> str:
    return os.path.join(root, L.experiments_dir(), exp_id, "output")


def recover(conn, *, now_pid_alive=None) -> dict:
    """올라올 때 한 번. 무엇을 어떻게 했는지 돌려준다."""
    alive = now_pid_alive or process_mod.alive
    projects = {name: root for root, name in registry.load().items()}
    out = {"stillRunning": [], "finished": [], "requeued": [], "failed": [], "notes": []}

    for job in J.listing(conn, states=("running", "leased"), limit=200):
        root = projects.get(job["project"], "")
        payload = job.get("payload") or {}
        starttime = payload.get("starttime") if isinstance(payload, dict) else None

        if job["state"] == "running" and alive(job.get("pid"), starttime):
            out["stillRunning"].append(job["id"])
            continue

        if job["state"] == "leased":
            # 띄우기 전에 죽었다. 그대로 큐로 돌린다.
            J.requeue(conn, job["id"], error="오케스트레이터가 멈춰서 다시 큐에 넣었어요")
            out["requeued"].append(job["id"])
            continue

        exp_id = job.get("experiment_id") or ""
        output = _exp_output(root, exp_id) if root and exp_id else ""
        code = process_mod.read_exit_code(os.path.join(output, "exit_code")) if output else None

        if code == 0:
            J.finish(conn, job["id"], "done", exit_code=0)
            if exp_id:
                X.set_state(conn, job["project"], exp_id, "done")
            out["finished"].append(job["id"])
            continue

        checkpoint = latest_checkpoint(output) if output else ""
        J.finish(
            conn,
            job["id"],
            "failed",
            exit_code=code,
            error="오케스트레이터가 멈춘 사이에 끝났어요"
            if code is not None
            else "오케스트레이터가 멈춘 사이에 사라졌어요",
        )
        if checkpoint:
            new_id = J.add(
                conn,
                job["project"],
                "train",
                experiment_id=exp_id,
                payload={**(payload if isinstance(payload, dict) else {}), "resume_from": checkpoint},
            )
            out["requeued"].append(new_id)
            out["notes"].append(f"{exp_id}: 체크포인트에서 이어 돌려요 ({os.path.basename(checkpoint)})")
        else:
            if exp_id:
                X.set_state(conn, job["project"], exp_id, "failed")
            out["failed"].append(job["id"])
            out["notes"].append(f"{exp_id or job['id']}: 체크포인트가 없어 새 폴더가 필요해요")

    # 실행 상태를 다시 맞춘다 (훅이 보는 쪽)
    for name, root in projects.items():
        running = J.running(conn)
        try:
            if running and running.get("project") == name:
                loopstate.set_running(
                    name, running.get("experiment_id") or "", pid=running.get("pid"), root=root
                )
            else:
                if runstate.load(name).running:
                    loopstate.set_idle(name, root=root)
                else:
                    loopstate.write_current(name, root)
        except Exception as exc:
            out["notes"].append(f"{name}: 상태를 다시 쓰지 못했어요 — {exc}")
    return out
