"""모니터 루프.

**어떤 예외도 루프를 멈추지 못한다.** 모니터가 죽으면 "자리를 비워도 돈다" 의
절반이 사라진다.
"""

import os

import pytest

from app import registry
from app.monitor import daemon as D
from app.monitor import snapshot as S
from app.store import resources as R


@pytest.fixture()
def two_projects(isolated_data, tmp_path, conn):
    from app import policy

    roots = {}
    for name in ("hook-sandbox", "other-proj"):
        root = tmp_path / "projects" / name
        (root / "experiments").mkdir(parents=True, exist_ok=True)
        registry.register(str(root), name)
        policy.ensure(name, str(root))
        roots[name] = str(root)
    return roots


def test_한_바퀴에_모든_프로젝트를_쓴다(two_projects, conn):
    got = D.tick(conn)
    assert sorted(got["wrote"]) == ["hook-sandbox", "other-proj"]
    assert got["problems"] == []
    for name in two_projects:
        assert S.read(name)["project"] == name


def test_자원_표본을_쌓는다(two_projects, conn):
    D.tick(conn)
    latest = R.latest(conn)
    assert latest is not None
    assert latest["disk_free_gb"] is not None


def test_한_프로젝트가_깨져도_나머지를_쓴다(two_projects, conn, monkeypatch):
    real = S.write

    def flaky(connection, project, **kw):
        if project == "hook-sandbox":
            raise RuntimeError("일부러 깨뜨림")
        return real(connection, project, **kw)

    monkeypatch.setattr(S, "write", flaky)
    got = D.tick(conn)
    assert got["wrote"] == ["other-proj"]
    assert any("hook-sandbox" in p for p in got["problems"])


def test_표본이_깨져도_상태_파일은_쓴다(two_projects, conn, monkeypatch):
    from app.monitor import gpu as G

    monkeypatch.setattr(G, "probe", lambda: (_ for _ in ()).throw(RuntimeError("GPU 폭발")))
    got = D.tick(conn)
    assert sorted(got["wrote"]) == ["hook-sandbox", "other-proj"]
    assert any("표본" in p for p in got["problems"])


def test_정해진_횟수만_돈다(two_projects):
    naps = []
    got = D.run(rounds=3, interval_sec=0.01, sleep=naps.append)
    assert got["rounds"] == 3
    assert got["failures"] == 0
    assert len(naps) == 2  # 마지막엔 안 쉰다


def test_한_바퀴에_걸린_시간을_간격에서_뺀다(two_projects, monkeypatch):
    naps = []
    monkeypatch.setattr(D, "tick", lambda conn, **kw: {"wrote": [], "problems": [], "sample": None})
    D.run(rounds=2, interval_sec=5.0, sleep=naps.append)
    assert naps and naps[0] <= 5.0


def test_CPU_표본을_다음_바퀴로_넘긴다(two_projects, conn):
    """표본이 하나면 CPU 를 "모른다" 고 한다. 두 바퀴째부터 값이 나온다."""
    first = D.tick(conn)
    assert first["sample"] is not None
    second = D.tick(conn, host_before=first["sample"])
    assert second["problems"] == []
    cpu = S.read("hook-sandbox")["raw"]["host"]["cpuPct"]
    assert cpu is None or 0 <= cpu <= 100


def test_등록된_프로젝트가_없으면_조용히_넘어간다(isolated_data, conn):
    got = D.tick(conn)
    assert got["wrote"] == []
    assert got["problems"] == []


def test_승인_대기를_파일에서_읽는다(two_projects, conn):
    from app import approval_log as A

    A.open_request("hook-sandbox", "toolu_1", {"actions": [{"action": "pkg", "name": "패키지 설치"}]})
    D.tick(conn)
    approval = S.read("hook-sandbox")["dashboard"]["approval"]
    assert approval and approval["count"] == 1
    assert "패키지 설치" in approval["text"]
