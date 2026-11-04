"""CPU·RAM·디스크 — `/proc` 와 `statvfs` 만.

`psutil` 이 없고 ② 범위 밖이다. 같은 인터페이스 뒤에 나중에 붙일 수 있다.

CPU 사용률은 **두 표본의 차분**이다. `/proc/stat` 은 부팅 이후 누적값이라
한 번만 읽으면 "부팅 이후 평균" 이 나온다 — 지금 바쁜지 알 수 없다.
"""

from __future__ import annotations

import os

__all__ = ["cpu_times", "cpu_pct", "memory", "disk", "load_average", "probe"]

PROC_STAT = "/proc/stat"
PROC_MEMINFO = "/proc/meminfo"


def cpu_times() -> tuple[int, int] | None:
    """`(바쁜 시간, 전체 시간)` 누적값. 못 읽으면 None."""
    try:
        with open(PROC_STAT, encoding="utf-8") as fh:
            line = fh.readline()
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(v) for v in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    return total - idle, total


def cpu_pct(before: tuple[int, int] | None, after: tuple[int, int] | None) -> float | None:
    """두 표본 사이의 사용률. 표본이 없거나 시간이 안 흘렀으면 None."""
    if not before or not after:
        return None
    busy = after[0] - before[0]
    total = after[1] - before[1]
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * busy / total)), 1)


def memory() -> dict:
    """`/proc/meminfo` 기준. `MemAvailable` 을 쓴다 — `MemFree` 는 캐시를
    빼서 "거의 꽉 찼다" 로 보이게 한다."""
    values: dict[str, int] = {}
    try:
        with open(PROC_MEMINFO, encoding="utf-8") as fh:
            for line in fh:
                name, _, rest = line.partition(":")
                number = rest.strip().split(" ")[0]
                if number.isdigit():
                    values[name] = int(number)  # kB
    except OSError:
        return {"ok": False, "reason": f"{PROC_MEMINFO} 를 읽을 수 없어요"}
    total = values.get("MemTotal")
    if not total:
        return {"ok": False, "reason": "MemTotal 이 없어요"}
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = total - available
    return {
        "ok": True,
        "totalGb": round(total / 1024**2, 1),
        "usedGb": round(used / 1024**2, 1),
        "availableGb": round(available / 1024**2, 1),
        "pct": round(100.0 * used / total, 1),
    }


def disk(path: str) -> dict:
    try:
        stat = os.statvfs(path)
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    free = stat.f_bavail * stat.f_frsize
    total = stat.f_blocks * stat.f_frsize
    if not total:
        return {"ok": False, "reason": "크기가 0이에요"}
    return {
        "ok": True,
        "freeGb": round(free / 1024**3, 1),
        "totalGb": round(total / 1024**3, 1),
        "pct": round(100.0 * (1 - free / total), 1),
    }


def load_average() -> list[float] | None:
    try:
        return [round(v, 2) for v in os.getloadavg()]
    except OSError:  # pragma: no cover - 리눅스에서는 늘 된다
        return None


def probe(path: str = ".", *, before: tuple[int, int] | None = None) -> dict:
    """한 덩어리로. `before` 를 주면 그 표본과의 차분으로 CPU 를 계산한다.

    안 주면 CPU 는 `None` 이다 — **거짓말보다 모른다고 하는 게 낫다.**
    """
    now = cpu_times()
    return {
        "cpuPct": cpu_pct(before, now),
        "cpuSample": now,
        "memory": memory(),
        "disk": disk(path),
        "load": load_average(),
    }
