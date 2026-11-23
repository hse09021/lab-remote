"""등록한 프로젝트 목록과 데이터 폴더 위치."""

import os

import pytest

from app import registry


def test_등록_안_된_경로는_None(tmp_path):
    assert registry.lookup(str(tmp_path)) is None


def test_등록하면_찾는다(project_root):
    root = registry.register(project_root, "hook-sandbox")
    assert registry.lookup(root) == (root, "hook-sandbox")
    deep = os.path.join(root, "experiments", "EXP-007")
    assert registry.lookup(deep) == (root, "hook-sandbox")
    assert registry.root_of("hook-sandbox") == root


def test_형제_접두사_폴더는_다른_프로젝트(project_root, tmp_path):
    registry.register(project_root, "hook-sandbox")
    sibling = tmp_path / "projects" / "hook-sandbox-old"
    sibling.mkdir(parents=True)
    assert registry.lookup(str(sibling)) is None


def test_중첩되면_더_깊은_루트가_이긴다(project_root):
    registry.register(project_root, "hook-sandbox")
    inner = os.path.join(project_root, "experiments", "EXP-007")
    registry.register(inner, "inner")
    assert registry.lookup(os.path.join(inner, "x.py")) == (inner, "inner")


def test_같은_이름을_다른_경로에_쓰면_거절(project_root, tmp_path):
    registry.register(project_root, "hook-sandbox")
    other = tmp_path / "projects" / "other"
    other.mkdir(parents=True)
    with pytest.raises(registry.InvalidName):
        registry.register(str(other), "hook-sandbox")


def test_같은_경로_재등록은_괜찮다(project_root):
    registry.register(project_root, "hook-sandbox")
    assert registry.register(project_root, "hook-sandbox") == project_root


def test_등록_해제(project_root):
    registry.register(project_root, "hook-sandbox")
    assert registry.unregister("hook-sandbox") is True
    assert registry.unregister("hook-sandbox") is False
    assert registry.lookup(project_root) is None


@pytest.mark.parametrize(
    "name",
    ["../../etc", "a/b", "Hook-Sandbox", "", ".hidden", "a" * 65, "이름", "x_", "/abs"],
)
def test_나쁜_이름은_거절(name):
    with pytest.raises(registry.InvalidName):
        registry.valid_name(name)


@pytest.mark.parametrize("name", ["hook-sandbox", "exp1", "a", "a.b_c-d", "lora2"])
def test_좋은_이름은_통과(name):
    assert registry.valid_name(name) == name


def test_저장_경로가_데이터_폴더_안에_있다():
    data = registry.data_dir()
    assert os.path.commonpath([data, registry.projects_file()]) == data


def test_v1_상태_경로_함수는_없다():
    """정책·실행 상태·승인 요청·허가 폴더는 v3 에서 빠졌다."""
    for name in ("policy_path", "runstate_path", "pending_dir", "requests_dir",
                 "grants_dir", "projects_root"):
        assert not hasattr(registry, name), name


def test_깨진_레지스트리는_빈_dict():
    with open(registry.projects_file(), "w", encoding="utf-8") as fh:
        fh.write("깨진 JSON")
    assert registry.load() == {}


def test_원자적_쓰기_뒤에_임시_파일이_안_남는다(project_root):
    registry.register(project_root, "hook-sandbox")
    leftovers = [p for p in os.listdir(registry.data_dir()) if ".tmp." in p]
    assert leftovers == []


def test_LAB_DATA_DIR_를_따른다(monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path / "상태"))
    assert registry.data_dir() == str(tmp_path / "상태")
