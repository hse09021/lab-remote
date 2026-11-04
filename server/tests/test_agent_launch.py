"""`claude -p` 인자 조립 — **보안 경계**다.

②가 ①의 경계를 약하게 만들 수 있는 자리는 여기뿐이다. `--bare` 한 줄이면
훅이 통째로 사라진다. 그래서 금지 플래그를 코드로 막고 여기서 고정한다.
"""

import json
import os

import pytest

from app import registry
from app.agent import launch as L
from app.agent import session as S


@pytest.fixture()
def run(project, project_root):
    registry.register(project_root, "hook-sandbox")
    return L.AgentRun(
        project="hook-sandbox",
        root=project_root,
        prompt="루프 1회차를 설계해 주세요",
        session_id=S.new_id(),
    )


# --- 금지 플래그 ----------------------------------------------------------------


@pytest.mark.parametrize("flag", sorted(L.FORBIDDEN_FLAGS))
def test_훅을_끄는_플래그는_거부한다(run, flag):
    run.extra_flags = [flag]
    with pytest.raises(L.LaunchRefused) as err:
        L.build_argv(run)
    assert "훅" in str(err.value)


def test_등호로_붙여_써도_잡는다(run):
    """`--setting-sources=project` 로 user 설정을 빼면 훅 등록이 사라진다."""
    run.extra_flags = ["--setting-sources=project"]
    with pytest.raises(L.LaunchRefused):
        L.build_argv(run)


def test_금지_플래그가_중간에_섞여도_잡는다(run):
    run.extra_flags = ["--verbose", "--bare", "--debug"]
    with pytest.raises(L.LaunchRefused):
        L.build_argv(run)


@pytest.mark.parametrize("mode", sorted(L.FORBIDDEN_MODES))
def test_승인_경로가_사라지는_모드는_거부한다(run, mode):
    run.permission_mode = mode
    with pytest.raises(L.LaunchRefused) as err:
        L.build_argv(run)
    assert "승인 경로가 사라져요" in str(err.value)


def test_모르는_모드도_거부한다(run):
    run.permission_mode = "아무거나"
    with pytest.raises(L.LaunchRefused):
        L.build_argv(run)


@pytest.mark.parametrize("mode", sorted(L.ALLOWED_MODES))
def test_쓸_수_있는_모드(run, mode):
    run.permission_mode = mode
    assert mode in L.build_argv(run)


def test_수동제어_프리셋에_헤드리스는_거부한다(run):
    """전부 승인 대기로 떨어져서 루프가 한 발짝도 못 나간다."""
    with pytest.raises(L.LaunchRefused) as err:
        L.check_mode("default", preset="manual", headless=True)
    assert "한 발짝도 못 나가요" in str(err.value)


def test_수동제어라도_대화형은_괜찮다(run):
    assert L.check_mode("default", preset="manual", headless=False) == "default"


# --- 인자 조립 ------------------------------------------------------------------


def test_인자_모양(run):
    argv = L.build_argv(run)
    assert argv[:2] == ["claude", "-p"]
    assert argv[-1] == run.prompt
    assert "--session-id" in argv and run.session_id in argv
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert "--output-format" in argv and "json" in argv


def _flag_set(argv, flag):
    """쉼표로 묶어 한 번에 넘긴다 (help: "Comma or space-separated")."""
    out = set()
    for i, x in enumerate(argv):
        if x == flag and i + 1 < len(argv):
            out |= {n for n in argv[i + 1].split(",") if n}
    return out


def _disallowed(argv):
    return _flag_set(argv, "--disallowedTools")


def _tools(argv):
    return _flag_set(argv, "--tools")


