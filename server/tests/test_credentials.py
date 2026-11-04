"""홈의 자격 증명 — 세 겹으로 막는다.

`--ro-bind / /` 만 하면 홈이 전부 읽히고, **네트워크가 열려 있으니 읽힌 건 곧
나간다.** SSH 키 하나로 저장소가, AWS 자격 증명 하나로 계정이 열린다.

| 층 | 막는 것 | 어디 |
|---|---|---|
| 학습 샌드박스 | AI 가 쓴 **코드**가 읽는 것 | `runner/sandbox.home_dirs` — 홈을 통째로 가림 |
| 훅 `SECRET_FILES` | Claude 의 **도구 호출** | `policy_defaults.SECRET_FILES` |
| 훅 `readOutside` | 프로젝트 밖 읽기 전부 | 헤드리스에서 승인 대상 |
"""

import os

import pytest

from app import policy_defaults as D
from app.hooks import classify

#: 읽히면 안 되는 것. 사용자가 꼽은 목록 그대로.
CREDENTIALS = [
    "~/.ssh/id_rsa",
    "~/.ssh/id_ed25519",
    "~/.gnupg/secring.gpg",
    "~/.git-credentials",
    "~/.netrc",
    "~/.aws/credentials",
    "~/.docker/config.json",
    "~/.kaggle/kaggle.json",
    "~/.config/gh/hosts.yml",
    "~/.pypirc",
    "~/.npmrc",
    "~/.mozilla/firefox/profile/logins.json",
    "~/.config/google-chrome/Default/Login Data",
    "~/.config/Code/User/settings.json",
    "~/.bash_history",
    "~/.zsh_history",
    "~/.kube/config",
    "~/.cache/huggingface/token",
    "~/.claude/.credentials.json",
]

#: 비밀이 아닌 것 — git 원격을 쓰려면 봐야 한다.
NOT_SECRET = ["~/.ssh/id_ed25519.pub", "~/.ssh/known_hosts", "~/.ssh/config"]


def one(ctx, tool, tool_input):
    return classify.classify_event({"tool_name": tool, "tool_input": tool_input}, ctx)


def actions(found):
    return sorted(f.action for f in found)


# --- 훅: 도구 호출 -------------------------------------------------------------


@pytest.mark.parametrize("path", CREDENTIALS)
def test_Read_로는_자격_증명을_못_읽는다(ctx, path):
    assert actions(one(ctx, "Read", {"file_path": os.path.expanduser(path)})) == ["secret"]


@pytest.mark.parametrize("path", CREDENTIALS)
def test_Bash_로도_못_읽는다(ctx, path):
    """`cat ~/.ssh/id_rsa` 도 같은 판정을 받아야 한다."""
    assert "secret" in actions(one(ctx, "Bash", {"command": f"cat {path}"}))


@pytest.mark.parametrize("path", CREDENTIALS[:6])
def test_복사도_막힌다(ctx, path):
    expanded = os.path.expanduser(path)
    assert "secret" in actions(one(ctx, "Bash", {"command": f"cp {expanded} /tmp/몰래"}))


@pytest.mark.parametrize("path", ["~/.ssh", "~/.gnupg", "~/.aws", "~/.config/gh"])
def test_Glob_으로_훑는_것도_막힌다(ctx, path):
    assert actions(one(ctx, "Glob", {"pattern": "*", "path": os.path.expanduser(path)})) == [
        "secret"
    ]


