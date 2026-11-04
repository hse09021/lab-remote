"""📌 git 기록 앵커 — **이전 커밋을 바꿔치기하면 들킨다.**

T4 는 `.git` 이 **코드를 실행하게 만드는 설정**을 막았다. 이건 **기록
자체**다 — `.git` 은 프로젝트 안이고 샌드박스는 작업 디렉터리 쓰기를 못
막으므로(M4) AI 가 쓴 코드가 이렇게 할 수 있다.

    git branch -D exp-003     실험 브랜치를 지운다
    git commit --amend        이전 커밋을 바꿔치기한다
    git reset --hard <옛것>    기록을 되감는다

막을 수 없으므로 **들키게** 한다 — 앵커는 `lab.db` 에 있고 샌드박스 안에서
그 파일 쓰기가 실패한다(M1b).

여기서는 **진짜 git 으로 실제로 위조해 보고** 잡히는지 본다.
"""

import os
import shutil
import subprocess

import pytest

from app.git import anchor as AN
from app.git import ops
from app.store import anchors as A

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 이 없어요")

PROJECT = "hook-sandbox"


def _git(root, *args, check=True):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check, capture_output=True, text=True, env=env,
    )


def _touch(root, name, text="x\n"):
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture()
def repo(tmp_path):
    """커밋 둘이 있는 진짜 저장소."""
    root = str(tmp_path / "repo")
    os.makedirs(os.path.join(root, "src"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "시험")
    _git(root, "config", "user.email", "t@example.com")
    _touch(root, "src/a.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    _touch(root, "src/b.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "second")
    return root


# --- 적고 대조하기 -----------------------------------------------------------


def test_적은_직후에는_맞는다(repo, conn):
    got = AN.record(conn, PROJECT, repo, "main")
    assert got["ok"] is True and len(got["sha"]) == 40
    assert AN.verify(conn, PROJECT, repo)["ok"] is True


def test_앵커가_없으면_볼_것이_없다(repo, conn):
    got = AN.verify(conn, PROJECT, repo)
    assert got["ok"] is True and got["checked"] == 0


def test_앞으로_나아가면_맞는다(repo, conn):
    """새 커밋을 쌓는 것은 정상이다 — 앵커가 조상이면 통과."""
    AN.record(conn, PROJECT, repo, "main")
    _touch(repo, "src/c.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "third")
    assert AN.verify(conn, PROJECT, repo)["ok"] is True


def test_브랜치_전부를_적는다(repo, conn):
    _git(repo, "branch", "exp-001")
    _git(repo, "branch", "exp-002")
    AN.record_all(conn, PROJECT, repo)
    saved = {a["key"] for a in A.listing(conn, PROJECT, AN.KIND)}
    assert saved == {"main", "exp-001", "exp-002"}


# --- 🔑 위조를 잡는다 ---------------------------------------------------------


def test_브랜치를_지우면_잡는다(repo, conn):
    """실험 브랜치를 지워 기록을 없애는 길."""
    _git(repo, "branch", "exp-003")
    AN.record_all(conn, PROJECT, repo)
    _git(repo, "branch", "-D", "exp-003")

    got = AN.verify(conn, PROJECT, repo)
    assert got["ok"] is False
    assert any("exp-003 브랜치가 사라졌어요" in p for p in got["problems"])


def test_amend_로_바꿔치기하면_잡는다(repo, conn):
    """이전 커밋의 내용을 바꾸는 길. 해시가 바뀌고 옛 해시는 조상이 아니다."""
    AN.record(conn, PROJECT, repo, "main")
    before = AN.verify(conn, PROJECT, repo)
    assert before["ok"] is True

    _touch(repo, "src/b.txt", "위조된 내용\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "-m", "second (위조)")

    got = AN.verify(conn, PROJECT, repo)
    assert got["ok"] is False
    assert any("되감겼어요" in p or "없어졌어요" in p for p in got["problems"]), got


def test_reset_hard_로_되감으면_잡는다(repo, conn):
    AN.record(conn, PROJECT, repo, "main")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")

    got = AN.verify(conn, PROJECT, repo)
    assert got["ok"] is False
    assert any("되감겼어요" in p for p in got["problems"]), got


def test_refs_를_직접_써도_잡는다(repo, conn):
    """`.git/refs/heads/main` 을 손으로 쓰는 길 — git 명령을 안 거친다."""
    AN.record(conn, PROJECT, repo, "main")
    old = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
    with open(os.path.join(repo, ".git", "refs", "heads", "main"), "w", encoding="utf-8") as fh:
        fh.write(old + "\n")

    got = AN.verify(conn, PROJECT, repo)
    assert got["ok"] is False
    assert any("되감겼어요" in p for p in got["problems"]), got


def test_verify_는_아무것도_고치지_않는다(repo, conn):
    AN.record(conn, PROJECT, repo, "main")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    AN.verify(conn, PROJECT, repo)
    # 되돌리지 않는다 — 무엇이 정본인지 알 수 없다
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() != head
    assert A.get(conn, PROJECT, AN.KIND, key="main")["value"] == head


# --- fsck -------------------------------------------------------------------


def test_fsck_가_깨끗한_저장소를_통과한다(repo):
    got = AN.fsck(repo)
    assert got["ok"] is True, got


def test_fsck_가_깨진_객체를_찾는다(repo):
    """객체 파일을 망가뜨려 본다."""
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    path = os.path.join(repo, ".git", "objects", head[:2], head[2:])
    if not os.path.exists(path):
        pytest.skip("객체가 pack 안이에요")
    # git 은 객체 파일을 0444 로 둔다. AI 가 쓴 코드도 chmod 하면 쓸 수 있다.
    os.chmod(path, 0o644)
    with open(path, "wb") as fh:
        fh.write(b"\x00\x01\x02 broken")
    got = AN.fsck(repo)
    assert got["ok"] is False and got["ran"] is True


def test_check_가_둘을_합친다(repo, conn):
    AN.record(conn, PROJECT, repo, "main")
    got = AN.check(conn, PROJECT, repo)
    assert got["ok"] is True and got["fsck"]["ok"] is True


# --- 루프가 멈추나 -----------------------------------------------------------


def test_루프_시작_전에_어긋나면_시작하지_않는다(repo, conn, monkeypatch, project):
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx
    from app.store import loops as LP

    AN.record(conn, PROJECT, repo, "main")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")

    ctx = runner_ctx.LoopCtx(project=PROJECT, root=repo, preset="full")
    sent = []
    monkeypatch.setattr(
        loop_mod.notifier, "send", lambda *a, **k: sent.append(k) or {"ok": True}
    )
    assert loop_mod.guard_anchor(ctx, conn, when="루프 시작 전") is False
    assert LP.ensure(conn, PROJECT)["state"] == "blocked"
    assert sent and "git 기록이 바뀌었어요" in sent[0]["title"]


def test_git_저장소가_아니면_조용히_넘어간다(tmp_path, conn):
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx

    plain = tmp_path / "plain"
    plain.mkdir()
    ctx = runner_ctx.LoopCtx(project=PROJECT, root=str(plain), preset="full")
    assert loop_mod.guard_anchor(ctx, conn, when="시험") is True


def test_앵커_표는_종류를_나눠_담는다(conn):
    """S7 의 승인 로그 해시 체인도 같은 표를 쓴다."""
    A.put(conn, PROJECT, AN.KIND, "abc", key="main")
    A.put(conn, PROJECT, "approval_log", "deadbeef", key="csv", count=42)
    assert A.get(conn, PROJECT, AN.KIND, key="main")["value"] == "abc"
    got = A.get(conn, PROJECT, "approval_log", key="csv")
    assert got["value"] == "deadbeef" and got["count"] == 42
    assert len(A.listing(conn, PROJECT)) == 2


# --- 학습 bwrap 이 .git 을 덮나 (T5) -----------------------------------------


def test_bwrap_이_프로젝트_안_보호_파일을_읽기_전용으로_덮는다(tmp_path):
    from app.runner import sandbox

    root = tmp_path / "proj"
    for rel in (".claude", ".git", "logs", "state", "src"):
        (root / rel).mkdir(parents=True)
    (root / ".mcp.json").write_text("{}", encoding="utf-8")
    (root / "logs" / "Approval_log.csv").write_text("h\n", encoding="utf-8")
    (root / "logs" / "hook_events.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "state" / "Current.yaml").write_text("x: 1\n", encoding="utf-8")

    got = sandbox.protected_inside(str(root))
    names = {os.path.relpath(p, str(root)) for p in got}
    assert names == {
        ".claude", ".git", ".mcp.json",
        "logs/Approval_log.csv", "logs/hook_events.jsonl", "state/Current.yaml",
    }

    argv = sandbox.command(["/bin/true"], project_root=str(root), hide=[], bwrap="/bin/bwrap")
    # 🔑 순서: `--bind <프로젝트>` 가 먼저, `--ro-bind <보호 파일>` 이 **뒤**.
    # 뒤집히면 조용히 쓰기 가능해진다.
    bind_at = argv.index(str(root))
    for item in got:
        assert argv[argv.index(item) - 1] == "--ro-bind", item
        assert argv.index(item) > bind_at, item


def test_bwrap_은_없는_파일을_덮지_않는다(tmp_path):
    """`--ro-bind` 는 원본이 없으면 실패한다."""
    from app.runner import sandbox

    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    assert sandbox.protected_inside(str(root)) == []


def test_bwrap_은_프로젝트_밖은_이_목록으로_안_덮는다(tmp_path):
    from app.runner import sandbox

    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    argv = sandbox.command(
        ["/bin/true"], project_root=str(root), hide=[],
        ro_inside=[str(outside)], bwrap="/bin/bwrap",
    )
    assert str(outside) not in argv
