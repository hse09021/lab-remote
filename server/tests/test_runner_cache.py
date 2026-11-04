"""공용 캐시 폴더.

샌드박스는 프로젝트 하나만 쓸 수 있게 두는데, 진짜 학습은 프로젝트 밖에
쓰려 든다 — HuggingFace·torch hub·pip·W&B 캐시, 그리고 임시 파일.

특히 `/tmp` 는 샌드박스 안에서 **tmpfs = 메모리**다. 큰 임시 파일이면
메모리가 터진다. 그래서 `TMPDIR` 을 캐시 폴더 아래 진짜 디스크로 돌린다.

**값은 실행기가 정한다.** `run.json` 으로는 못 바꾼다.
"""

import json
import os
import shutil

import pytest

from app.runner import cache as C
from app.runner import process as P
from app.runner import sandbox as SB
from tests.test_runner_spec import load, write_config

FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_train.py")
STATE = SB.available()
needs_bwrap = pytest.mark.skipif(not STATE["ok"], reason=f"bwrap 을 쓸 수 없어요: {STATE['reason']}")


@pytest.fixture()
def ready(project, project_root):
    os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
    shutil.copy(FAKE, os.path.join(project_root, "src", "train.py"))
    write_config(project_root, entrypoints=["src/train.py"])
    os.makedirs(os.path.join(project_root, "experiments", "EXP-001"), exist_ok=True)
    return project_root


@pytest.fixture()
def cache(isolated_cache):
    """conftest 의 autouse 격리와 같은 폴더."""
    return isolated_cache


def spec_for(root, *args):
    got = load(root, {"entrypoint": "src/train.py", "args": ["--epochs", "1", *args]})
    got.conda_env = ""
    got.args = [*got.args, "--out", got.exp_dir]
    return got


# --- 어디를 쓰나 ---------------------------------------------------------------


def test_기본은_홈_아래_lab_cache(isolated_data, monkeypatch):
    monkeypatch.delenv("LAB_CACHE_DIR", raising=False)
    assert C.cache_dir() == os.path.realpath(os.path.expanduser("~/lab-cache"))


def test_정책으로_바꿀_수_있다(project, tmp_path, monkeypatch):
    monkeypatch.delenv("LAB_CACHE_DIR", raising=False)
    project.data["paths"]["cacheDir"] = str(tmp_path / "다른캐시")
    assert C.cache_dir(project) == os.path.realpath(str(tmp_path / "다른캐시"))


def test_환경_변수가_정책을_이긴다(project, tmp_path, monkeypatch):
    project.data["paths"]["cacheDir"] = str(tmp_path / "정책캐시")
    monkeypatch.setenv("LAB_CACHE_DIR", str(tmp_path / "환경캐시"))
    assert C.cache_dir(project) == os.path.realpath(str(tmp_path / "환경캐시"))


def test_자리표시는_설정_안_한_것으로_본다(project, monkeypatch):
    monkeypatch.delenv("LAB_CACHE_DIR", raising=False)
    project.data["paths"]["cacheDir"] = "[캐시 폴더 — 미정]"
    assert C.cache_dir(project) == os.path.realpath(os.path.expanduser("~/lab-cache"))


def test_정책_기본값에_칸이_있다(project):
    assert project.paths["cacheDir"] == ""


# --- 보호 경로와 겹치면 거부 -----------------------------------------------------


def test_보호_경로_안은_거부(ready):
    """정책·자격 증명·허가 키가 있는 곳이다."""
    for guard in SB.hidden_paths(ready):
        with pytest.raises(C.CacheError) as err:
            C.check(os.path.join(guard, "캐시"), ready)
        assert "보호 경로 안이에요" in str(err.value)


def test_보호_경로를_품는_것도_거부(ready):
    """캐시가 보호 경로의 **부모**인 경우. 학습에 그 경로를 쓰기로 열어 주는 셈이다."""
    from app import policy_defaults as Dft

    parent = os.path.dirname(Dft.hard_protected_roots()[0])  # 저장소 루트
    assert parent != os.path.realpath(os.path.expanduser("~"))
    with pytest.raises(C.CacheError) as err:
        C.check(parent, ready)
    assert "품고 있어요" in str(err.value)


def test_비밀과_교차_오염은_다르게_다룬다(ready, tmp_path):
    """비밀은 `dataPaths` 로도 못 열고, 다른 프로젝트는 열 수 있다."""
    from app import registry

    other = tmp_path / "projects" / "다른프로젝트"
    other.mkdir(parents=True)
    registry.register(str(other), "other-proj")
    secrets = SB.secret_paths(ready)
    assert os.path.realpath(str(other)) not in secrets
    assert os.path.realpath(str(other)) in SB.hidden_paths(ready)
    assert any(h.endswith("/server") for h in secrets), secrets