def test_서브에이전트_도구_이름이_Agent_다(run):
    """🔑 전에는 `Task` 였고 **그건 아무것도 끄지 않았다.**

    2.1.318 의 서브에이전트 도구 이름은 `Agent` 다 — 세션에 도구 목록을
    물어봐서 확인했다. `Task` 는 존재하지 않는 이름이라
    `--disallowedTools Task` 가 무효였고 서브에이전트가 계속 열려 있었다.
    """
    assert "Agent" in L.DISALLOWED_TOOLS
    assert "Task" not in L.DISALLOWED_TOOLS, "없는 도구를 끄는 척하면 안 돼요"
    assert "Agent" in _disallowed(L.build_argv(run))


def test_바깥으로_내보내는_도구를_끈다(run):
    """`Artifact` 는 claude.ai 로 올린다 — 훅의 파일 게이트와 샌드박스의
    네트워크 허용 목록을 **둘 다** 지나간다."""
    got = _disallowed(L.build_argv(run))
    for tool in ("Artifact", "ArtifactComments", "ArtifactData", "SendFeedback",
                 "PushNotification", "DesignSync"):
        assert tool in got, tool


def test_나중에_실행되는_도구를_끈다(run):
    """`at`·`crontab` 을 denyCommands 로 막은 것과 같은 이유다."""
    got = _disallowed(L.build_argv(run))
    for tool in ("CronCreate", "CronDelete", "CronList", "RemoteTrigger",
                 "ScheduleWakeup", "Monitor"):
        assert tool in got, tool


def test_판정할_수_있는_도구는_남겨_둔다(run):
    """훅이 판정하는 것은 끄지 않는다 — 끄면 일을 못 한다."""
    got = _disallowed(L.build_argv(run))
    for tool in ("Bash", "Read", "Write", "Edit", "NotebookEdit",
                 "WebFetch", "WebSearch", "ToolSearch", "Skill"):
        assert tool not in got, tool


def test_헤드리스_전용_플래그(run):
    argv = L.build_argv(run)
    assert argv[argv.index("--permission-prompts") + 1] == "none"


def test_도구_허용_목록이_붙는다(run):
    """🔑 `--tools` 는 **능력 자체를 제한**한다 (실측: 이 목록만 세션에 보인다).

    끄는 목록만으로는 새 판에서 늘어난 도구가 조용히 빠져나간다 — 헤드리스는
    훅이 막지만 **대화형은 `defer` 라 사람이 승인창에서 허용할 수 있다.**
    """
    got = _tools(L.build_argv(run))
    assert got == set(L.ALLOWED_TOOLS)
    assert "Bash" in got and "Read" in got and "ToolSearch" in got
    # 끄는 목록과 겹치지 않는다
    assert not (got & set(L.DISALLOWED_TOOLS))


def test_allowedTools_는_여전히_금지다():
    """`--allowedTools` 는 **자동 승인** 목록이다 — 게이트를 열어 버린다.
    능력을 제한하는 것은 `--tools` 다. 혼동하면 안 된다."""
    assert "--allowedTools" in L.FORBIDDEN_FLAGS
    # 우리가 직접 넣는 둘은 넘겨받지 않는다
    assert "--tools" in L.FORBIDDEN_FLAGS
    assert "--disallowedTools" in L.FORBIDDEN_FLAGS
    with pytest.raises(L.LaunchRefused):
        L.check_flags(["--tools", "Bash,Agent"])
    with pytest.raises(L.LaunchRefused):
        L.check_flags(["--allowedTools", "Bash"])


def test_자동_업데이트를_끈다(run):
    """2.1.317 → 2.1.318 이 저절로 바뀌면서 도구 이름이 달라졌다.

    번들의 판정 코드: `DISABLE_UPDATES` → `DISABLE_AUTOUPDATER` → 설정.
    이 설치는 native 라 설정은 무시될 수 있어서 환경 변수여야 한다.
    """
    env = L.build_env(run, base={"HOME": "/h", "PATH": "/b"})
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["DISABLE_UPDATES"] == "1"
    # 넘겨받은 값이 이기지 못한다
    env = L.build_env(run, base={"HOME": "/h", "DISABLE_AUTOUPDATER": "0"})
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_대화형도_같은_도구_경계를_쓴다(run):
    """`labremote claude` 가 있는 이유가 "같은 경계로 열기" 다."""
    run.headless = False
    run.interactive = True
    argv = L.build_argv(run)
    assert _disallowed(argv) == set(L.DISALLOWED_TOOLS)
    assert _tools(argv) == set(L.ALLOWED_TOOLS)
    # 헤드리스 전용은 안 붙는다
    assert "--permission-prompts" not in argv
    assert "--output-format" not in argv


