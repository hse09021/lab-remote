"""`claude -p` 인자 조립 — **보안 경계**다.

②가 ①의 경계를 약하게 만들 수 있는 자리는 여기뿐이다. `--bare` 한 줄이면
훅이 통째로 사라진다. 그래서 금지 플래그를 코드로 막고 여기서 고정한다.
"""

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


def test_헤드리스는_서브에이전트를_끈다(run):
    """①에서 가장 성가셨던 게 서브에이전트 대기 건이었다."""
    argv = L.build_argv(run)
    assert argv[argv.index("--disallowedTools") + 1] == "Task"
    assert argv[argv.index("--permission-prompts") + 1] == "none"


def test_대화형은_그_둘을_안_붙인다(run):
    run.headless = False
    argv = L.build_argv(run)
    assert "--disallowedTools" not in argv
    assert "--permission-prompts" not in argv


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


def test_plan_은_샌드박스가_꺼져_있으면_거부한다(run):
    """AI 가 쓴 테스트 코드를 가두는 유일한 수단이다. 꺼져 있으면 안 띄운다."""
    with pytest.raises(L.LaunchRefused) as err:
        L.plan(run, base_env={})
    assert "샌드박스가 켜져 있지 않아요" in str(err.value)


def test_대화형은_샌드박스가_꺼져_있어도_띄운다(run):
    """사람이 보고 있다. 막으면 개발이 안 된다."""
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