def test_홈_폴더_자체는_거부(ready):
    with pytest.raises(C.CacheError) as err:
        C.check("~", ready)
    assert "홈 폴더를" in str(err.value)


def test_루트는_거부(ready):
    with pytest.raises(C.CacheError):
        C.check("/", ready)


def test_다른_실험_프로젝트_안은_거부(ready, tmp_path):
    from app import registry

    other = tmp_path / "projects" / "다른프로젝트"
    other.mkdir(parents=True)
    registry.register(str(other), "other-proj")
    with pytest.raises(C.CacheError):
        C.check(str(other / "캐시"), ready)


def test_프로젝트_안이면_경고만(ready):
    """막지는 않는다. 다시 내려받게 되고 저장소가 커진다고 알려 준다."""
    warnings = C.check(os.path.join(ready, "캐시"), ready)
    assert warnings and "프로젝트 안이에요" in warnings[0]


def test_멀쩡한_곳은_통과(ready, tmp_path):
    assert C.check(str(tmp_path / "lab-cache"), ready) == []


# --- 폴더와 환경 변수 -----------------------------------------------------------


def test_하위_폴더까지_만든다(ready, cache):
    got = C.ensure(str(cache), ready)
    assert got["dir"] == os.path.realpath(str(cache))
    for sub in C.SUBDIRS.values():
        assert os.path.isdir(cache / sub), sub


