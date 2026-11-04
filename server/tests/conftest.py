"""공통 픽스처.

`server/data/` 를 건드리지 않도록 `LAB_DATA_DIR` 과 `LAB_PROJECTS_DIR` 를
테스트마다 임시 폴더로 돌린다. 생성기가 붙는 8단계에서 여기에
`project` 픽스처(실제로 프로젝트를 만드는)가 추가된다.
"""

import os
import pathlib

import pytest

#: 저장소 루트. web/ 의 mock JSON 을 대조하는 데 쓴다.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """정책·레지스트리·실행 상태를 임시 폴더로."""
    data = tmp_path / "data"
    projects = tmp_path / "projects"
    data.mkdir()
    projects.mkdir()
    monkeypatch.setenv("LAB_DATA_DIR", str(data))
    monkeypatch.setenv("LAB_PROJECTS_DIR", str(projects))
    return data


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """`~/.config/labremote` 를 건드리지 않게. 웹훅 주소·허가 서명 키가 거기 있다."""
    folder = tmp_path / "config"
    folder.mkdir()
    monkeypatch.setenv("LAB_CONFIG_DIR", str(folder))
    return folder


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """공용 캐시 폴더를 임시 폴더로.

    실행기는 띄울 때 캐시 폴더를 **만든다.** 격리하지 않으면 시험이 진짜
    `~/lab-cache` 를 만들어 둔다.
    """
    folder = tmp_path / "lab-cache"
    monkeypatch.setenv("LAB_CACHE_DIR", str(folder))
    return folder


@pytest.fixture(autouse=True)
def pinned_claude_version(isolated_data, monkeypatch):
    """Claude Code 판을 고정하고 **기록해 둔다.**

    `guards.check_loop` 이 "마지막으로 도구 목록을 실측한 판" 과 지금 판을
    대조해서 다르면 루프를 멈춘다(2.1.317 → 2.1.318 에서 서브에이전트 도구
    이름이 바뀌어 방어에 틈이 생겼다). 시험에서는 그 둘을 같게 둔다 —
    판이 바뀐 경우는 전용 시험이 따로 본다.

    `claude --version` 을 실제로 돌리지 않는다 (느리고, 없을 수도 있다).
    """
    from app.agent import version as version_mod

    monkeypatch.setattr(version_mod, "current", lambda binary="claude": "9.9.9-시험")
    version_mod.record("9.9.9-시험", tools=None, note="시험 픽스처")
    return "9.9.9-시험"


@pytest.fixture()
def conn(isolated_data):
    """이행까지 끝난 `lab.db` 연결. 테스트마다 빈 DB 다."""
    from app import db

    with db.open_db() as connection:
        yield connection


@pytest.fixture()
def grant_key(isolated_config):
    """허가 서명 키를 만들어 둔다. 없으면 모든 허가가 무효다."""
    from app import config

    return config.ensure_grant_key()


@pytest.fixture()
def project_root(tmp_path):
    """등록은 안 된 빈 프로젝트 폴더."""
    root = tmp_path / "projects" / "hook-sandbox"
    for sub in ("docs", "specifications", "logs", "experiments/EXP-007", "src"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return os.path.realpath(str(root))


@pytest.fixture()
def project(project_root):
    """등록까지 끝난 프로젝트. 훅 판정 테스트의 기본 픽스처."""
    from app import policy, registry

    for sub in ("docs", "specifications", "logs", "state", "templates", "src"):
        os.makedirs(os.path.join(project_root, sub), exist_ok=True)
    registry.register(project_root, "hook-sandbox")
    return policy.ensure("hook-sandbox", project_root)


@pytest.fixture()
def sandboxed(project, project_root, tmp_path, monkeypatch):
    """Claude Bash 샌드박스가 켜진 프로젝트. 코드 실행(`pytest`)이 열리는 조건.

    샌드박스는 **런처가 넘기는 설정 파일**에 있다
    (`<LAB_DATA_DIR>/agent/headless-settings.json`). `LAB_DATA_DIR` 은
    `isolated_data` 가 임시 폴더로 돌려 놨다.

    **진짜 `~/.claude/settings.json` 을 건드리지 않는다** — 코드가 그 파일에
    `sandbox` 를 쓰지 않게 바뀌었지만(T2), 훅 등록 경로를 쓰는 시험이 섞여도
    안전하게 `LAB_CLAUDE_SETTINGS` 를 임시 파일로 돌려 둔다.
    """
    from app import policy

    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(path))
    policy.render_launch_settings(project_root, cache_dir="", conda_roots=[])
    return project_root


@pytest.fixture()
def ctx(project, project_root):
    """수동제어 · 실험이 안 도는 상태."""
    from app import runstate
    from app.hooks.classify import Ctx

    return Ctx(
        root=project_root,
        cwd=project_root,
        name="hook-sandbox",
        policy=project,
        run=runstate.RunState(),
        event={},
    )


@pytest.fixture()
def hook_event():
    """실측 모양 그대로의 PreToolUse 이벤트를 만든다."""

    def make(tool, tool_input, *, cwd=None, **extra):
        event = {
            "session_id": "sess-테스트",
            "cwd": cwd or "",
            "prompt_id": "prompt-테스트",
            "permission_mode": "default",
            "effort": {"level": "medium"},
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "tool_use_id": "toolu_테스트",
        }
        event.update(extra)
        return event

    return make


FIXTURE_EVENTS = pathlib.Path(__file__).resolve().parent / "fixtures" / "hook_events"


@pytest.fixture()
def real_event():
    """실측 덤프를 이름 조각으로 찾아 돌려준다."""
    import json

    def find(fragment):
        for path in sorted(FIXTURE_EVENTS.glob("*.json")):
            if fragment in path.name:
                return json.loads(path.read_text(encoding="utf-8"))
        raise AssertionError(f"픽스처가 없어요: {fragment}")

    return find