def test_재개는_resume_로(run):
    run.resume = True
    argv = L.build_argv(run)
    assert argv[argv.index("--resume") + 1] == run.session_id
    assert "--session-id" not in argv


def test_fork_session_은_안_쓴다(run):
    """세션 ID 가 바뀌면 재시도 상한 추적이 끊긴다."""
    run.resume = True
    assert "--fork-session" not in L.build_argv(run)


def test_모델을_지정하지_않는다(run):
    """기본값을 쓰고 **쓰인 모델을 기록**한다 (결정 2번)."""
    assert "--model" not in L.build_argv(run)


def test_세션_ID_가_없으면_거부한다(run):
    run.session_id = ""
    with pytest.raises(L.LaunchRefused) as err:
        L.build_argv(run)
    assert "세션 ID" in str(err.value)


# --- 환경 -----------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(L.ENV_STRIP))
def test_API_키를_지운다(run, name):
    """키가 섞이면 구독이 아니라 **종량제 과금**이다. 어떤 경우에도 안 된다."""
    env = L.build_env(run, base={name: "sk-새면안되는값", "HOME": "/home/x", "PATH": "/usr/bin"})
    assert name not in env


def test_헤드리스_표식을_넣는다(run):
    """훅이 "헤드리스" 를 아는 유일한 길이다. stdin 으로는 구분할 수 없다."""
    assert L.build_env(run, base={})[L.HEADLESS_ENV] == "1"


def test_대화형에는_표식을_안_넣는다(run):
    run.headless = False
    assert L.HEADLESS_ENV not in L.build_env(run, base={})


def test_우리_폴더_위치를_물려주지_않는다(run):
    env = L.build_env(run, base={"LAB_DATA_DIR": "/비밀", "HOME": "/home/x"})
    assert not [k for k in env if k.startswith("LAB_") and k != L.HEADLESS_ENV]


# --- 작업 디렉터리 ---------------------------------------------------------------


def test_등록된_프로젝트에서만_띄운다(run, tmp_path):
    """래퍼가 cwd 로만 판정한다. 그 밖에서 띄우면 훅이 아예 안 뜬다."""
    outside = tmp_path / "남의폴더"
    outside.mkdir()
    run.root = str(outside)
    with pytest.raises(L.LaunchRefused) as err:
        L.check_cwd(run)
    assert "권한 훅이 뜨지 않아요" in str(err.value)


def test_없는_폴더는_거부한다(run):
    run.root = "/없는경로/프로젝트"
    with pytest.raises(L.LaunchRefused):
        L.check_cwd(run)


def test_plan_은_설정_파일을_직접_쓴다(run, monkeypatch):
    """`--settings` 파일은 **매 실행 전에 코드에서 다시 쓴다.**

    디스크에 있는 걸 믿지 않는다 — 오래된 설정이나 손댄 설정으로 뜨는 길을
    막는다. 그래서 `plan()` 뒤에는 샌드박스가 **켜져 있는 것이 정상**이다.
    """
    from app import policy

    path = policy.launch_settings_path()
    assert not os.path.exists(path)
    got = L.plan(run, base_env={})
    assert got["settings"] == path
    assert got["sandbox"]["ok"] is True
    assert got["sandbox"]["source"] == "launch"


