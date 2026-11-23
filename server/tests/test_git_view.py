"""git 읽기 — 상태·파일 표 표시·diff·worktree."""

import os
import subprocess

import pytest

from app.git import view


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture()
def repo(project_root):
    root = project_root
    _git(root, "init", "-q", "-b", "main")
    with open(os.path.join(root, "src", "a.py"), "w") as fh:
        fh.write("a = 1\n")
    with open(os.path.join(root, ".gitignore"), "w") as fh:
        fh.write("runs/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_git_이_아니면_상태로_알린다(project_root):
    assert view.summary(project_root)["state"] == "none"


def test_요약(repo):
    with open(os.path.join(repo, "src", "a.py"), "a") as fh:
        fh.write("b = 2\n")
    info = view.summary(repo)
    assert info["state"] == "ok" and info["branch"] == "main"
    assert info["changed"] == 1 and len(info["head"]) == 7


def test_파일_표의_git_칸(repo):
    os.makedirs(os.path.join(repo, "runs", "x"))
    open(os.path.join(repo, "runs", "x", "m.csv"), "w").close()
    with open(os.path.join(repo, "src", "a.py"), "a") as fh:
        fh.write("b = 2\n")
    open(os.path.join(repo, "new.txt"), "w").close()
    marks = view.marks_for(repo, "")
    assert marks["runs/"] == "gitignore"
    assert marks["src/"] == "수정"
    assert marks["new.txt"] == "새 파일"
    assert view.marks_for(repo, "src") == {"src/a.py": "수정"}


def test_diff(repo):
    with open(os.path.join(repo, "src", "a.py"), "a") as fh:
        fh.write("b = 2\n")
    out = view.diff(repo, "src/a.py")
    assert out["state"] == "ok" and "+b = 2" in out["diff"]


def test_worktree_와_합쳐진_표시(repo):
    wt = os.path.join(repo, ".labremote", "worktrees")
    os.makedirs(wt)
    _git(repo, "worktree", "add", "-q", "-b", "exp/done", os.path.join(wt, "done"))
    _git(repo, "worktree", "add", "-q", "-b", "exp/ahead", os.path.join(wt, "ahead"))
    _git(repo, "worktree", "add", "-q", "-b", "exp/fresh", os.path.join(wt, "fresh"))
    # exp/done 은 커밋하고 main 에 합친다
    with open(os.path.join(wt, "done", "d.txt"), "w") as fh:
        fh.write("d\n")
    _git(os.path.join(wt, "done"), "add", "d.txt")
    _git(os.path.join(wt, "done"), "commit", "-q", "-m", "d")
    _git(repo, "merge", "-q", "--ff-only", "exp/done")
    with open(os.path.join(wt, "ahead", "x.txt"), "w") as fh:
        fh.write("x\n")
    _git(os.path.join(wt, "ahead"), "add", "x.txt")
    _git(os.path.join(wt, "ahead"), "commit", "-q", "-m", "x")

    info = view.worktrees(repo)
    assert info["state"] == "ok" and info["main"] == "main"
    rows = {r["branch"]: r for r in info["worktrees"]}
    assert rows["main"]["primary"] is True and rows["main"]["merged"] is False
    assert rows["exp/done"]["merged"] is True and rows["exp/done"]["ahead"] == 0
    assert rows["exp/ahead"]["merged"] is False and rows["exp/ahead"]["ahead"] == 1
    # 막 만든 브랜치는 main 과 같은 커밋이어도 "합쳐짐" 이 아니다 (정리 대상 아님)
    assert rows["exp/fresh"]["merged"] is False
    assert rows["exp/done"]["rel"] == ".labremote/worktrees/done"
    # 정리(지우기)는 하지 않는다 — 표시만
    assert os.path.isdir(os.path.join(wt, "done"))


def test_하위_폴더를_등록해도_경로가_맞다(repo):
    with open(os.path.join(repo, "src", "a.py"), "a") as fh:
        fh.write("b = 2\n")
    info = view.status(os.path.join(repo, "src"))
    assert [c["path"] for c in info["changes"]] == ["a.py"]
