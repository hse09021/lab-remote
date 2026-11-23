"""경로 판정 회귀 시험. 잠긴 항목 ①(프로젝트 폴더 밖)이 여기에 걸려 있다."""

import os

import pytest

from app import paths


@pytest.fixture()
def root(tmp_path):
    """실험 프로젝트 루트. tmp_path 자체가 링크일 수 있어 해소해 둔다."""
    p = tmp_path / "hook-sandbox"
    (p / "experiments" / "EXP-007").mkdir(parents=True)
    (p / "docs").mkdir()
    return paths.real(str(p))


def test_루트_자신은_안쪽(root):
    assert paths.rel_or_none(root, root) == "."


def test_평범한_안쪽_경로(root):
    tgt = paths.safe_resolve("experiments/EXP-007/train.py", root)
    assert paths.rel_or_none(root, tgt) == "experiments/EXP-007/train.py"


def test_상위로_빠져나가면_밖(root):
    tgt = paths.safe_resolve("experiments/../../etc/passwd", root)
    assert paths.rel_or_none(root, tgt) is None


def test_절대경로_밖(root):
    tgt = paths.safe_resolve("/etc/hosts", root)
    assert paths.rel_or_none(root, tgt) is None


def test_형제_접두사_경로는_밖(root, tmp_path):
    """`<root>-old`가 안쪽으로 보이면 안 된다. os.sep을 빼먹었을 때 생기는 버그."""
    sibling = tmp_path / "hook-sandbox-old"
    sibling.mkdir()
    tgt = paths.real(str(sibling / "x.txt"))
    assert tgt.startswith(root)  # 전제: 문자열로는 접두사가 맞다
    assert paths.rel_or_none(root, tgt) is None


def test_안쪽_심볼릭_링크가_밖을_가리키면_밖(root, tmp_path):
    outside = tmp_path / "datasets"
    outside.mkdir()
    os.symlink(str(outside), os.path.join(root, "data"))
    tgt = paths.safe_resolve("data/train.csv", root)
    assert paths.rel_or_none(root, tgt) is None


def test_루트_자체가_심볼릭_링크여도_안쪽은_안쪽(tmp_path):
    realroot = tmp_path / "real" / "hook-sandbox"
    realroot.mkdir(parents=True)
    link = tmp_path / "proj"
    os.symlink(str(realroot), str(link))

    # 훅은 cwd로 링크 경로를 받을 수 있다. 양쪽을 해소하면 안쪽으로 나와야 한다.
    tgt = paths.safe_resolve("src/train.py", str(link))
    assert paths.rel_or_none(str(link), tgt) == "src/train.py"
    assert paths.rel_or_none(str(realroot), tgt) == "src/train.py"


def test_없는_파일도_판정된다(root):
    tgt = paths.safe_resolve("docs/아직없음.md", root)
    assert paths.rel_or_none(root, tgt) == "docs/아직없음.md"


def test_깊은_cwd_의_상대경로(root):
    cwd = os.path.join(root, "experiments", "EXP-007")
    tgt = paths.safe_resolve("config.yaml", cwd)
    assert paths.rel_or_none(root, tgt) == "experiments/EXP-007/config.yaml"


def test_물결표는_홈으로_펼친다(root):
    tgt = paths.safe_resolve("~/x.txt", root)
    assert tgt == paths.real(os.path.join(os.path.expanduser("~"), "x.txt"))
    assert paths.rel_or_none(root, tgt) is None


def test_빈_경로는_cwd(root):
    assert paths.safe_resolve("", root) == root


def test_예외_허용_경로(root, tmp_path):
    outside = tmp_path / "datasets"
    outside.mkdir()
    os.symlink(str(outside), os.path.join(root, "data"))
    tgt = paths.safe_resolve("data/train.csv", root)

    assert paths.is_inside_any([str(outside)], tgt)
    assert not paths.is_inside_any([], tgt)
    assert not paths.is_inside_any([str(tmp_path / "other")], tgt)


def test_is_inside_는_빈_값에_False():
    assert not paths.is_inside("", "/tmp/x")
    assert not paths.is_inside("/tmp", "")


# --- glob ------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel, pattern, expected",
    [
        (".claude/settings.json", ".claude/**", True),
        (".claude/agents/x.md", ".claude/**", True),
        (".claude", ".claude/**", True),  # 폴더 자신도 대상
        (".claudex/settings.json", ".claude/**", False),
        ("experiments/EXP-007/config.yaml", "experiments/*/config.yaml", True),
        ("experiments/EXP-007/a/config.yaml", "experiments/*/config.yaml", False),
        ("experiments/EXP-007/analysis.md", "experiments/*/analysis.md", True),
        ("README.md", "experiments/*/analysis.md", False),
        ("docs/Evaluation.md", "docs/Evaluation.md", True),
        ("docs/evaluation.md", "docs/Evaluation.md", False),  # 대소문자 구분
        ("logs/Approval_log.csv", "logs/Approval_log.csv", True),
        ("docs/Stop_and_recovery.md", "docs/Evaluation.md", False),
        ("a/b/c/x.py", "**/x.py", True),
        ("x.py", "**/x.py", True),
    ],
)
def test_match_glob(rel, pattern, expected):
    assert paths.match_glob(rel, pattern) is expected


def test_match_globs_는_하나라도_맞으면_참():
    pats = ["docs/Evaluation.md", "specifications/Config.yaml"]
    assert paths.match_globs("specifications/Config.yaml", pats)
    assert not paths.match_globs("specifications/environment.yml", pats)