def test_Glob_에_훅이_실제로_뜬다(sandboxed, project_root):
    """🔑 위 시험은 **거짓 초록불이었다.**

    판정 코드는 `Glob` 을 막도록 써 뒀는데, `PreToolUse` matcher 에 `Glob` 이
    없어서 **훅이 아예 안 떴다.** 번들의 matcher 비교는 이름을 나열하면
    정확 문자열 비교다. 판정만 시험하면 영원히 못 잡는다 — **설치된
    matcher** 를 같이 본다.
    """
    import json

    from app.hooks import install

    install.install(mode="enforce")
    with open(install.settings_path(), encoding="utf-8") as fh:
        data = json.load(fh)
    matchers = [e.get("matcher") for e in data["hooks"]["PreToolUse"]]
    assert matchers, "PreToolUse 훅이 없어요"
    # match-all 이어야 `Glob`·`TodoWrite`·`Task`·`mcp__*` 에 훅이 뜬다
    assert all(m in (None, "", "*", ".*") for m in matchers), matchers


@pytest.mark.parametrize("path", NOT_SECRET)
def test_공개키와_known_hosts_는_비밀이_아니다(ctx, path):
    """막으면 git 원격을 못 쓴다. 비밀이 아닌 건 비밀이라고 하지 않는다."""
    found = actions(one(ctx, "Read", {"file_path": os.path.expanduser(path)}))
    assert found == ["readOutside"], found  # 승인 대상이긴 하지만 비밀은 아니다


def test_SECRET_FILES_가_홈_자격_증명을_덮는다():
    """목록이 코드에 있고, 정책으로는 더할 수만 있다."""
    from app import paths

    for path in CREDENTIALS:
        target = paths.real(path)
        assert paths.match_abs_globs(target, D.SECRET_FILES), path


def test_정책으로_비밀_목록을_줄일_수_없다(ctx, project_root):
    """`secretFilesExtra` 는 **더하는** 칸이다."""
    ctx.policy.data["paths"]["secretFilesExtra"] = []
    assert actions(one(ctx, "Read", {"file_path": os.path.expanduser("~/.ssh/id_rsa")})) == [
        "secret"
    ]


# --- 학습 샌드박스: AI 가 쓴 코드 ------------------------------------------------


def test_홈을_통째로_가린다(project_root):
    from app.runner import sandbox as SB

    argv = SB.command(["/bin/true"], project_root=project_root, bwrap="/usr/bin/bwrap")
    hidden = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    assert os.path.realpath(os.path.expanduser("~")) in hidden


def test_홈을_가린_뒤_필요한_것만_다시_연다(project_root):
    from app.runner import sandbox as SB

    argv = SB.command(["/bin/true"], project_root=project_root, bwrap="/usr/bin/bwrap")
    home = os.path.realpath(os.path.expanduser("~"))
    hide_at = argv.index(home)
    # 프로젝트 쓰기 바인드가 가림 **뒤**에 와야 뚫린다
    assert argv.index(project_root) > hide_at
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert binds == [project_root]


def test_conda_를_읽기로_다시_연다(project_root):
    """`conda run -n <환경>` 이 돌아야 한다. 홈을 가리면 conda 도 사라진다."""
    from app.runner import sandbox as SB

    roots = SB.conda_roots()
    if not roots:
        pytest.skip("이 머신에 conda 가 없어요")
    argv = SB.command(["/bin/true"], project_root=project_root, bwrap="/usr/bin/bwrap")
    ro = [argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"]
    for root in roots:
        assert root in ro, root
    home = os.path.realpath(os.path.expanduser("~"))
    for root in roots:
        if root.startswith(home + os.sep):
            assert argv.index(root) > argv.index(home)  # 가림 뒤에 와야 한다


def test_다른_사용자_홈도_가린다(project_root, monkeypatch):
    from app.runner import sandbox as SB

    assert "/home" in str(SB.home_dirs()) or SB.home_dirs()
    # /home 아래를 훑어 내 홈이 아닌 것을 넣는다
    home = os.path.realpath(os.path.expanduser("~"))
    for item in SB.home_dirs():
        assert item == home or item.startswith("/home/")


def test_작업_폴더를_가리라고_하면_거부한다(project_root):
    from app.runner import sandbox as SB

    with pytest.raises(SB.SandboxError):
        SB.command(["/bin/true"], project_root=project_root, hide=[project_root], bwrap="/usr/bin/bwrap")
