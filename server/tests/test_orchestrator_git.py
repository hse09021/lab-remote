"""브랜치와 기록 커밋 — **로컬만.**

실험이 도는 동안에는 브랜치를 절대 바꾸지 않는다. 훅이 계속 쓰는 파일
(`Approval_log.csv`) 때문에 전환이 실패할 수 있어서, 전환 전에 커밋한다.
**강제 전환(`-f`)은 하지 않는다** — 강제로 밀면 그 기록이 사라진다.
"""

import os
import subprocess

import pytest

from app.git import ops
from app.orchestrator import gitflow


@pytest.fixture()
def repo(project_root):
    def git(*args):
        subprocess.run(["git", "-C", project_root, *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "시험@lab.remote")
    git("config", "user.name", "시험")
    for sub in ("logs", "state", "experiments"):
        os.makedirs(os.path.join(project_root, sub), exist_ok=True)
    with open(os.path.join(project_root, "logs", "Approval_log.csv"), "w", encoding="utf-8") as fh:
        fh.write("when,action\n")
    git("add", "-A")
    git("commit", "-m", "첫 커밋")
    return project_root


def write(root, rel, text="x\n"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


# --- 저수준 -------------------------------------------------------------------


def test_저장소인지_본다(repo, tmp_path):
    assert ops.inside_worktree(repo) is True
    assert ops.inside_worktree(str(tmp_path / "아무데나")) is False


def test_브랜치를_만들고_옮긴다(repo):
    assert ops.current_branch(repo) == "main"
    ops.create_branch(repo, "exp-001")
    assert ops.current_branch(repo) == "exp-001"
    assert "exp-001" in ops.branches(repo)
    ops.switch(repo, "main")
    assert ops.current_branch(repo) == "main"


def test_이미_있는_브랜치는_그냥_옮긴다(repo):
    ops.create_branch(repo, "exp-001")
    ops.switch(repo, "main")
    ops.create_branch(repo, "exp-001")
    assert ops.current_branch(repo) == "exp-001"


def test_지정한_경로만_커밋한다(repo):
    """자유 `add -A` 는 만들지 않는다 — git 은 훅을 거치지 않는다."""
    write(repo, "logs/Decision_log.md", "- 결정\n")
    write(repo, "src/비밀.py", "secret = 1\n")
    got = ops.commit(repo, "기록", ["logs"])
    assert got["committed"] is True
    assert got["paths"] == ["logs/Decision_log.md"]
    # git 은 추적 안 된 폴더를 `?? src/` 로 묶어 보여 준다
    assert "src/" in "\n".join(ops.status_porcelain(repo))  # 안 담겼다


def test_바뀐_게_없으면_커밋_안_한다(repo):
    assert ops.commit(repo, "빈 커밋", ["logs"])["committed"] is False


def test_경로를_안_주면_거절한다(repo):
    with pytest.raises(ops.GitError):
        ops.commit(repo, "x", [])


def test_없는_경로는_건너뛴다(repo):
    got = ops.commit(repo, "x", ["없는폴더"])
    assert got["committed"] is False and "아직 없어요" in got["reason"]


def test_로그와_HEAD_를_읽는다(repo):
    assert ops.head_sha(repo)
    rows = ops.log(repo, 1)
    assert rows and rows[0]["subject"] == "첫 커밋"


def test_git_실패는_GitError(repo):
    with pytest.raises(ops.GitError):
        ops.run(repo, ["switch", "없는브랜치"])


# --- 루프 흐름 ------------------------------------------------------------------


def test_실험을_시작하면_브랜치로_옮긴다(repo):
    got = gitflow.start_experiment(repo, "EXP-007")
    assert got["ok"] is True
    assert got["branch"] == "exp-007"
    assert got["from"] == "main"


def test_전환_전에_훅이_쓴_기록을_커밋한다(repo):
    """안 하면 전환이 실패한다."""
    write(repo, "logs/Approval_log.csv", "지금,허용\n")
    got = gitflow.start_experiment(repo, "EXP-007")
    assert got["committed"]["committed"] is True
    assert got["branch"] == "exp-007"
    assert ops.status_porcelain(repo, ["logs"]) == []


def test_실험이_도는_중에는_안_바꾼다(repo):
    got = gitflow.start_experiment(repo, "EXP-007", running=True)
    assert got["ok"] is False
    assert "도는 중" in got["reason"]
    assert ops.current_branch(repo) == "main"


def test_기록을_main_에_남기고_돌아온다(repo):
    gitflow.start_experiment(repo, "EXP-007")
    write(repo, "experiments/EXP-007/result.csv", "step,split,metric,value\n1,train,loss,2.0\n")
    write(repo, "logs/Decision_log.md", "- EXP-007 을 돌렸어요\n")
    got = gitflow.record_and_return(repo, "EXP-007")

    assert got["ok"] is True
    assert ops.current_branch(repo) == "main"
    # 기록이 main 에 있다
    assert os.path.exists(os.path.join(repo, "experiments/EXP-007/result.csv"))
    assert "EXP-007" in ops.log(repo, 1)[0]["subject"]


def test_실험_브랜치는_남는다(repo):
    """병합·push 는 ③ 이후다. 브랜치는 보존한다."""
    gitflow.start_experiment(repo, "EXP-007")
    gitflow.record_and_return(repo, "EXP-007")
    assert "exp-007" in ops.branches(repo)


def test_도는_중이면_기록_커밋도_안_한다(repo):
    gitflow.start_experiment(repo, "EXP-007")
    got = gitflow.record_and_return(repo, "EXP-007", running=True)
    assert got["ok"] is False
    assert ops.current_branch(repo) == "exp-007"


def test_저장소가_아니면_조용히_넘어간다(project_root):
    got = gitflow.start_experiment(project_root, "EXP-001")
    assert got["ok"] is False and "git 저장소가 아니에요" in got["reason"]


def test_브랜치_이름_규칙():
    assert gitflow.branch_name("EXP-007") == "exp-007"
    assert gitflow.branch_name("exp-007") == "exp-007"
