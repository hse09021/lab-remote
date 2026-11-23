"""공통 픽스처.

`server/data/`를 건드리지 않도록 `LAB_DATA_DIR`을 테스트마다 임시 폴더로
돌린다. 웹훅 설정(`discord.json`)도 그 안에 있어서 같이 격리된다.
"""

import os
import pathlib

import pytest

#: 저장소 루트. web/ 의 mock JSON을 대조하는 데 쓴다.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """lab.remote 데이터 폴더(프로젝트 목록·`lab.db`·웹훅 설정)를 임시 폴더로."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("LAB_DATA_DIR", str(data))
    # 진짜 웹훅으로 새지 않게
    monkeypatch.delenv("LAB_DISCORD_WEBHOOK", raising=False)
    # 서버의 실행 감시 스레드를 시험에서는 띄우지 않는다
    monkeypatch.setenv("LAB_NO_WATCH", "1")
    return data


@pytest.fixture(autouse=True)
def no_systemd_scope(monkeypatch):
    """시험에서는 실행을 systemd scope에 담지 않는다.

    시험이 `systemd-run --user --scope`를 쓰면 user systemd에 매이고
    transient 유닛이 기계에 남는다.
    """
    from app.runner import process as process_mod

    monkeypatch.setenv(process_mod.NO_SCOPE_ENV, "1")


@pytest.fixture()
def conn(isolated_data):
    """이행까지 끝난 `lab.db` 연결. 테스트마다 빈 DB 다."""
    from app import db

    with db.open_db() as connection:
        yield connection


@pytest.fixture()
def project_root(tmp_path):
    """등록은 안 된 빈 프로젝트 폴더."""
    root = tmp_path / "projects" / "demo"
    (root / "src").mkdir(parents=True, exist_ok=True)
    return os.path.realpath(str(root))


@pytest.fixture()
def project(project_root):
    """등록까지 끝난 프로젝트. 이름은 `demo`."""
    from app import registry

    registry.register(project_root, "demo")
    return project_root


@pytest.fixture(autouse=True)
def no_tunnel_cli(monkeypatch):
    """시험에서는 진짜 `code tunnel`을 부르지 않는다 (느리고 기계마다 다르다)."""
    from app import tunnel

    monkeypatch.setattr(tunnel, "_run", lambda argv: (-1, "시험에서는 부르지 않아요"))
    monkeypatch.setattr(tunnel, "_cache", None)
