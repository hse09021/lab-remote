"""IDE — 검색 · 커밋 · main에 합치기 · 터미널(WebSocket ↔ tmux)."""

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


pytestmark_tmux = pytest.mark.skipif(not runs.tmux_bin(), reason="tmux가 없어요")


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
        # Origin이 없거나 다른 사이트면 거절 — cross-site WebSocket hijacking
        # (TestClient의 WebSocket은 Host를 testserver로 보내서 직접 넣는다)
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


def test_worktree_만들기와_정리(repo, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    r = client.post("/api/projects/demo/git/worktrees", json={"branch": "exp/wd"}, headers=H)
    assert r.status_code == 200, r.text
    rel = r.json()["rel"]
    assert rel == ".labremote/worktrees/wd"
    assert client.post("/api/projects/demo/git/worktrees", json={"branch": "-x"}, headers=H).status_code == 400

    # 커밋 안 한 변경이 있으면 git이 거절한다 (--force 안 씀)
    with open(os.path.join(repo, rel, "src", "train.py"), "a") as fh:
        fh.write("x = 1\n")
    r = client.post("/api/projects/demo/git/worktrees/remove", json={"rel": rel}, headers=H)
    assert r.status_code == 409 and "커밋" in r.json()["detail"]
    _git(os.path.join(repo, rel), "checkout", "--", "src/train.py")

    # 프로젝트 본체나 .labremote/worktrees 밖은 정리하지 않는다
    assert client.post("/api/projects/demo/git/worktrees/remove", json={"rel": ""}, headers=H).status_code == 409
    assert client.post("/api/projects/demo/git/worktrees/remove", json={"rel": "src"}, headers=H).status_code == 409

    r = client.post("/api/projects/demo/git/worktrees/remove", json={"rel": rel}, headers=H)
    assert r.status_code == 200 and r.json() == {"removed": rel}
    assert not os.path.exists(os.path.join(repo, rel))
    assert "exp/wd" in _git(repo, "branch", "--list", "exp/wd")  # 브랜치는 남는다


def test_최근_머지(repo, monkeypatch):
    from app import gitfeed

    made = worktree.add(repo, "exp/feed")
    with open(os.path.join(repo, made["rel"], "src", "train.py"), "a") as fh:
        fh.write("feed = 1\n")
    actions.commit(os.path.join(repo, made["rel"]), "feed")
    actions.merge_to_main(repo, "exp/feed")
    got = gitfeed.merges()
    assert got["week"] == 1 and got["today"] == 1
    assert got["items"][0]["project"] == "demo" and got["items"][0]["branch"] == "exp/feed"
    # gh가 없으면 없다고 말한다
    monkeypatch.setattr(gitfeed.shutil, "which", lambda name: None)
    assert gitfeed.prs()["available"] is False


def test_PR_열기는_push_된_브랜치만(repo, tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    made = worktree.add(repo, "exp/pr")
    calls = []

    class Done:
        returncode = 0
        stdout = "Creating pull request\nhttps://github.com/me/demo/pull/7\n"
        stderr = ""

    def fake(cmd):
        calls.append(cmd)
        return Done()

    with pytest.raises(actions.ActionError, match="제목"):
        actions.create_pr(made["path"], " ", runner=fake)
    # 아직 원격에 없어요 — lab.remote는 push하지 않아요
    with pytest.raises(actions.ActionError, match="원격에 없어요"):
        actions.create_pr(made["path"], "lr 낮추기", runner=fake)
    _git(made["path"], "push", "-q", "-u", "origin", "exp/pr")
    got = actions.create_pr(made["path"], "lr 낮추기", "본문", runner=fake)
    assert got == {"url": "https://github.com/me/demo/pull/7", "number": "7", "branch": "exp/pr"}
    assert calls[-1][1:4] == ["pr", "create", "--head"] and "lr 낮추기" in calls[-1]
    # 원격보다 앞선 커밋이 있으면 먼저 push하라고 해요
    with open(os.path.join(made["path"], "src", "train.py"), "a") as fh:
        fh.write("x = 1\n")
    actions.commit(made["path"], "더")
    with pytest.raises(actions.ActionError, match="1개 앞서요"):
        actions.create_pr(made["path"], "lr 낮추기", runner=fake)
    # main에서는 열지 않아요
    with pytest.raises(actions.ActionError, match="main이 아닌"):
        actions.create_pr(repo, "x", runner=fake)


def test_합치면_Inbox에_남아요(repo, tmp_path):
    from app import db, inbox

    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    made = worktree.add(repo, "exp/m")
    with open(os.path.join(made["path"], "src", "train.py"), "a") as fh:
        fh.write("y = 2\n")
    actions.commit(made["path"], "y")
    r = client.post("/api/projects/demo/git/merge", json={"branch": "exp/m"}, headers=H)
    assert r.status_code == 200
    with db.open_db() as conn:
        got = inbox.items(conn, kind="pr")
    assert any("exp/m" in x["title"] and "합침" in x["title"] for x in got)


def test_세션_카드_git_상태(repo, monkeypatch):
    from app import gitfeed

    monkeypatch.setattr(gitfeed, "feed", lambda **_: {"merges": {}, "prs": {"available": True, "items": [
        {"project": "demo", "number": 3, "title": "t", "branch": "exp/c", "state": "리뷰 기다림", "ci": "", "url": "u"}]}})
    made = worktree.add(repo, "exp/c")
    with open(os.path.join(repo, made["rel"], "src", "train.py"), "a") as fh:
        fh.write("a = 1\nb = 2\n")
    got = gitfeed.session_cards([
        {"id": "s1", "project": "demo", "tree": made["rel"], "branch": "exp/c"},
        {"id": "s2", "project": "demo", "tree": ".", "branch": "main"},
    ], fresh=True)
    assert got["s1"] == {"add": 2, "del": 0, "files": 1, "pr": {"number": 3, "state": "리뷰 기다림", "url": "u"}}
    assert got["s2"] == {"add": 0, "del": 0, "files": 0, "pr": None}


def test_파일_되돌리기(repo):
    with open(os.path.join(repo, "src", "train.py"), "a") as fh:
        fh.write("bad = 1\n")
    with open(os.path.join(repo, "src", "new.py"), "w") as fh:
        fh.write("x\n")
    assert actions.discard(repo, "src/train.py") == {"path": "src/train.py", "removed": False}
    assert open(os.path.join(repo, "src", "train.py")).read() == "lr = 0.001\nepochs = 10\n"
    assert actions.discard(repo, "src/new.py")["removed"] is True
    assert not os.path.exists(os.path.join(repo, "src", "new.py"))
    with pytest.raises(actions.ActionError):
        actions.discard(repo, "src/train.py")  # 이제 변경이 없어요
    with pytest.raises(actions.ActionError):
        actions.discard(repo, "../outside.txt")


def test_파일_출처(repo, tmp_path):
    import json as _json

    from app.agents.manager import manager

    d = manager._dir(repo)
    os.makedirs(d, exist_ok=True)
    sid = "s-0123456789"
    with open(os.path.join(d, f"{sid}.json"), "w") as fh:
        _json.dump({"id": sid, "project": "demo", "title": "rank 64 설정", "tree": ".", "state": "idle", "updatedAt": 1}, fh)
    with open(os.path.join(d, f"{sid}.jsonl"), "w") as fh:
        fh.write(_json.dumps({"at": 100, "type": "tool", "name": "Write", "input": {"file_path": os.path.join(repo, "src", "r64.yaml")}}) + "\n")
        fh.write(_json.dumps({"at": 200, "type": "tool", "name": "Read", "input": {"file_path": os.path.join(repo, "src", "train.py")}}) + "\n")
    got = manager.file_origin("demo", repo, "src/r64.yaml")
    assert got == {"session": sid, "title": "rank 64 설정", "at": 100.0, "tool": "Write", "closed": False}
    assert manager.file_origin("demo", repo, "src/train.py") is None  # 읽기만 한 건 출처가 아니에요
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    assert client.get("/api/projects/demo/files/origin", params={"path": "src/r64.yaml"}).json()["origin"]["session"] == sid
