"""끝난 실험 산출물 정리.

체크포인트는 금방 수십 GB 가 된다. **재개용은 버리고 결과용은 남긴다.**

⚠ 이 파일들은 훅의 `outputProtect` 대상이라 Claude 는 못 지운다.
오케스트레이터는 훅을 거치지 않으니 지울 수 있다 — 의도된 비대칭이고,
그래서 지우는 조건을 코드가 좁게 쥔다.
"""

import os

import pytest

from app.runner import artifacts as A


@pytest.fixture()
def output(project_root):
    folder = os.path.join(project_root, "experiments", "EXP-001", "output")
    os.makedirs(folder, exist_ok=True)
    for name in (
        "epoch_001.ckpt",
        "epoch_002.ckpt",
        "step_5000.ckpt",
        "last.ckpt",
        "best.ckpt",
        "final.ckpt",
        "train.log",
        "result.csv",
        "probes.json",
    ):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write("x" * 100)
    return folder


def test_재개용만_지운다(output, project_root):
    got = A.prune_checkpoints(output, project_root=project_root)
    assert got["ok"] is True
    assert sorted(got["removed"]) == ["epoch_001.ckpt", "epoch_002.ckpt", "last.ckpt", "step_5000.ckpt"]
    left = sorted(os.listdir(output))
    assert left == ["best.ckpt", "final.ckpt", "probes.json", "result.csv", "train.log"]


def test_되찾은_용량을_알려_준다(output, project_root):
    assert A.prune_checkpoints(output, project_root=project_root)["freedBytes"] == 400


def test_미리보기는_안_지운다(output, project_root):
    got = A.prune_checkpoints(output, project_root=project_root, dry_run=True)
    assert len(got["removed"]) == 4
    assert len(os.listdir(output)) == 9


def test_결과용_패턴이_먼저_이긴다(project_root):
    """`best.ckpt` 를 `ckpt_*` 같은 패턴으로 잡는 사고를 막는다."""
    folder = os.path.join(project_root, "experiments", "EXP-002", "output")
    os.makedirs(folder, exist_ok=True)
    for name in ("best.ckpt", "final.pt"):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write("x")
    got = A.prune_checkpoints(
        folder, project_root=project_root, resume_patterns=("best.*", "final.*", "*")
    )
    assert got["removed"] == []
    assert sorted(os.listdir(folder)) == ["best.ckpt", "final.pt"]


def test_프로젝트_밖은_건드리지_않는다(tmp_path, project_root):
    outside = tmp_path / "남의폴더"
    outside.mkdir()
    (outside / "epoch_001.ckpt").write_text("x", encoding="utf-8")
    got = A.prune_checkpoints(str(outside), project_root=project_root)
    assert got["ok"] is False
    assert (outside / "epoch_001.ckpt").exists()


def test_상대경로로_빠져나가도_안_된다(project_root, tmp_path):
    (tmp_path / "epoch_001.ckpt").write_text("x", encoding="utf-8")
    escape = os.path.join(project_root, "experiments", "..", "..")
    assert A.prune_checkpoints(escape, project_root=project_root)["ok"] is False
    assert (tmp_path / "epoch_001.ckpt").exists()


def test_없는_폴더는_조용히_넘어간다(project_root):
    got = A.prune_checkpoints(
        os.path.join(project_root, "experiments", "없는실험", "output"),
        project_root=project_root,
    )
    assert got["ok"] is False


def test_심볼릭_링크는_안_지운다(output, project_root):
    """링크를 지우면 원본이 어디 있는지 모른 채 사라진 것처럼 보인다."""
    link = os.path.join(output, "epoch_999.ckpt")
    os.symlink(os.path.join(output, "best.ckpt"), link)
    got = A.prune_checkpoints(output, project_root=project_root)
    assert "epoch_999.ckpt" not in got["removed"]
    assert os.path.islink(link)


def test_디스크_여유를_읽는다(project_root):
    got = A.disk_usage(project_root)
    assert got["ok"] is True
    assert got["freeGb"] > 0 and 0 <= got["usedPct"] <= 100


def test_없는_경로의_디스크_조회는_정상_실패(project_root):
    assert A.disk_usage("/없는경로/없음")["ok"] is False
