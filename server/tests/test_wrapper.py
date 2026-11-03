"""셸 래퍼 시험.

래퍼의 일은 하나다 — "실험 프로젝트 폴더 밖이면 파이썬을 아예 띄우지 않기".
이게 깨지면 ① lab-remote 저장소에서 개발용 Claude Code 가 막히거나
② 반대로 실험 프로젝트에서 잠금이 조용히 꺼진다.
"""

import json
import os
import subprocess

import pytest

from app import paths
from app.hooks import install

FAKE_PY = "/nonexistent/절대/없는/python"


def run(wrapper, env=None, cwd=None, module="app.hooks.pretooluse", stdin=""):
    base = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    base.update(env or {})
    return subprocess.run(
        ["/bin/sh", wrapper, module],
        input=stdin,
        capture_output=True,
        text=True,
        env=base,
        cwd=cwd,
    )


@pytest.fixture()
def roots(tmp_path):
    r = tmp_path / "projects"
    (r / "hook-sandbox" / "experiments" / "EXP-007").mkdir(parents=True, exist_ok=True)
    return paths.real(str(r))


@pytest.fixture()
def wrapper(roots):
    """진짜 파이썬을 가리키는 래퍼."""
    return install.render_wrapper(roots=roots)


@pytest.fixture()
def broken_wrapper(roots):
    """인터프리터가 사라진 상황을 흉내 낸 래퍼."""
    return install.render_wrapper(python=FAKE_PY, roots=roots)


# --- 밖이면 건너뛴다 --------------------------------------------------------


def test_프로젝트_밖이면_조용히_통과(wrapper, tmp_path):
    outside = tmp_path / "lab-remote"
    outside.mkdir()
    r = run(wrapper, env={"CLAUDE_PROJECT_DIR": str(outside)})
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


def test_인터프리터가_없어도_프로젝트_밖_작업은_안_막힌다(broken_wrapper, tmp_path):
    """labremote 환경이 깨져도 lab-remote 저장소에서의 개발은 평소대로."""
    outside = tmp_path / "lab-remote"
    outside.mkdir()
    r = run(broken_wrapper, env={"CLAUDE_PROJECT_DIR": str(outside)})
    assert r.returncode == 0
    assert r.stdout == ""


def test_형제_접두사_폴더는_밖(wrapper, tmp_path):
    sibling = tmp_path / "projects-old"
    sibling.mkdir()
    r = run(wrapper, env={"CLAUDE_PROJECT_DIR": str(sibling)})
    assert r.returncode == 0 and r.stdout == ""


# --- 안쪽 판정 --------------------------------------------------------------


def test_안쪽이면_파이썬까지_간다(wrapper, roots):
    """등록된 프로젝트가 아직 없으니 파이썬이 떠서 빈 판정을 내면 된다.
    여기서는 '래퍼가 건너뛰지 않았다' 만 본다 — debug 모듈로 확인."""
    inside = os.path.join(roots, "hook-sandbox")
    r = run(
        wrapper,
        env={"CLAUDE_PROJECT_DIR": inside, "LAB_DATA_DIR": os.environ["LAB_DATA_DIR"]},
        module="app.hooks.debug",
        stdin=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write"}),
    )
    assert r.returncode == 0, r.stderr
    dumps = os.listdir(os.path.join(os.environ["LAB_DATA_DIR"], "hook_dumps"))
    assert len(dumps) == 1  # 파이썬이 실제로 돌았다


def test_환경_변수_없이도_cwd_로_안쪽_판정(wrapper, roots):
    """CLAUDE_PROJECT_DIR 이 없는 환경에서도 잠금이 꺼지면 안 된다."""
    inside = os.path.join(roots, "hook-sandbox")
    r = run(
        wrapper,
        env={"LAB_DATA_DIR": os.environ["LAB_DATA_DIR"]},  # CLAUDE_PROJECT_DIR 없음
        cwd=inside,
        module="app.hooks.debug",
        stdin="{}",
    )
    assert r.returncode == 0, r.stderr
    assert os.listdir(os.path.join(os.environ["LAB_DATA_DIR"], "hook_dumps"))


