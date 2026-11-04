"""모니터 루프 — 5초마다 상태를 적는다.

오케스트레이터와 **따로 돈다**(systemd 사용자 서비스 두 개). 학습이
오래 돌 때 오케스트레이터는 `wait` 에 묶여 있고, 화면은 그 사이에도
갱신돼야 한다.

**어떤 예외도 루프를 멈추지 못한다.** 모니터가 죽으면 "자리를 비워도 돈다" 의
절반이 사라진다. 실패는 세어 두고 계속 돈다.
"""

from __future__ import annotations

import time

from .. import db, registry
from ..store import resources as R
from . import host as host_mod
from . import snapshot as snapshot_mod

__all__ = ["INTERVAL_SEC", "PRUNE_EVERY", "tick", "run"]

#: 표본 간격. 목업의 리소스 바가 이 주기로 움직인다.
INTERVAL_SEC = 5.0

#: 몇 번마다 오래된 표본을 버리나 (5초 간격이면 약 1시간)
PRUNE_EVERY = 720

#: 표본을 몇 개 남기나 (5초 간격이면 약 28시간)
KEEP_SAMPLES = 20000


def tick(conn, *, host_before=None, pending_of=None) -> dict:
    """한 바퀴. 등록된 모든 프로젝트의 상태 파일을 쓰고 표본을 쌓는다."""
    projects = registry.load()
    wrote: list[str] = []
    problems: list[str] = []
    sample = host_mod.cpu_times()

    for root, name in sorted(projects.items()):
        try:
            pending = pending_of(name) if pending_of else _pending(name)
            snapshot_mod.write(
                conn, name, root=root, host_before=host_before, pending=pending
            )
            wrote.append(name)
        except Exception as exc:  # 한 프로젝트가 깨져도 나머지는 쓴다
            problems.append(f"{name}: {type(exc).__name__}: {exc}")

    # 자원 표본은 프로젝트와 무관하게 한 줄 (호스트 하나니까)
    try:
        from . import gpu as gpu_mod

        gpu = gpu_mod.probe()
        host = host_mod.probe(".", before=host_before)
        device = (gpu.get("devices") or [{}])[0]
        memory = host.get("memory") or {}
        disk = host.get("disk") or {}
        R.add(
            conn,
            gpu_available=bool(gpu.get("available")),
            gpu_util=device.get("utilPct"),
            gpu_mem_used_mb=int(device["memUsedMb"]) if device.get("memUsedMb") is not None else None,
            gpu_temp_c=device.get("tempC"),
            cpu_pct=host.get("cpuPct"),
            ram_pct=memory.get("pct"),
            disk_free_gb=disk.get("freeGb"),
            note=gpu.get("reason") or None,
        )
    except Exception as exc:
        problems.append(f"표본: {type(exc).__name__}: {exc}")

    return {"wrote": wrote, "problems": problems, "sample": sample}


def _pending(project: str) -> list[dict]:
    """승인 대기 — 파일이 진실이다 (`data/requests/`)."""
    from .. import approval_log as A

    try:
        return A.list_requests(project)
    except Exception:
        return []


def run(*, interval_sec: float = INTERVAL_SEC, rounds: int | None = None, sleep=None) -> dict:
    """모니터 루프. `rounds` 를 주면 그만큼만 돈다 (시험·`monitor once` 용).

    `sleep` 을 바꿔 끼울 수 있다 — 시험에서 실제로 기다리지 않게.
    """
    napper = sleep or time.sleep
    done = 0
    failures = 0
    sample = None
    with db.open_db() as conn:
        while rounds is None or done < rounds:
            started = time.time()
            got = tick(conn, host_before=sample)
            sample = got["sample"]
            failures += len(got["problems"])
            done += 1
            if done % PRUNE_EVERY == 0:
                try:
                    R.prune(conn, keep=KEEP_SAMPLES)
                except Exception:
                    pass
            if rounds is not None and done >= rounds:
                break
            # 한 바퀴에 걸린 시간을 빼서 간격을 지킨다
            napper(max(0.0, interval_sec - (time.time() - started)))
    return {"rounds": done, "failures": failures}
