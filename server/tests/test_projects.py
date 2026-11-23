"""프로젝트 등록 · `.labremote/` · 설정 · 고정."""

import json
import os
import subprocess

import pytest

from app import projects, registry


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


def test_등록하면_labremote_폴더와_gitignore_를_만든다(project_root):
    made = projects.register(project_root, "demo")
    assert made == {"name": "demo", "root": project_root}
    folder = os.path.join(project_root, ".labremote")
    with open(os.path.join(folder, ".gitignore"), encoding="utf-8") as fh:
        assert fh.read().splitlines()[-1] == "*"
    with open(os.path.join(folder, "settings.json"), encoding="utf-8") as fh:
        assert json.load(fh)["share"] is False
    # 프로젝트의 .gitignore 는 만들지도 고치지도 않는다
    assert not os.path.exists(os.path.join(project_root, ".gitignore"))
    assert registry.root_of("demo") == project_root


def test_이름을_안_주면_폴더_이름으로(tmp_path):
    root = tmp_path / "My Project_2"
    root.mkdir()
    assert projects.register(str(root))["name"] == "my-project_2"


@pytest.mark.parametrize("bad", ["/", "~"])
def test_루트와_홈은_등록하지_않는다(bad):
    with pytest.raises(projects.ProjectError):
        projects.register(bad, "x")


def test_겹치는_폴더는_거절(project, tmp_path):
    inner = os.path.join(project, "src")
    with pytest.raises(projects.ProjectError, match="겹쳐요"):
        projects.register(inner, "inner")
    with pytest.raises(projects.ProjectError, match="겹쳐요"):
        projects.register(os.path.dirname(project), "outer")


def test_없는_폴더는_거절(tmp_path):
    with pytest.raises(projects.ProjectError, match="없어요"):
        projects.register(str(tmp_path / "nope"), "nope")


def test_labremote_가_링크면_거절(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", root / ".labremote")
    with pytest.raises(projects.ProjectError, match="폴더가 아니에요"):
        projects.register(str(root), "p")
    assert os.listdir(tmp_path / "elsewhere") == []


def test_repo_에_같이_올리기를_켜면_설정과_scenario_만_추적(project_root):
    _git(project_root, "init", "-q")
    projects.register(project_root, "demo")
    folder = os.path.join(project_root, ".labremote")
    os.makedirs(os.path.join(folder, "scenarios"))
    os.makedirs(os.path.join(folder, "worktrees", "x"))
    for rel in ("scenarios/main.json", "worktrees/x/a.txt", "runs.json"):
        with open(os.path.join(folder, rel), "w") as fh:
            fh.write("{}")

    def untracked():
        out = subprocess.run(
            ["git", "-C", project_root, "status", "--porcelain", "-uall"],
            capture_output=True, text=True, check=True,
        ).stdout
        return sorted(line[3:] for line in out.splitlines())

    assert not [p for p in untracked() if p.startswith(".labremote")]  # 통째로 빠진다
    projects.save_settings(project_root, {"share": True})
    shown = [p for p in untracked() if p.startswith(".labremote/")]
    assert shown == [
        ".labremote/.gitignore",
        ".labremote/scenarios/main.json",
        ".labremote/settings.json",
    ]
    projects.save_settings(project_root, {"share": False})
    assert not [p for p in untracked() if p.startswith(".labremote/")]


def test_설정_검사(project):
    saved = projects.save_settings(
        project,
        {"condaEnv": "lora-env", "commands": ["python train.py", "python train.py", " "], "metricGlobs": ["runs/*/metrics.csv"]},
    )
    assert saved["commands"] == ["python train.py"]
    assert projects.load_settings(project) == saved
    with pytest.raises(projects.ProjectError):
        projects.save_settings(project, {"condaEnv": "../evil"})
    with pytest.raises(projects.ProjectError):
        projects.save_settings(project, {"metricGlobs": ["../../etc/*"]})
    with pytest.raises(projects.ProjectError):
        projects.save_settings(project, {"commands": ["a\nb"]})


def test_해제는_기본으로_labremote_를_남긴다(project_root):
    projects.register(project_root, "demo")
    projects.set_pin("demo", True)
    out = projects.unregister("demo")
    assert out["removedLabremote"] is False
    assert os.path.isdir(os.path.join(project_root, ".labremote"))
    assert registry.root_of("demo") is None
    assert projects.pins() == []


def test_해제하며_labremote_만_지운다(project_root):
    projects.register(project_root, "demo")
    out = projects.unregister("demo", remove_labremote=True)
    assert out["removedLabremote"] is True
    assert not os.path.exists(os.path.join(project_root, ".labremote"))
    assert os.path.isdir(os.path.join(project_root, "src"))


def test_고정은_데이터_폴더에(project, isolated_data):
    projects.set_pin("demo", True)
    assert projects.pins() == ["demo"]
    assert os.path.exists(isolated_data / "ui.json")
    [row] = projects.list_projects()
    assert row["pinned"] is True and row["name"] == "demo"


def test_worktree_가_남아_있으면_labremote_를_안_지운다(project_root):
    projects.register(project_root, "demo")
    os.makedirs(os.path.join(project_root, ".labremote", "worktrees", "exp"))
    with pytest.raises(projects.ProjectError, match="worktree"):
        projects.unregister("demo", remove_labremote=True)
    assert registry.root_of("demo") == project_root  # 등록도 그대로
