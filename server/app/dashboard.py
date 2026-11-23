"""Dashboard Overview — 등록한 모든 프로젝트의 실행을 한데 모은다.

PR · 머지는 느린 명령(gh · git log)이라 `/api/dashboard/git`(gitfeed.py)에서 따로 준다.
에이전트는 `/api/agents/sessions`에서 따로 받는다. 그래서 여기서는 `null`로 둔다.
"""

from __future__ import annotations

import os
import time

from . import inbox, registry, runs

__all__ = ["overview", "self_usage", "CUT_WINDOW_SEC"]

#: 끊긴 실행 배너에 올리는 기간
CUT_WINDOW_SEC = 14 * 24 * 3600

_cpu_prev: tuple[float, float] | None = None


def self_usage() -> dict:
    """lab.remote 서버 자신의 CPU·메모리 — "서버는 가볍다" 를 눈으로 보여 주려고."""
    global _cpu_prev
    out: dict = {"cpuPct": None, "rssMb": None}
    try:
        with open("/proc/self/stat", encoding="ascii") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        ticks = os.sysconf("SC_CLK_TCK")
        cpu_sec = (int(fields[11]) + int(fields[12])) / ticks
        now = time.monotonic()
        if _cpu_prev and now > _cpu_prev[0]:
            out["cpuPct"] = round(100.0 * (cpu_sec - _cpu_prev[1]) / (now - _cpu_prev[0]), 1)
        _cpu_prev = (now, cpu_sec)
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    out["rssMb"] = round(int(line.split()[1]) / 1024)
    except (OSError, ValueError):
        pass
    return out


def overview(conn) -> dict:
    now = time.time()
    running, cut, finished_today = [], [], []
    projects_n = 0
    for root, name in sorted(registry.load().items(), key=lambda kv: kv[1]):
        projects_n += 1
        if not os.path.isdir(root):
            continue
        try:
            items = runs.list_runs(name)
        except Exception:  # 프로젝트 하나가 깨져도 대시보드는 뜬다
            continue
        for r in items:
            r["project"] = name
            if r["state"] == "running":
                try:
                    r["metrics"] = runs.metrics_summary(name, r["id"])
                except Exception:
                    r["metrics"] = None
                running.append(r)
            elif r["state"] == "cut" and not r.get("ack") and now - (r.get("endedAt") or 0) < CUT_WINDOW_SEC:
                cut.append(r)
            elif r["state"] in ("done", "failed") and now - (r.get("endedAt") or 0) < 24 * 3600:
                finished_today.append(r)
    running.sort(key=lambda r: r.get("startedAt") or 0)
    cut.sort(key=lambda r: -(r.get("endedAt") or 0))
    finished_today.sort(key=lambda r: -(r.get("endedAt") or 0))
    return {
        "now": now,
        "projects": projects_n,
        "runs": {
            "running": running,
            "cut": cut,
            "finishedToday": finished_today[:10],
            "failedToday": sum(1 for r in finished_today if r["state"] == "failed"),
        },
        "inbox": {"badge": inbox.badge(conn)},
        # 따로 받는다 (agents/sessions · dashboard/git)
        "agents": None,
        "prs": None,
        "merges": None,
        "self": self_usage(),
    }