def test_환경_변수가_캐시_아래를_가리킨다(cache):
    env = C.env_for(str(cache))
    assert set(env) == {"HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "WANDB_DIR", "TMPDIR"}
    for value in env.values():
        assert value.startswith(os.path.realpath(str(cache)) + os.sep)
    assert env["TMPDIR"].endswith("/tmp")


def test_실행기가_캐시_변수를_덮어쓴다(ready, cache, monkeypatch):
    """호스트의 `~/.cache` 를 물려받으면 샌드박스에서 못 쓴다."""
    monkeypatch.setenv("HF_HOME", "/home/사용자/.cache/huggingface")
    monkeypatch.setenv("TMPDIR", "/tmp")
    env = P.build_env(spec_for(ready), cache_dir=str(cache))
    assert env["HF_HOME"] == os.path.join(os.path.realpath(str(cache)), "huggingface")
    assert env["TMPDIR"] == os.path.join(os.path.realpath(str(cache)), "tmp")


def test_캐시를_끄면_변수를_안_넣는다(ready):
    env = P.build_env(spec_for(ready), cache_dir="")
    assert "HF_HOME" not in env
    assert "TMPDIR" not in env


# --- 샌드박스 명령 --------------------------------------------------------------


def test_캐시를_쓰기로_바인드한다(ready, cache):
    C.ensure(str(cache), ready)
    argv = SB.command(["/bin/true"], project_root=ready, cache_dir=str(cache), bwrap="/usr/bin/bwrap")
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert binds == [ready, os.path.realpath(str(cache))]


def test_캐시_폴더가_없으면_안_띄운다(ready, tmp_path):
    with pytest.raises(SB.SandboxError) as err:
        SB.command(["/bin/true"], project_root=ready, cache_dir=str(tmp_path / "없음"), bwrap="/usr/bin/bwrap")
    assert "캐시 폴더가 없어요" in str(err.value)


def test_캐시가_프로젝트_안이면_두_번_바인드하지_않는다(ready):
    inside = os.path.join(ready, "캐시")
    os.makedirs(inside, exist_ok=True)
    argv = SB.command(["/bin/true"], project_root=ready, cache_dir=inside, bwrap="/usr/bin/bwrap")
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"] == [ready]


def test_가림보다_데이터셋_바인드가_뒤에_온다(ready, tmp_path):
    """뒤에 온 것이 이긴다. 가려진 곳 안의 데이터셋을 다시 뚫으려면 뒤여야 한다."""
    data = tmp_path / "자료"
    data.mkdir()
    argv = SB.command(
        ["/bin/true"],
        project_root=ready,
        extra_ro=[str(data)],
        hide=[str(tmp_path)],
        bwrap="/usr/bin/bwrap",
    )
    assert argv.index("--tmpfs") < argv.index("--ro-bind", argv.index("--tmpfs"))


def test_캐시가_가려질_곳이면_띄우지_않는다(ready, tmp_path):
    """`cache.check` 가 놓쳐도 여기서 멈춘다 (두 번째 자물쇠)."""
    cache_dir = tmp_path / "캐시"
    cache_dir.mkdir()
    with pytest.raises(SB.SandboxError) as err:
        SB.command(
            ["/bin/true"],
            project_root=ready,
            cache_dir=str(cache_dir),
            hide=[str(tmp_path)],
            bwrap="/usr/bin/bwrap",
        )
    assert "보호 경로 안이에요" in str(err.value)


def test_런처가_겹치는_캐시를_거부한다(ready, monkeypatch):
    guard = SB.hidden_paths(ready)[0]
    monkeypatch.setenv("LAB_CACHE_DIR", os.path.join(guard, "캐시"))
    with pytest.raises(C.CacheError):
        P.launch(spec_for(ready), use_sandbox=False)


# --- 실제로 띄워서 -------------------------------------------------------------


def run_probes(spec, *, cache_dir):
    launched = P.launch(spec, use_sandbox=True, cache_dir=cache_dir)
    outcome = P.wait(launched, timeout_sec=60, grace_sec=2, poll_sec=0.05)
    probe_file = os.path.join(spec.output_dir, "probes.json")
    probes = json.load(open(probe_file, encoding="utf-8")) if os.path.exists(probe_file) else []
    return outcome, {p.get("env") or p["path"]: p for p in probes}


@needs_bwrap
@pytest.mark.parametrize("name", ["HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "WANDB_DIR"])
def test_캐시_아래_쓰기는_호스트에_남는다(ready, cache, name):
    """막히면 매 실험마다 모델을 다시 내려받는다."""
    spec = spec_for(ready, "--probe-env", name)
    outcome, probes = run_probes(spec, cache_dir=str(cache))
    assert outcome.state == "done"
    probe = probes[name]
    assert probe["result"] == "MADE", probe
    assert os.path.exists(probe["path"]), probe  # 호스트에 **실제로** 남는다


@needs_bwrap
def test_TMPDIR_은_tmpfs_가_아니다(ready, cache):
    """샌드박스의 `/tmp` 는 메모리다. 큰 임시 파일이면 메모리가 터진다."""
    spec = spec_for(ready, "--probe-tempfile")
    outcome, probes = run_probes(spec, cache_dir=str(cache))
    assert outcome.state == "done"
    probe = probes["TMPDIR"]
    assert probe["result"] == "MADE", probe
    assert probe["value"] == os.path.join(os.path.realpath(str(cache)), "tmp")
    # /tmp 였다면 호스트에 안 남는다 (사설 tmpfs)
    assert os.path.exists(probe["path"]), probe


@needs_bwrap
def test_캐시를_끄면_임시_파일이_사라진다(ready):
    """캐시 없이 돌면 `TMPDIR` 이 샌드박스의 tmpfs 다. 그 차이를 고정한다."""
    spec = spec_for(ready, "--probe-tempfile")
    outcome, probes = run_probes(spec, cache_dir="")
    assert outcome.state == "done"
    probe = probes["TMPDIR"]
    assert probe["result"] == "MADE"
    assert probe["value"] == "/tmp"
    assert not os.path.exists(probe["path"])  # 호스트에 안 남는다


@needs_bwrap
def test_캐시를_켜도_보호_경로는_그대로_막힌다(ready, cache):
    """쓸 수 있는 바깥이 하나 생겼어도 비밀은 그대로 가려져야 한다."""
    from app import config

    config.ensure_grant_key()
    spec = spec_for(ready, "--probe-read", config.grant_key_path())
    outcome, probes = run_probes(spec, cache_dir=str(cache))
    assert outcome.state == "done"
    assert probes[config.grant_key_path()]["result"] == "BLOCKED"


@needs_bwrap
def test_가려진_곳_안의_데이터셋을_dataPaths_로_다시_읽는다(ready, cache, tmp_path):
    """다른 실험 프로젝트의 `data/` 를 공유하는 경우."""
    from app import registry

    other = tmp_path / "projects" / "자료프로젝트"
    data = other / "data"
    data.mkdir(parents=True)
    (data / "표본.txt").write_text("자료 한 줄\n", encoding="utf-8")
    registry.register(str(other), "data-proj")
    assert os.path.realpath(str(other)) in SB.hidden_paths(ready)

    target = str(data / "표본.txt")
    # dataPaths 없이: 가려져서 안 읽힌다
    spec = spec_for(ready, "--probe-read", target)
    _, probes = run_probes(spec, cache_dir=str(cache))
    assert probes[target]["result"] == "BLOCKED", probes

    # dataPaths 로 열면: 읽힌다
    write_config(ready, entrypoints=["src/train.py"], extra=f"  dataPaths: ['{data}']\n")
    spec = spec_for(ready, "--probe-read", target)
    _, probes = run_probes(spec, cache_dir=str(cache))
    assert probes[target]["result"] == "READ", probes
    assert "자료 한 줄" in probes[target]["head"]