def test_런타임_LAB_PROJECTS_DIR_로는_못_바꾼다(wrapper, roots, tmp_path):
    """루트는 설치할 때 박힌다. 환경 변수를 바꿔도 판정이 흔들리면 안 된다."""
    elsewhere = tmp_path / "다른곳" / "proj"
    elsewhere.mkdir(parents=True)
    # 밖을 안쪽으로 만들려는 시도 -> 여전히 밖
    r = run(
        wrapper,
        env={"CLAUDE_PROJECT_DIR": str(elsewhere), "LAB_PROJECTS_DIR": str(tmp_path / "다른곳")},
    )
    assert r.returncode == 0 and r.stdout == ""

    # 안쪽을 밖으로 만들려는 시도 -> 여전히 안쪽
    inside = os.path.join(roots, "hook-sandbox")
    r = run(
        broken := install.render_wrapper(python=FAKE_PY, roots=roots),
        env={"CLAUDE_PROJECT_DIR": inside, "LAB_PROJECTS_DIR": "/tmp/아무데나"},
    )
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert broken


def test_심볼릭_링크로_들어와도_안쪽(wrapper, roots, tmp_path):
    """pwd -P 로 실제 경로를 본다."""
    link = tmp_path / "바로가기"
    os.symlink(os.path.join(roots, "hook-sandbox"), str(link))
    r = run(
        wrapper,
        env={"CLAUDE_PROJECT_DIR": str(link), "LAB_DATA_DIR": os.environ["LAB_DATA_DIR"]},
        module="app.hooks.debug",
        stdin="{}",
    )
    assert r.returncode == 0, r.stderr
    assert os.listdir(os.path.join(os.environ["LAB_DATA_DIR"], "hook_dumps"))


def test_루트가_심볼릭_링크여도_안쪽(tmp_path):
    """~/projects 자체가 링크인 경우. 설치할 때 해소하므로 양쪽이 맞아야 한다."""
    # autouse 픽스처가 tmp_path/projects 를 이미 만들어 두므로 다른 이름을 쓴다.
    real_roots = tmp_path / "실제" / "연구"
    (real_roots / "hook-sandbox").mkdir(parents=True)
    link_roots = tmp_path / "연구링크"
    os.symlink(str(real_roots), str(link_roots))

    wrapper = install.render_wrapper(python=FAKE_PY, roots=str(link_roots))
    r = run(wrapper, env={"CLAUDE_PROJECT_DIR": str(link_roots / "hook-sandbox")})
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- 안쪽인데 인터프리터가 없을 때 -------------------------------------------


def test_안쪽에서_인터프리터가_없으면_deny(broken_wrapper, roots):
    inside = os.path.join(roots, "hook-sandbox")
    r = run(broken_wrapper, env={"CLAUDE_PROJECT_DIR": inside})
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "어요" in out["permissionDecisionReason"]


def test_PreToolUse_가_아니면_deny_를_안_찍는다(broken_wrapper, roots):
    """기록용 훅(Stop·SessionEnd)은 판정을 내지 않는다."""
    inside = os.path.join(roots, "hook-sandbox")
    r = run(broken_wrapper, env={"CLAUDE_PROJECT_DIR": inside}, module="app.hooks.stop")
    assert r.returncode == 0 and r.stdout == ""


# --- 래퍼 자체 --------------------------------------------------------------


def test_래퍼는_실행_권한이_있다(wrapper):
    assert os.access(wrapper, os.X_OK)


def test_래퍼에_자리표시가_안_남는다(wrapper):
    body = open(wrapper, encoding="utf-8").read()
    for token in ("__PY__", "__SERVER_DIR__", "__ROOTS__"):
        assert token not in body


def test_래퍼는_PATH_없이도_돈다(wrapper, roots, tmp_path):
    outside = tmp_path / "lab-remote"
    outside.mkdir()
    r = run(wrapper, env={"CLAUDE_PROJECT_DIR": str(outside), "PATH": ""})
    assert r.returncode == 0 and r.stdout == ""


def test_한계_안내에_프로젝트_안에서_켜기가_들어_있다():
    joined = " ".join(install.limitations())
    assert "항상 이 프로젝트 폴더 안에서" in joined or "항상" in joined
    assert install.SHELL_LIMITATION_NOTE in joined
