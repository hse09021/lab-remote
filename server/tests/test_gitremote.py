"""소스 제어 — 브랜치 · 원격 연결 · fetch/pull/push/동기화 · 스테이징 · 초기화 · GitHub 게시.

원격은 로컬 bare 저장소로 흉내 낸다. 실제 화면에서는 https · ssh만 열지만,
시험에서는 `NET_PROTOCOLS`에 file을 더해 같은 경로를 탄다.
"""

import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import main
from app.git import actions, ops, remote

H = {"X-Lab-Remote": "1"}


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


@pytest.fixture()
def repo(project):
    _git(project, "init", "-q", "-b", "main")
    _write(project, "src/train.py", "lr = 0.001\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "init")
    return project


@pytest.fixture()
def file_net(monkeypatch):
    monkeypatch.setattr(ops, "NET_PROTOCOLS", ("https", "ssh", "file"))


@pytest.fixture()
def origin(repo, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    return bare


def test_원격_주소_검사와_가리기(repo):
    with pytest.raises(actions.ActionError, match="토큰"):
        remote.set_remote(repo, "https://me:ghp_secret@github.com/me/demo.git")
    for bad in ("/tmp/x", "file:///tmp/x", "ext::sh -c id", "-oProxyCommand=x", "http://github.com/me/demo"):
        with pytest.raises(actions.ActionError, match="형식"):
            remote.set_remote(repo, bad)
    got = remote.set_remote(repo, "git@github.com:me/demo.git")
    assert got["remotes"] == [{"name": "origin", "url": "git@github.com:me/demo.git"}]
    got = remote.set_remote(repo, "https://github.com/me/demo.git")  # 있으면 주소만 바꿔요
    assert got["remotes"] == [{"name": "origin", "url": "https://github.com/me/demo.git"}]
    assert remote.mask_url("https://u:t@host/x") == "https://host/x"


def test_기본_git은_원격과_주고받지_않는다(repo, origin, file_net):
    # net=False(화면의 읽기 · 커밋)는 protocol.allow=never 그대로예요
    with pytest.raises(ops.GitError):
        ops.run(repo, ["fetch", "origin"])
    # net=True도 https · ssh 밖의 프로토콜은 열지 않아요
    ops.NET_PROTOCOLS = ("https", "ssh")
    with pytest.raises(actions.ActionError, match="https나 ssh"):
        remote.push(repo)


def test_브랜치_게시_push_pull_동기화(repo, origin, file_net, tmp_path):
    got = remote.info(repo)
    assert got["upstream"] == "" and got["remotes"][0]["name"] == "origin"
    got = remote.push(repo)  # 원격 브랜치가 없으면 -u로 게시해요
    assert got["upstream"] == "origin/main" and got["ahead"] == 0

    # 다른 사람이 원격에 커밋을 올려요
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    _write(other, "README.md", "hi\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "readme")
    _git(other, "push", "-q")

    got = remote.fetch(repo)
    assert got["behind"] == 1
    # 로컬에도 커밋이 있으면 push는 거절돼요 (force 없음)
    _write(repo, "src/train.py", "lr = 0.002\n")
    actions.commit(repo, "lr")
    with pytest.raises(actions.ActionError, match="먼저 pull"):
        remote.push(repo)
    got = remote.sync(repo)  # pull(merge) 뒤 push
    assert got["ahead"] == 0 and got["behind"] == 0
    assert os.path.exists(os.path.join(repo, "README.md"))


def test_pull_충돌이면_머지를_취소해요(repo, origin, file_net, tmp_path):
    remote.push(repo)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    _write(other, "src/train.py", "lr = 9\n")
    _git(other, "commit", "-qam", "theirs")
    _git(other, "push", "-q")
    _write(repo, "src/train.py", "lr = 1\n")
    actions.commit(repo, "mine")
    with pytest.raises(actions.ActionError, match="충돌"):
        remote.pull(repo)
    assert not os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD"))
    assert open(os.path.join(repo, "src", "train.py")).read() == "lr = 1\n"


def test_push할_때_저장소_훅은_실행되지_않는다(repo, origin, file_net, tmp_path):
    mark = tmp_path / "pwned"
    hook = os.path.join(repo, ".git", "hooks", "pre-push")
    with open(hook, "w") as fh:
        fh.write(f"#!/bin/sh\ntouch {mark}\n")
    os.chmod(hook, 0o755)
    remote.push(repo)
    assert not mark.exists()


def test_브랜치_만들기와_전환(repo, origin, file_net):
    with pytest.raises(actions.ActionError, match="브랜치 이름"):
        remote.create_branch(repo, "bad name")
    with pytest.raises(actions.ActionError, match="브랜치 이름"):
        remote.create_branch(repo, "-x")
    got = remote.create_branch(repo, "exp/lr")
    assert got["branch"] == "exp/lr"
    remote.push(repo)
    got = remote.checkout(repo, "main")
    assert got["branch"] == "main"
    _git(repo, "branch", "-D", "exp/lr")
    got = remote.checkout(repo, "origin/exp/lr")  # 원격 브랜치면 추적 브랜치를 만들어요
    assert got["branch"] == "exp/lr" and got["upstream"] == "origin/exp/lr"
    with pytest.raises(actions.ActionError, match="없는 브랜치"):
        remote.checkout(repo, "nope")


def test_스테이징한_것만_커밋해요(repo):
    _write(repo, "src/a.py", "a\n")
    _write(repo, "src/b.py", "b\n")
    remote.stage(repo, ["src/a.py"])
    got = actions.commit(repo, "a만")
    assert got["files"] == ["src/a.py"]
    remote.stage(repo, ["src/b.py"])
    remote.unstage(repo, ["src/b.py"])
    got = actions.commit(repo, "나머지 전부")  # 스테이징한 게 없으면 전부
    assert got["files"] == ["src/b.py"]
    with pytest.raises(actions.ActionError):
        remote.stage(repo, ["../outside.txt"])


def test_저장소_초기화(project):
    assert remote.info(project)["state"] == "none"
    got = remote.init(project)
    assert got["state"] == "ok" and got["branch"] == "main" and got["hasCommit"] is False
    with pytest.raises(actions.ActionError, match="이미"):
        remote.init(project)
    # 커밋이 없을 때 새 브랜치는 이름만 바꿔요
    assert remote.create_branch(project, "dev")["branch"] == "dev"


def test_GitHub에_게시(repo, monkeypatch):
    calls = []

    class Done:
        returncode = 0
        stdout = "https://github.com/me/demo\n"
        stderr = ""

    def fake(cmd):
        calls.append(cmd)
        return Done()

    monkeypatch.setattr(remote, "push", lambda base: {"state": "ok", "upstream": "origin/main"})
    with pytest.raises(actions.ActionError, match="저장소 이름"):
        remote.publish_github(repo, "bad name", runner=fake)
    got = remote.publish_github(repo, "demo", True, runner=fake)
    assert calls[0][1:] == ["repo", "create", "demo", "--private"]
    assert got["published"] == "https://github.com/me/demo"
    assert _git(repo, "remote", "get-url", "origin").strip() == "https://github.com/me/demo.git"
    with pytest.raises(actions.ActionError, match="이미 원격"):
        remote.publish_github(repo, "demo", runner=fake)


def test_API(repo, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    got = client.get("/api/projects/demo/git/repo", headers=H).json()
    assert got["state"] == "ok" and got["branch"] == "main" and [b["name"] for b in got["local"]] == ["main"]
    r = client.post("/api/projects/demo/git/branch", json={"name": "exp/a"}, headers=H)
    assert r.status_code == 200 and r.json()["branch"] == "exp/a"
    r = client.post("/api/projects/demo/git/push", json={}, headers=H)
    assert r.status_code == 409 and "원격 저장소" in r.json()["detail"]
    r = client.post("/api/projects/demo/git/remote", json={"url": "file:///x"}, headers=H)
    assert r.status_code == 400