def test_plan_은_설정을_못_쓰면_거부한다(run, monkeypatch):
    """fail-closed. 울타리를 못 세웠으면 헤드리스로 띄우지 않는다."""
    from app import policy

    monkeypatch.setattr(
        L, "render_settings", lambda root, project="": policy.launch_settings_path()
    )
    with pytest.raises(L.LaunchRefused) as err:
        L.plan(run, base_env={})
    assert "샌드박스" in str(err.value)


def test_대화형은_샌드박스가_꺼져_있어도_띄운다(run, monkeypatch):
    """사람이 보고 있다. 막으면 개발이 안 된다."""
    from app import policy

    monkeypatch.setattr(
        L, "render_settings", lambda root, project="": policy.launch_settings_path()
    )
    run.headless = False
    assert L.plan(run, base_env={})["sandbox"]["ok"] is False


def test_plan_은_전부_통과해야_나온다(run, sandboxed):
    got = L.plan(run, base_env={"HOME": "/home/x", "PATH": "/usr/bin"})
    assert got["sandbox"]["ok"] is True
    assert got["cwd"] == os.path.realpath(run.root)
    assert got["sessionId"] == run.session_id
    assert got["env"][L.HEADLESS_ENV] == "1"
    assert "--bare" not in got["argv"]


def test_plan_은_수동제어_헤드리스를_거부한다(run):
    with pytest.raises(L.LaunchRefused):
        L.plan(run, preset="manual")


# --- 세션 ID ---------------------------------------------------------------------


def test_세션_ID_는_uuid4(run):
    got = S.new_id()
    assert S.is_valid(got)
    assert S.new_id() != got


@pytest.mark.parametrize("bad", ["", None, "그냥문자열", "1234", "abc-def"])
def test_이상한_세션_ID_는_거부한다(bad):
    assert S.is_valid(bad) is False


def test_대소문자만_다르면_같은_세션(run):
    got = S.new_id()
    assert S.same(got, got.upper()) is True
    assert S.same(got, S.new_id()) is False


# --- 🔑 경계 플래그 셋 (M6) ---------------------------------------------------
#
# 프로젝트 `.claude/settings.json` 은 AI 가 쓴 코드가 고칠 수 있다(M4). 실측에서
# 거기 심은 훅이 샌드박스 **밖에서 사용자 권한으로** 돌았고, `sandbox.enabled:false`
# 한 줄로 샌드박스가 꺼져 AI 코드가 `server/data/runstate/` 에 실제로 썼다.
# 그래서 그 파일을 **아예 안 읽는다.** 이 절이 그걸 고정한다.


def _argv(run):
    from app import policy

    run.settings_path = policy.launch_settings_path()
    return L.build_argv(run)


