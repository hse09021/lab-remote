"""실험 한 건의 상태와 결과. 화면의 실험 목록이 이 표에서 나온다."""

from __future__ import annotations

import sqlite3

from .. import db
from . import row, rows

__all__ = ["STATES", "upsert", "get", "listing", "set_state", "record_result"]

#: web/src/api/types.ts 의 Experiment.state 와 같은 어휘로 둔다.
STATES = ("planned", "running", "done", "failed", "stopped")


def upsert(
    conn: sqlite3.Connection,
    project: str,
    exp_id: str,
    **fields,
) -> dict:
    """없으면 넣고 있으면 준 칸만 고친다. 루프가 같은 실험을 여러 번 건드린다."""
    allowed = {
        "parent",
        "knob",
        "state",
        "progress",
        "metric_name",
        "metric_value",
        "best_metric",
        "branch",
        "commit_sha",
        "report",
        "gpu_sec",
        "started_at",
        "ended_at",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"experiments 에 없는 칸이에요: {', '.join(sorted(unknown))}")
    now = db.now()
    conn.execute(
        "INSERT INTO experiments(project, exp_id, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(project, exp_id) DO NOTHING",
        (project, exp_id, now),
    )
    if fields:
        sets = ", ".join(f"{k}=?" for k in sorted(fields))
        args = [fields[k] for k in sorted(fields)]
        conn.execute(
            f"UPDATE experiments SET {sets}, updated_at=? WHERE project=? AND exp_id=?",
            [*args, now, project, exp_id],
        )
    return get(conn, project, exp_id)  # type: ignore[return-value]


def get(conn: sqlite3.Connection, project: str, exp_id: str) -> dict | None:
    return row(
        conn.execute(
            "SELECT * FROM experiments WHERE project=? AND exp_id=?", (project, exp_id)
        ).fetchone()
    )


def listing(conn: sqlite3.Connection, project: str, limit: int = 100) -> list[dict]:
    return rows(
        conn.execute(
            "SELECT * FROM experiments WHERE project=? ORDER BY exp_id DESC LIMIT ?",
            (project, int(limit)),
        )
    )


def set_state(conn: sqlite3.Connection, project: str, exp_id: str, state: str) -> dict:
    if state not in STATES:
        raise ValueError(f"모르는 실험 상태예요: {state!r}")
    stamp = {"started_at": db.now()} if state == "running" else {}
    if state in ("done", "failed", "stopped"):
        stamp = {"ended_at": db.now()}
    return upsert(conn, project, exp_id, state=state, **stamp)


def record_result(
    conn: sqlite3.Connection,
    project: str,
    exp_id: str,
    *,
    metric_name: str,
    metric_value: float | None,
    better: str = "lower",
) -> dict:
    """주 지표를 적고 best 를 갱신한다.

    `better` 는 "작을수록 좋다"(loss)와 "클수록 좋다"(accuracy)를 가른다.
    판단은 `docs/Evaluation.md` 가 기준이고, 여기서는 받은 대로만 센다.
    """
    current = get(conn, project, exp_id) or {}
    best = current.get("best_metric")
    if metric_value is not None:
        if best is None:
            best = metric_value
        elif better == "lower":
            best = min(best, metric_value)
        else:
            best = max(best, metric_value)
    return upsert(
        conn,
        project,
        exp_id,
        metric_name=metric_name,
        metric_value=metric_value,
        best_metric=best,
    )
