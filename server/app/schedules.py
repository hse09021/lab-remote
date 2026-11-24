"""예약 — 사람이 시각으로 건 것만, 서버 안의 시계로 돈다(PLAN 4.1 scheduler).

- 한 번 / 매일 / 매주. **연쇄 예약 없음** — "앞 실행이 끝나면 다음" 같은 건 만들지
  않는다. cron · systemd 타이머도 만들지 않는다.
- 명령 예약: 그 시각에 GPU가 바쁘면(`nvidia-smi` 계산 프로세스가 있으면 — 사람이
  고름, 2026-11-23) 끝날 때까지 기다렸다가 시작하고, 기다리기 시작할 때 한 번 알린다.
- 에이전트 예약: 세션을 열고 첫 요청만 보낸다. 승인이 필요하면 거기서 멈춘다.
- 서버가 꺼져 있던 사이 지난 예약은 **늦게 돌리지 않고** "놓쳤어요"로 적는다
  (System 화면: "서버가 꺼져 있으면 돌지 않아요").
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta

from . import alerts, db, projects
from .store import rows

__all__ = [
    "ScheduleError",
    "KINDS",
    "REPEATS",
    "MISS_GRACE_SEC",
    "next_after",
    "create",
    "update",
    "delete",
    "list_all",
    "get",
    "gpu_busy",
    "due",
]

KINDS = ("command", "agent")
REPEATS = ("once", "daily", "weekly")
#: 이보다 늦게 알아챈 예약은 서버가 꺼져 있었던 것으로 본다
MISS_GRACE_SEC = 10 * 60
REPEAT_LABELS = {"once": "한 번", "daily": "매일", "weekly": "매주"}
FIELDS = ("name", "kind", "project", "tree", "command", "env", "prompt", "mode", "model", "effort", "at", "repeat", "enabled")


class ScheduleError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def next_after(at: float, repeat: str, now: float) -> float | None:
    """`now` 뒤의 다음 시각. 한 번짜리가 이미 지났으면 None."""
    if repeat == "once":
        return at if at > now else None
    first = datetime.fromtimestamp(at)
    current = datetime.fromtimestamp(now)
    step = timedelta(days=1 if repeat == "daily" else 7)
    if first > current:
        return first.timestamp()
    # 시각(과 요일)을 지킨 채 now 뒤로 민다 — 서머타임이 없는 시간대 기준
    k = int((current - first) / step) + 1
    return (first + k * step).timestamp()


def _view(row: dict) -> dict:
    out = {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "project": row["project"],
        "tree": row["tree"],
        "command": row["command"],
        "env": row["env"],
        "prompt": row["prompt"],
        "mode": row["mode"],
        "model": row["model"],
        "effort": row["effort"],
        "at": row["at"],
        "repeat": row["repeat"],
        "repeatLabel": REPEAT_LABELS.get(row["repeat"], row["repeat"]),
        "enabled": bool(row["enabled"]),
        "nextAt": row["next_at"],
        "lastAt": row["last_at"],
        "lastResult": row["last_result"],
        "lastRef": json.loads(row["last_ref"]) if row["last_ref"] else None,
        "waitingSince": row["waiting_since"],
    }
    if row["repeat"] == "weekly":
        out["repeatLabel"] = "매주 " + "월화수목금토일"[datetime.fromtimestamp(row["at"]).weekday()]
    return out


def _clean(data: dict, *, partial: bool = False) -> dict:
    out: dict = {}
    for key in FIELDS:
        if key in data and data[key] is not None:
            out[key] = data[key]
    if not partial or "kind" in out:
        if out.get("kind") not in KINDS:
            raise ScheduleError("예약 종류는 명령이나 에이전트 중 하나여야 해요.")
    if not partial or "repeat" in out:
        if out.get("repeat", "once") not in REPEATS:
            raise ScheduleError("반복은 한 번 · 매일 · 매주 중 하나여야 해요.")
    if not partial or "project" in out:
        projects.require(out.get("project", ""))
    if "name" in out:
        out["name"] = str(out["name"]).strip()[:80]
    if not partial and not out.get("name"):
        raise ScheduleError("예약 이름을 입력해 주세요.")
    if "at" in out:
        try:
            out["at"] = float(out["at"])
        except (TypeError, ValueError):
            raise ScheduleError("시각이 올바르지 않아요.") from None
    if not partial and "at" not in out:
        raise ScheduleError("시각을 선택해 주세요.")
    for key in ("command", "prompt"):
        if key in out and (len(str(out[key])) > 4000 or "\x00" in str(out[key])):
            raise ScheduleError("명령이나 요청이 너무 길어요.")
    if "enabled" in out:
        out["enabled"] = 1 if out["enabled"] else 0
    return out


def _check_ready(merged: dict) -> None:
    if merged["kind"] == "command" and not str(merged.get("command") or "").strip():
        raise ScheduleError("실행할 명령을 입력해 주세요.")
    if merged["kind"] == "agent" and not str(merged.get("prompt") or "").strip():
        raise ScheduleError("에이전트에게 보낼 요청을 입력해 주세요.")


def create(conn: sqlite3.Connection, data: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    clean = _clean(data)
    merged = {"tree": "", "command": "", "env": "", "prompt": "", "mode": "manual", "model": "", "effort": "", "repeat": "once", "enabled": 1, **clean}
    _check_ready(merged)
    nxt = next_after(merged["at"], merged["repeat"], now)
    if nxt is None:
        raise ScheduleError("이미 지난 시각이에요. 이후 시각을 선택해 주세요.")
    cols = list(merged)
    cur = conn.execute(
        f"INSERT INTO schedules({', '.join(cols)}, next_at, created_at) VALUES({', '.join('?' * len(cols))}, ?, ?)",
        [merged[c] for c in cols] + [nxt, db.now()],
    )
    return get(conn, int(cur.lastrowid))


def get(conn: sqlite3.Connection, sid: int) -> dict:
    found = rows(conn.execute("SELECT * FROM schedules WHERE id = ?", (int(sid),)))
    if not found:
        raise ScheduleError(f"없는 예약이에요: {sid}")
    return _view(found[0])


def list_all(conn: sqlite3.Connection) -> list[dict]:
    items = [_view(r) for r in rows(conn.execute("SELECT * FROM schedules"))]
    items.sort(key=lambda x: (x["nextAt"] is None, x["nextAt"] or 0, x["id"]))
    return items


def update(conn: sqlite3.Connection, sid: int, data: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    current = rows(conn.execute("SELECT * FROM schedules WHERE id = ?", (int(sid),)))
    if not current:
        raise ScheduleError(f"없는 예약이에요: {sid}")
    clean = _clean(data, partial=True)
    merged = {**current[0], **clean}
    _check_ready(merged)
    nxt = next_after(merged["at"], merged["repeat"], now)
    if clean.get("enabled") and nxt is None:
        raise ScheduleError("한 번 실행하는 예약인데 시각이 이미 지났어요. 시각을 다시 선택해 주세요.")
    sets = ", ".join(f"{k} = ?" for k in clean)
    conn.execute(
        f"UPDATE schedules SET {sets + ', ' if sets else ''}next_at = ?, waiting_since = NULL WHERE id = ?",
        [*clean.values(), nxt, int(sid)],
    )
    return get(conn, sid)


def delete(conn: sqlite3.Connection, sid: int) -> None:
    conn.execute("DELETE FROM schedules WHERE id = ?", (int(sid),))


def gpu_busy() -> bool:
    """`nvidia-smi`에 계산 프로세스가 있나. 화면용(그래픽) 프로세스는 안 센다.

    조회가 안 되면 바쁘지 않은 것으로 본다 — 드라이버가 깨져 있으면 어차피 학습이
    실패하고, 그건 실행 쪽 알림이 알려 준다.
    """
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and any(line.strip() for line in done.stdout.splitlines())


def due(conn: sqlite3.Connection, now: float) -> list[dict]:
    return [_view(r) for r in rows(conn.execute(
        "SELECT * FROM schedules WHERE enabled = 1 AND next_at IS NOT NULL AND next_at <= ? ORDER BY next_at", (now,)
    ))]


def _finish(conn: sqlite3.Connection, job: dict, result: str, ref: dict | None, now: float) -> None:
    nxt = next_after(job["at"], job["repeat"], now)
    # 한 번짜리는 돌고 나면 꺼진다 — 다시 쓰려면 시각을 고쳐서 켠다
    conn.execute(
        "UPDATE schedules SET last_at = ?, last_result = ?, last_ref = ?, next_at = ?, waiting_since = NULL, "
        "enabled = CASE WHEN ? IS NULL THEN 0 ELSE enabled END WHERE id = ?",
        (now, result, json.dumps(ref) if ref else None, nxt, nxt, job["id"]),
    )


async def _post(*args, **kwargs) -> None:
    """알림은 스레드에서 새 연결로 — Discord 재시도(sleep)가 이벤트 루프를 막지 않게."""
    import asyncio

    def go():
        with db.open_db() as c:
            alerts.post(c, *args, **kwargs)

    try:
        await asyncio.to_thread(go)
    except Exception:  # 알림이 예약을 멈추면 안 된다
        pass


def _where(job: dict) -> str:
    return f"{job['project']} · {job['tree'] or '프로젝트 루트'}"


async def tick(conn: sqlite3.Connection, *, now: float | None = None, busy=None, start_run=None, start_session=None) -> list[dict]:
    """시각이 된 예약을 처리한다. 무엇을 했는지 돌려준다(시험용).

    `start_run`·`start_session`·`busy`는 시험에서 바꿔 끼운다.
    """
    import asyncio

    from . import runs
    from .agents.manager import manager

    now = time.time() if now is None else now
    busy = busy or gpu_busy
    start_run = start_run or (lambda job: runs.start(job["project"], job["command"], env=job["env"], cwd=job["tree"], name=job["name"]))
    done = []
    for job in due(conn, now):
        late = now - job["nextAt"]
        if late > MISS_GRACE_SEC and not job["waitingSince"]:
            _finish(conn, job, "놓쳤어요. 그 시각에 서버가 실행 중이 아니었어요", None, now)
            await _post("sched", "plan", f"예약 · {job['name']} 놓침", where=_where(job),
                        body="그 시각에 lab.remote 서버가 실행 중이 아니었어요. 놓친 예약은 나중에 실행하지 않아요.", project=job["project"],
                        ref={"schedule": job["id"]}, subject=f"sched:{job['id']}:{job['nextAt']}:miss")
            done.append({"id": job["id"], "did": "missed"})
            continue
        if job["kind"] == "command":
            if await asyncio.to_thread(busy):
                if not job["waitingSince"]:
                    conn.execute("UPDATE schedules SET waiting_since = ? WHERE id = ?", (now, job["id"]))
                    await _post("sched", "plan", f"예약 · {job['name']} 기다리는 중", where=_where(job),
                                body="다른 학습이 GPU를 사용 중이에요. 끝나면 바로 시작하고 알림을 보내요.", project=job["project"],
                                ref={"schedule": job["id"]}, subject=f"sched:{job['id']}:{job['nextAt']}:wait")
                done.append({"id": job["id"], "did": "waiting"})
                continue
            try:
                run = await asyncio.to_thread(start_run, job)
            except Exception as exc:
                _finish(conn, job, f"시작하지 못했어요: {exc}", None, now)
                await _post("sched", "fail", f"예약 · {job['name']} 시작하지 못함", where=_where(job), body=str(exc)[:300],
                            project=job["project"], act=True, ref={"schedule": job["id"]}, subject=f"sched:{job['id']}:{job['nextAt']}:err")
                done.append({"id": job["id"], "did": "error"})
                continue
            _finish(conn, job, f"{run['id']} 시작", {"project": job["project"], "run": run["id"]}, now)
            await _post("sched", "plan", f"예약 · {job['name']} 시작", where=_where(job), body=f"{run['id']} · {job['command']}",
                        project=job["project"], ref={"project": job["project"], "run": run["id"], "schedule": job["id"]},
                        subject=f"sched:{job['id']}:{job['nextAt']}:start")
            done.append({"id": job["id"], "did": "started", "run": run["id"]})
        else:
            try:
                if start_session:
                    made = await start_session(job)
                else:
                    made = await manager.create(job["project"], text=job["prompt"], title=job["name"], tree=job["tree"],
                                                mode=job["mode"] or "manual", model=job["model"], effort=job["effort"])
            except Exception as exc:
                _finish(conn, job, f"세션을 열지 못했어요: {exc}", None, now)
                await _post("sched", "fail", f"예약 · {job['name']} 세션을 열지 못함", where=_where(job), body=str(exc)[:300],
                            project=job["project"], act=True, ref={"schedule": job["id"]}, subject=f"sched:{job['id']}:{job['nextAt']}:err")
                done.append({"id": job["id"], "did": "error"})
                continue
            _finish(conn, job, "세션을 열었어요", {"project": job["project"], "session": made["id"]}, now)
            await _post("sched", "plan", f"예약 · {job['name']} 세션 열림", where=_where(job),
                        body="요청을 보냈어요. 승인이 필요한 단계에서는 대기해요.", project=job["project"],
                        ref={"project": job["project"], "session": made["id"], "schedule": job["id"]},
                        subject=f"sched:{job['id']}:{job['nextAt']}:session")
            done.append({"id": job["id"], "did": "session", "session": made["id"]})
    return done