def test_argv_에_경계_플래그_셋이_항상_있다(run):
    from app import policy

    argv = _argv(run)
    assert "--setting-sources" in argv
    assert argv[argv.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--settings") + 1] == policy.launch_settings_path()


def test_대화형_argv_도_같은_경계를_쓴다(run):
    """`labremote claude` 로 여는 세션도 프로젝트 설정을 안 읽어야 한다."""
    run.interactive = True
    argv = _argv(run)
    assert "--setting-sources" in argv and "--strict-mcp-config" in argv
    # 헤드리스 전용은 빠진다
    assert "-p" not in argv
    assert "--permission-prompts" not in argv
    assert "--output-format" not in argv
    assert run.prompt not in argv


def test_settings_는_server_data_아래만_받는다(run, tmp_path):
    """AI 가 프로젝트 안에 만든 설정 파일을 넘기는 길을 막는다."""
    fake = tmp_path / "projects" / "hook-sandbox" / "evil-settings.json"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("{}", encoding="utf-8")
    with pytest.raises(L.LaunchRefused):
        L.check_settings_file(str(fake))
    with pytest.raises(L.LaunchRefused):
        L.check_flags(["--settings", str(fake)])
    with pytest.raises(L.LaunchRefused):
        L.check_flags([f"--settings={fake}"])


def test_setting_sources_는_user_가_빠지면_거부한다():
    """`user` 가 빠지면 훅 등록을 안 읽는다 — 잠금이 전부 사라진다."""
    for bad in ("project", "project,local", "local"):
        with pytest.raises(L.LaunchRefused) as err:
            L.check_setting_sources(bad)
        assert "user" in str(err.value)
    for bad in ("", "managed", "user,nope"):
        with pytest.raises(L.LaunchRefused):
            L.check_setting_sources(bad)
    # user 가 있으면 통과한다 — 우리가 써야 하는 값이다
    assert L.check_setting_sources("user") == "user"
    assert L.check_setting_sources("user,project") == "user,project"


def test_setting_sources_는_금지_플래그가_아니다():
    """전에는 이름만 보고 전부 거부했다. 우리가 써야 하므로 값만 본다."""
    assert "--setting-sources" not in L.FORBIDDEN_FLAGS
    L.check_flags(["--setting-sources", "user"])
    L.check_flags(["--setting-sources=user,project"])


def test_경계를_넓히는_플래그들을_거부한다():
    for flag in (
        "--mcp-config", "--add-dir", "--tools", "--allowedTools",
        "--plugin-dir", "--agents", "--system-prompt", "--append-system-prompt",
        "--bare", "--safe-mode", "--restricted", "--dangerously-skip-permissions",
    ):
        with pytest.raises(L.LaunchRefused), pytest.MonkeyPatch.context():
            L.check_flags([flag, "x"])


def test_allowWrite_에_넓은_곳이_있으면_샌드박스가_거부된다(project_root, tmp_path):
    """`~/projects` 를 열면 다른 실험 프로젝트까지 쓰기 가능해진다."""
    from app import policy, registry

    for bad in (registry.projects_root(), registry.data_dir(), os.path.expanduser("~")):
        policy.render_launch_settings(project_root, cache_dir=bad, conda_roots=[])
        state = policy.sandbox_state(project_root)
        assert state["ok"] is False, bad
        assert any("너무 넓어요" in r for r in state["reasons"]), (bad, state)


def test_allowWrite_에_server_data_가_없다(project_root, tmp_path):
    """훅은 샌드박스 **밖**에서 돈다(M1) — 열어 줄 이유가 없고, 열면 AI 가
    `runstate` 를 고쳐 stop·prev 잠금을 풀 수 있다."""
    from app import policy, registry

    cache = str(tmp_path / "lab-cache")
    policy.render_launch_settings(project_root, cache_dir=cache, conda_roots=[])
    state = policy.sandbox_state(project_root)
    assert state["ok"] is True, state["reasons"]
    assert state["allowWrite"] == [os.path.realpath(cache)]
    for name in ("runstate", "grants", "policies", "status", "requests", "pending"):
        assert not any(name in item for item in state["allowWrite"]), name
    # 프로젝트 루트도 적지 않는다 — 어차피 열려 있다(M4)
    assert os.path.realpath(project_root) not in state["allowWrite"]


def test_코드는_사용자_설정에_샌드박스를_쓰지_않는다(project_root, tmp_path, monkeypatch):
    """규칙 0 — 전에 `hooks install` 이 거기에 써서 이 PC 의 모든 세션이 갇혔다."""
    from app import policy
    from app.hooks import install

    user = tmp_path / "claude" / "settings.json"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(user))
    install.install(mode="enforce")
    data = json.loads(user.read_text(encoding="utf-8"))
    assert "sandbox" not in data, data
    assert "hooks" in data
    # 대신 런처 설정 파일이 생긴다
    assert os.path.exists(policy.launch_settings_path())


def test_런처_설정에는_훅을_넣지_않는다(project_root):
    """양쪽에 두면 훅이 **두 번** 돈다 (실측 M6f)."""
    from app import policy

    data = policy.launch_settings(project_root, cache_dir="", conda_roots=[])
    assert "hooks" not in data
    assert data["sandbox"]["enabled"] is True
    assert data["permissions"]["blockWritesOutsideWorkingDirectories"] is True
