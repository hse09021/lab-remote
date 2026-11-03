"""공통 픽스처.

`server/data/` 를 건드리지 않도록 `LAB_DATA_DIR` 과 `LAB_PROJECTS_DIR` 를
테스트마다 임시 폴더로 돌린다. 생성기가 붙는 8단계에서 여기에
`project` 픽스처(실제로 프로젝트를 만드는)가 추가된다.
"""

import os
import pathlib

import pytest

#: 저장소 루트. web/ 의 mock JSON 을 대조하는 데 쓴다.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """정책·레지스트리·실행 상태를 임시 폴더로."""
    data = tmp_path / "data"
    projects = tmp_path / "projects"
    data.mkdir()
    projects.mkdir()
    monkeypatch.setenv("LAB_DATA_DIR", str(data))
    monkeypatch.setenv("LAB_PROJECTS_DIR", str(projects))
    return data


@pytest.fixture()
def project_root(tmp_path):
    """등록은 안 된 빈 프로젝트 폴더."""
    root = tmp_path / "projects" / "hook-sandbox"
    for sub in ("docs", "specifications", "logs", "experiments/EXP-007", "src"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return os.path.realpath(str(root))
