"""CPU·RAM·디스크 — `/proc` 와 `statvfs` 만.

`psutil` 이 없고 ② 범위 밖이다. 특히 CPU 는 **두 표본의 차분**이어야 한다 —
`/proc/stat` 은 부팅 이후 누적값이라 한 번만 읽으면 "부팅 이후 평균" 이 나온다.
"""

import pytest

from app.monitor import host as H


def test_CPU_표본을_읽는다():
    sample = H.cpu_times()
    assert sample is not None
    busy, total = sample
    assert 0 <= busy <= total


def test_CPU_사용률은_두_표본의_차분():
    before = (100, 1000)
    after = (150, 1100)
    assert H.cpu_pct(before, after) == 50.0


def test_표본이_하나면_모른다고_한다():
    """"부팅 이후 평균" 을 지금 사용률처럼 보여 주면 거짓말이다."""
    assert H.cpu_pct(None, (100, 1000)) is None
    assert H.cpu_pct((100, 1000), None) is None


def test_시간이_안_흘렀으면_모른다고_한다():
    assert H.cpu_pct((100, 1000), (100, 1000)) is None


def test_사용률은_0에서_100_사이로_맞춘다():
    assert H.cpu_pct((0, 0), (999, 100)) == 100.0
    assert H.cpu_pct((500, 1000), (400, 1100)) == 0.0


def test_proc_stat_이_이상하면_None(tmp_path, monkeypatch):
    path = tmp_path / "stat"
    path.write_text("이건 proc 형식이 아니에요\n", encoding="utf-8")
    monkeypatch.setattr(H, "PROC_STAT", str(path))
    assert H.cpu_times() is None


def test_proc_stat_이_없으면_None(monkeypatch):
    monkeypatch.setattr(H, "PROC_STAT", "/없는경로/stat")
    assert H.cpu_times() is None


# --- 메모리 -------------------------------------------------------------------


def test_메모리를_읽는다():
    got = H.memory()
    assert got["ok"] is True
    assert got["totalGb"] > 0
    assert 0 <= got["pct"] <= 100
    assert got["usedGb"] + got["availableGb"] == pytest.approx(got["totalGb"], abs=0.2)


def test_MemAvailable_을_쓴다(tmp_path, monkeypatch):
    """`MemFree` 는 캐시를 빼서 "거의 꽉 찼다" 로 보이게 한다."""
    path = tmp_path / "meminfo"
    path.write_text(
        "MemTotal:       32000000 kB\nMemFree:          500000 kB\n"
        "MemAvailable:   16000000 kB\nCached:         15000000 kB\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(H, "PROC_MEMINFO", str(path))
    got = H.memory()
    assert got["pct"] == 50.0  # MemFree 로 계산하면 98% 가 된다


def test_meminfo_가_없으면_정상_실패(monkeypatch):
    monkeypatch.setattr(H, "PROC_MEMINFO", "/없는경로/meminfo")
    got = H.memory()
    assert got["ok"] is False and "읽을 수 없어요" in got["reason"]


def test_MemTotal_이_없으면_정상_실패(tmp_path, monkeypatch):
    path = tmp_path / "meminfo"
    path.write_text("Cached: 100 kB\n", encoding="utf-8")
    monkeypatch.setattr(H, "PROC_MEMINFO", str(path))
    assert H.memory()["ok"] is False


# --- 디스크 -------------------------------------------------------------------


def test_디스크를_읽는다(tmp_path):
    got = H.disk(str(tmp_path))
    assert got["ok"] is True
    assert got["freeGb"] > 0 and got["totalGb"] > 0
    assert 0 <= got["pct"] <= 100


def test_없는_경로는_정상_실패():
    assert H.disk("/없는경로/없음")["ok"] is False


# --- 한 덩어리 ----------------------------------------------------------------


def test_probe_는_키가_정해져_있다(tmp_path):
    got = H.probe(str(tmp_path))
    assert set(got) == {"cpuPct", "cpuSample", "memory", "disk", "load"}
    assert got["cpuPct"] is None  # 표본이 하나면 모른다
    assert got["load"] is None or len(got["load"]) == 3


def test_앞_표본을_주면_CPU_가_나온다(tmp_path):
    before = H.cpu_times()
    got = H.probe(str(tmp_path), before=before)
    assert got["cpuPct"] is None or 0 <= got["cpuPct"] <= 100
