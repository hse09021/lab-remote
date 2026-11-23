"""IDE — 검색 · 커밋 · main 에 합치기 · 터미널(WebSocket ↔ tmux)."""

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import main, runs, search, terminals
from app.git import actions, worktree

H = {"X-Lab-Remote": "1"}


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture()
def repo(project):
    _git(project, "init", "-q", "-b", "main")
    with open(os.path.join(project, "src", "train.py"), "w") as fh:
        fh.write("lr = 0.001\nepochs = 10\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "init")
    return project


def test_검색(repo):
    with open(os.path.join(repo, "src", "new.py"), "w") as fh:
        fh.write("LR_SCHEDULE = 'cos'\n")
    got = search.search(repo, "lr")
    assert {(r["path"], r["line"]) for r in got["results"]} == {("src/train.py", 1), ("src/new.py", 1)}
    assert got["via"] == "git grep"
    assert search.search(repo, "lr", case=True)["results"] == [{"path": "src/train.py", "line": 1, "text": "lr = 0.001"}]
    assert search.search(repo, "x")["results"] == []  # 두 글자부터


def test_git_이_아니면_걸어서_찾는다(project):
    with open(os.path.join(project, "src", "a.txt"), "w") as fh:
        fh.write("hello world\n")
    os.makedirs(os.path.join(project, "node_modules"))
    with open(os.path.join(project, "node_modules", "x.txt"), "w") as fh:
        fh.write("hello\n")
    got = search.search(project, "hello")
    assert got["via"] == "파일 걷기" and [r["path"] for r in got["results"]] == ["src/a.txt"]


def test_커밋과_main_에_합치기(repo):
    made = worktree.add(repo, "exp/lr")
    with open(os.path.join(made["path"], "src", "train.py"), "w") as fh:
        fh.write("lr = 0.0005\nepochs = 10\n")
    with pytest.raises(actions.ActionError, match="메시지"):
        actions.commit(made["path"], " ")
    got = actions.commit(made["path"], "lr 낮추기")
    assert got["files"] == ["src/train.py"]
    with pytest.raises(actions.ActionError, match="변경이 없어요"):
        actions.commit(made["path"], "또")
    # main 쪽에 커밋 안 한 변경이 있으면 거절
    with open(os.path.join(repo, "notes.md"), "w") as fh:
        fh.write("x\n")
    with pytest.raises(actions.ActionError, match="커밋 안 한 변경"):
        actions.merge_to_main(repo, "exp/lr")
    os.remove(os.path.join(repo, "notes.md"))
    out = actions.merge_to_main(repo, "exp/lr")
    assert out["main"] == "main"
    with open(os.path.join(repo, "src", "train.py")) as fh:
        assert "0.0005" in fh.read()


def test_충돌이면_되돌린다(repo):
    made = worktree.add(repo, "exp/a")
    for path, value in ((made["path"], "0.1"), (repo, "0.2")):
        with open(os.path.join(path, "src", "train.py"), "w") as fh:
            fh.write(f"lr = {value}\n")
        actions.commit(path, f"lr {value}")
    with pytest.raises(actions.ActionError, match="충돌"):
        actions.merge_to_main(repo, "exp/a")
    assert _git(repo, "status", "--porcelain") == ""  # 반쯤 합쳐진 채로 두지 않는다


pytestmark_tmux = pytest.mark.skipif(not runs.tmux_bin(), reason="tmux 가 없어요")


@pytestmark_tmux
def test_터미널_만들고_목록_지우기(project):
    try:
        t = terminals.create("demo", "src")
        assert t["name"] == "t-1"
        assert terminals.create("demo")["name"] == "t-2"
        names = [x["name"] for x in terminals.list_sessions("demo")]
        assert names == ["t-1", "t-2"]
        terminals.kill("demo", "t-1")
        assert [x["name"] for x in terminals.list_sessions("demo")] == ["t-2"]
        with pytest.raises(terminals.TerminalError):
            terminals.create("demo", "../")
        with pytest.raises(terminals.TerminalError):
            terminals.attach_argv("demo", name="t-9")
    finally:
        subprocess.run([runs.tmux_bin(), "-L", terminals.socket_of("demo"), "kill-server"], capture_output=True)


@pytestmark_tmux
def test_웹소켓_터미널(project, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    try:
        terminals.create("demo")
        # Origin 이 없거나 다른 사이트면 거절 — cross-site WebSocket hijacking
        # (TestClient 의 WebSocket 은 Host 를 testserver 로 보내서 직접 넣는다)
        for headers in ({"host": "127.0.0.1:8000"}, {"host": "127.0.0.1:8000", "origin": "https://evil.example"}):
            with pytest.raises(Exception):
                with client.websocket_connect("/api/terminals/ws?project=demo&name=t-1", headers=headers) as ws:
                    ws.receive_bytes()
        with client.websocket_connect(
            "/api/terminals/ws?project=demo&name=t-1", headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}
        ) as ws:
            ws.send_json({"type": "resize", "cols": 100, "rows": 30})
            ws.send_json({"type": "input", "data": "echo lab-$((40+2))\r"})
            seen = b""
            end = time.time() + 8
            while b"lab-42" not in seen and time.time() < end:
                seen += ws.receive_bytes()
            assert b"lab-42" in seen
    finally:
        subprocess.run([runs.tmux_bin(), "-L", terminals.socket_of("demo"), "kill-server"], capture_output=True)


def test_IDE_API(repo, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    assert client.get("/api/projects/demo/search", params={"q": "epochs"}).json()["results"][0]["line"] == 2
    assert client.get("/api/projects/demo/git/caps").json() == {"pr": actions.gh_available()}
    with open(os.path.join(repo, "src", "train.py"), "a") as fh:
        fh.write("seed = 1\n")
    r = client.post("/api/projects/demo/git/commit", json={"message": "seed"}, headers=H)
    assert r.status_code == 200 and r.json()["files"] == ["src/train.py"]
    assert client.post("/api/projects/demo/git/merge", json={"branch": "nope"}, headers=H).status_code == 409


@pytestmark_tmux
def test_학습에_붙는_건_기본이_보기_전용(project):
    run = runs.start("demo", "sleep 20")
    try:
        argv = terminals.attach_argv("demo", run=run["id"])
        assert argv[-1] == "-r" and "attach-session" in argv
        assert "-r" not in terminals.attach_argv("demo", run=run["id"], write=True)
    finally:
        runs.stop("demo", run["id"], force=True)
    with pytest.raises(terminals.TerminalError, match="실행 중이 아니라"):
        terminals.attach_argv("demo", run=run["id"])
