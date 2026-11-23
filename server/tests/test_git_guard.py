"""`.git` 경유 탈출 — **오케스트레이터가 대신 실행해 주는 길.**

오케스트레이터의 git 은 **샌드박스 밖에서 사용자 권한으로** 돈다(의도된
비대칭 — 커밋·브랜치는 훅을 거치지 않는다). 그런데 샌드박스는 작업 디렉터리
쓰기를 못 막으므로(M4) AI 가 쓴 코드가 `.git/` 에 쓸 수 있다.

    .git/hooks/post-commit      커밋할 때 실행된다
    .git/config  core.hooksPath / filter.X.process / core.fsmonitor / include.path
    .gitattributes  * filter=X

여기서는 **실제로 악성 설정을 심어 두고** 오케스트레이터의 git 이 그걸
실행하지 않는지 본다. 가짜 없이 진짜 `git` 을 쓴다.
"""

import os
import shutil
import subprocess

import pytest

from app.git import guard as G
from app.git import ops

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git 이 없어요"
)

#: 훅·필터가 실행되면 여기에 흔적을 남긴다. 파일이 생기면 **실패**다.
MARK = "EXECUTED"


@pytest.fixture()
def repo(tmp_path):
    """커밋 하나가 있는 진짜 git 저장소."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.txt").write_text("hello\n", encoding="utf-8")
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "시험"],
        ["config", "user.email", "t@example.com"],
        ["add", "-A"],
        ["commit", "-q", "-m", "first"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=env)
    return str(root)


def _mark_path(tmp_path):
    return tmp_path / MARK


def _plant_hook(repo_root, name, mark):
    folder = os.path.join(repo_root, ".git", "hooks")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!/bin/sh\necho pwned > {mark}\n")
    os.chmod(path, 0o755)
    return path


def _append_config(repo_root, text):
    with open(os.path.join(repo_root, ".git", "config"), "a", encoding="utf-8") as fh:
        fh.write(text)


# --- 깨끗한 저장소 -------------------------------------------------------------


def test_깨끗하면_통과한다(repo):
    got = G.check(repo, config_args=ops.safe_config(), env=ops.safe_env())
    assert got["ok"] is True, got["problems"]


def test_기본_sample_훅은_봐준다(repo):
    """git init 이 `*.sample` 을 깔아 둔다 — 실행되지 않는다."""
    folder = os.path.join(repo, ".git", "hooks")
    assert any(n.endswith(".sample") for n in os.listdir(folder))
    assert G.bad_hooks(repo) == []


def test_평범한_git_작업은_그대로_된다(repo):
    assert ops.current_branch(repo) == "main"
    assert ops.inside_worktree(repo) is True
    assert ops.status_porcelain(repo) == []
    assert len(ops.log(repo, 5)) == 1
    with open(os.path.join(repo, "src", "b.txt"), "w", encoding="utf-8") as fh:
        fh.write("b\n")
    got = ops.commit(repo, "두 번째", ["src"])
    assert got["committed"] is True and got["sha"]


def test_신원이_없어도_커밋된다(repo):
    """`SAFE_ENV` 가 전역 설정을 끊는다 — 그래도 커밋이 돼야 한다."""
    subprocess.run(
        ["git", "-C", repo, "config", "--unset", "user.name"], check=False
    )
    subprocess.run(
        ["git", "-C", repo, "config", "--unset", "user.email"], check=False
    )
    with open(os.path.join(repo, "src", "c.txt"), "w", encoding="utf-8") as fh:
        fh.write("c\n")
    got = ops.commit(repo, "신원 없이", ["src"])
    assert got["committed"] is True
    assert "-c" in ops.commit_config()
    assert any("user.name=" in x for x in ops.commit_config())


# --- 🔑 훅이 실행되지 않는다 ---------------------------------------------------


def test_악성_post_commit_훅이_실행되지_않는다(repo, tmp_path):
    """가장 직접적인 길 — 오케스트레이터가 커밋할 때 실행된다."""
    mark = _mark_path(tmp_path)
    _plant_hook(repo, "post-commit", mark)

    # 1차 방어: guard 가 먼저 거부한다
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "post-commit" in str(err.value)

    # 2차 방어: 검사를 건너뛰어도 `-c core.hooksPath` 가 이긴다
    with open(os.path.join(repo, "src", "d.txt"), "w", encoding="utf-8") as fh:
        fh.write("d\n")
    ops.run(repo, ["add", "--", "src"], guarded=False)
    ops.run(repo, ["commit", "-m", "훅이 돌면 안 돼요"], guarded=False)
    assert not mark.exists(), "post-commit 훅이 실행됐어요"


def test_pre_commit_훅도_실행되지_않는다(repo, tmp_path):
    mark = _mark_path(tmp_path)
    _plant_hook(repo, "pre-commit", mark)
    with open(os.path.join(repo, "src", "e.txt"), "w", encoding="utf-8") as fh:
        fh.write("e\n")
    ops.run(repo, ["add", "--", "src"], guarded=False)
    ops.run(repo, ["commit", "-m", "x"], guarded=False)
    assert not mark.exists()


def test_core_hooksPath_를_심어도_이긴다(repo, tmp_path):
    """저장소 설정으로 훅 폴더를 바꿔도 `-c` 가 이긴다."""
    folder = tmp_path / "evil-hooks"
    folder.mkdir()
    mark = _mark_path(tmp_path)
    path = folder / "post-commit"
    path.write_text(f"#!/bin/sh\necho pwned > {mark}\n", encoding="utf-8")
    path.chmod(0o755)
    _append_config(repo, f"\n[core]\n\thooksPath = {folder}\n")

    with pytest.raises(G.GitRefused):
        ops.guard(repo)

    with open(os.path.join(repo, "src", "f.txt"), "w", encoding="utf-8") as fh:
        fh.write("f\n")
    ops.run(repo, ["add", "--", "src"], guarded=False)
    ops.run(repo, ["commit", "-m", "x"], guarded=False)
    assert not mark.exists()


# --- 🔑 필터가 실행되지 않는다 -------------------------------------------------


def test_filter_설정이면_git_을_안_돌린다(repo, tmp_path):
    """`-c` 로 덮을 수 없다(와일드카드) — 그래서 **멈춘다.**"""
    mark = _mark_path(tmp_path)
    _append_config(
        repo, f"\n[filter \"evil\"]\n\tclean = sh -c 'echo pwned > {mark}; cat'\n"
    )
    with open(os.path.join(repo, ".gitattributes"), "w", encoding="utf-8") as fh:
        fh.write("* filter=evil\n")

    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    text = str(err.value)
    assert "filter.evil.clean" in text
    assert ".gitattributes" in text

    # guard 를 지나가는 모든 호출이 막힌다 — 커밋도 status 도
    for call in (
        lambda: ops.commit(repo, "x", ["src"]),
        lambda: ops.status_porcelain(repo),
        lambda: ops.current_branch(repo),
    ):
        with pytest.raises(G.GitRefused):
            call()
    assert not mark.exists()


def test_textconv_도_잡는다(repo):
    _append_config(repo, "\n[diff \"evil\"]\n\ttextconv = /bin/sh\n")
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "diff.evil.textconv" in str(err.value)


def test_fsmonitor_를_잡는다(repo):
    """`git status` 할 때 실행된다."""
    _append_config(repo, "\n[core]\n\tfsmonitor = /tmp/evil.sh\n")
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "core.fsmonitor" in str(err.value)


def test_include_path_자체를_거부한다(repo, tmp_path):
    """`include.path` 는 파싱 시점에 끼어든다 — `-c` 로 못 막는다.

    ⚠ 그리고 `git config --list --local` 은 **include 가 끌어온 값을 보여
    주지 않는다**(실측). 그래서 끌어온 `filter.x.process` 는 우리 목록에
    안 보인다 — `include.path` **자체를 거부하는 것이 유일한 수단**이다.
    이 시험이 그 전제를 고정한다.
    """
    other = tmp_path / "evil.inc"
    other.write_text("[filter \"x\"]\n\tprocess = /bin/sh\n", encoding="utf-8")
    _append_config(repo, f"\n[include]\n\tpath = {other}\n")

    entries = G.config_entries(repo, config_args=ops.safe_config(), env=ops.safe_env())
    assert "include.path" in entries
    assert "filter.x.process" not in entries, (
        "--list --local 이 include 를 따라가면 이 시험을 지워도 돼요"
    )

    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "include.path" in str(err.value)


def test_includeIf_도_거부한다(repo, tmp_path):
    other = tmp_path / "evil.inc"
    other.write_text("[core]\n\thooksPath = /tmp/evil\n", encoding="utf-8")
    _append_config(repo, f'\n[includeIf "gitdir:**"]\n\tpath = {other}\n')
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "includeif" in str(err.value).lower()


def test_sshCommand_와_insteadOf_를_잡는다(repo):
    _append_config(repo, "\n[core]\n\tsshCommand = /tmp/evil.sh\n")
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "core.sshcommand" in str(err.value).lower()

    os.truncate(os.path.join(repo, ".git", "config"), 0)
    _append_config(repo, "[url \"/tmp/evil\"]\n\tinsteadOf = https://github.com/\n")
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert "insteadof" in str(err.value).lower()


def test_alias_와_credential_helper_를_잡는다(repo):
    _append_config(repo, "\n[alias]\n\tst = !sh -c 'echo pwned'\n")
    with pytest.raises(G.GitRefused):
        ops.guard(repo)
    os.truncate(os.path.join(repo, ".git", "config"), 0)
    _append_config(repo, "[credential]\n\thelper = !sh -c 'echo pwned'\n")
    with pytest.raises(G.GitRefused):
        ops.guard(repo)


def test_서브모듈을_거부한다(repo):
    with open(os.path.join(repo, ".gitmodules"), "w", encoding="utf-8") as fh:
        fh.write('[submodule "x"]\n\tpath = x\n\turl = /tmp/x\n')
    with pytest.raises(G.GitRefused) as err:
        ops.guard(repo)
    assert ".gitmodules" in str(err.value)


def test_하위_폴더의_gitattributes_도_본다(repo):
    with open(os.path.join(repo, "src", ".gitattributes"), "w", encoding="utf-8") as fh:
        fh.write("*.py diff=evil\n")
    got = G.bad_attributes(repo)
    assert got and "src/.gitattributes" in got[0]


def test_주석과_빈_줄은_넘어간다(repo):
    with open(os.path.join(repo, ".gitattributes"), "w", encoding="utf-8") as fh:
        fh.write("# filter=evil 은 주석이에요\n\n*.bin binary\n")
    assert G.bad_attributes(repo) == []


def test_git_info_attributes_도_본다(repo):
    folder = os.path.join(repo, ".git", "info")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "attributes"), "w", encoding="utf-8") as fh:
        fh.write("* filter=evil\n")
    got = G.bad_attributes(repo)
    assert got and "attributes" in got[0]


# --- 환경·설정 고정 -----------------------------------------------------------


def test_환경이_화이트리스트다():
    env = ops.safe_env({"HOME": "/h", "PATH": "/b", "LAB_DATA_DIR": "/secret",
                        "GIT_CONFIG_GLOBAL": "/evil", "ANTHROPIC_API_KEY": "k"})
    assert "LAB_DATA_DIR" not in env
    assert "ANTHROPIC_API_KEY" not in env
    # 고정값이 넘어온 값을 **이긴다**
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ATTR_NOSYSTEM"] == "1"


def test_안전_설정에_필요한_것이_다_있다():
    flat = " ".join(ops.safe_config())
    assert f"core.hooksPath={ops.nohooks_dir()}" in flat
    for key in (
        "core.fsmonitor=false", "core.sshCommand=", "core.editor=false",
        "credential.helper=", "diff.external=", "core.attributesFile=",
        "protocol.allow=never",
    ):
        assert key in flat, key


def test_빈_훅_폴더가_server_data_아래다():
    """샌드박스 안에서 그 폴더 쓰기가 실패하므로(M1b) AI 가 훅을 못 넣는다."""
    from app import registry

    folder = ops.nohooks_dir()
    assert folder.startswith(registry.data_dir())
    assert os.path.isdir(folder)
    assert os.listdir(folder) == []
