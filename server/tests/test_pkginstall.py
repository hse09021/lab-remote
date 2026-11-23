"""📦 패키지 설치 — 검증·설치 명령·환경.

Conda 화면에서 사람이 고른 패키지를 lab.remote가 사용자 권한으로 설치한다.
입력 칸의 글자가 명령에 섞이지 않게 `pkgspec`이 막는다.
"""

import json
import os
import subprocess

import pytest

from app.runner import pkginstall as PI
from app.runner import pkgspec as PS

# --- 🔑 검증 (보안 경계) -----------------------------------------------------


def test_평범한_요청은_통과한다():
    got = PS.parse(
        {
            "version": 1,
            "packages": [{"name": "peft", "spec": "==0.13.2"}, {"name": "accelerate"}],
            "reason": "LoRA 어댑터를 쓰려고요",
        }
    )
    assert PS.requirements(got) == ["accelerate", "peft==0.13.2"]
    assert got["allowSource"] is False
    assert "2개" in PS.summary(got)


def test_extras_도_받는다():
    got = PS.parse({"packages": [{"name": "peft", "extras": "torch", "spec": ">=0.1"}]})
    assert PS.requirements(got) == ["peft[torch]>=0.1"]


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "-e ."},
        {"name": "git+https://github.com/x/y"},
        {"name": "https://evil/x.whl"},
        {"name": "../../etc/passwd"},
        {"name": "x; rm -rf /"},
        {"name": "x && curl evil"},
        {"name": "x | sh"},
        {"name": "$(whoami)"},
        {"name": "`id`"},
        {"name": "x@1.0"},
        {"name": "./local/path"},
        {"name": "torch.tar.gz"},
        {"name": "x", "spec": "--index-url=http://evil"},
        {"name": "x", "spec": "; rm -rf /"},
        {"name": "x", "spec": "==$(id)"},
        {"name": " peft"},
        {"name": "peft "},
        {"name": "1peft"},
        {"name": ""},
        {"name": "x" * 100},
        {"name": "x", "extras": "a;b"},
        {"name": "x", "index_url": "http://evil"},
    ],
)
def test_셸과_URL_과_경로를_거부한다(bad):
    """하나라도 섞이면 **전체를 거부**한다 — 일부만 걸러서 돌리면 사람이
    승인한 것과 다른 게 깔린다."""
    with pytest.raises(PS.SpecError):
        PS.parse({"packages": [bad]})


@pytest.mark.parametrize(
    "name", ["pip", "PIP", "setuptools", "wheel", "conda", "mamba", "claude", "anthropic"]
)
def test_설치_도구_자신은_거부한다(name):
    """바꿔치기하면 **다음 설치가 임의 코드**가 된다."""
    with pytest.raises(PS.SpecError) as err:
        PS.parse({"packages": [{"name": name}]})
    assert "설치하지 않아요" in str(err.value)


def test_개수_상한이_있다():
    items = [{"name": f"pkg{n}"} for n in range(PS.MAX_PACKAGES + 1)]
    with pytest.raises(PS.SpecError) as err:
        PS.parse({"packages": items})
    assert str(PS.MAX_PACKAGES) in str(err.value)


def test_빈_목록과_모르는_칸을_거부한다():
    for bad in ({"packages": []}, {"packages": [{"name": "x"}], "huh": 1},
                {"version": 2, "packages": [{"name": "x"}]}, [], "x"):
        with pytest.raises(PS.SpecError):
            PS.parse(bad)


def test_같은_패키지를_다르게_두_번_적으면_거부한다():
    with pytest.raises(PS.SpecError):
        PS.parse({"packages": [{"name": "peft", "spec": "==1.0"},
                               {"name": "peft", "spec": "==2.0"}]})
    # 똑같이 두 번은 하나로 본다
    got = PS.parse({"packages": [{"name": "peft"}, {"name": "peft"}]})
    assert PS.requirements(got) == ["peft"]


def test_allowSource_는_불린만():
    with pytest.raises(PS.SpecError):
        PS.parse({"packages": [{"name": "x"}], "allowSource": "yes"})


def test_지문에_사유가_안_들어간다():
    """사유를 고쳐 같은 설치를 다시 승인받는 길을 막는다."""
    a = PS.parse({"packages": [{"name": "peft"}], "reason": "하나"})
    b = PS.parse({"packages": [{"name": "peft"}], "reason": "둘"})
    assert PS.fingerprint(a) == PS.fingerprint(b)
    c = PS.parse({"packages": [{"name": "peft", "spec": "==1.0"}]})
    assert PS.fingerprint(c) != PS.fingerprint(a)
    d = PS.parse({"packages": [{"name": "peft"}], "allowSource": True})
    assert PS.fingerprint(d) != PS.fingerprint(a)


# --- 🔑 설치 명령과 환경 (메모: 공용 캐시를 쓰지 않는다) ----------------------


def test_argv_에_no_cache_dir_가_있다():
    """다른 곳이 쓴 캐시를 설치 코드로 받지 않는다 — 오염된 휠을 읽으면 그게
    곧 코드 실행이다."""
    got = PS.parse({"packages": [{"name": "peft", "spec": "==0.13.2"}]})
    argv = PI.build_argv(got, "labenv")
    assert "--no-cache-dir" in argv
    assert "--no-input" in argv
    assert "--only-binary=:all:" in argv
    assert argv[:5] == ["conda", "run", "-n", "labenv", "--no-capture-output"]
    assert argv[-1] == "peft==0.13.2"


def test_환경에_캐시_변수가_하나도_없다():
    base = {
        "HOME": "/h", "PATH": "/b",
        "PIP_CACHE_DIR": "/home/u/lab-cache/pip",
        "HF_HOME": "/home/u/lab-cache/huggingface",
        "XDG_CACHE_HOME": "/home/u/lab-cache",
        "TORCH_HOME": "/home/u/lab-cache/torch",
        "TMPDIR": "/home/u/lab-cache/tmp",
        "WANDB_DIR": "/home/u/lab-cache/wandb",
        "ANTHROPIC_API_KEY": "k",
        "LAB_DATA_DIR": "/secret",
    }
    env = PI.build_env(base)
    for name in PI.CACHE_ENV_NAMES:
        assert name not in env, name
    assert "ANTHROPIC_API_KEY" not in env
    assert "LAB_DATA_DIR" not in env
    # pip 전역 설정도 안 읽는다 — 거기 index-url이 있으면 모르는 곳에서 받는다
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_소스_배포는_양쪽이_맞아야_열린다():
    plain = PS.parse({"packages": [{"name": "x"}]})
    asked = PS.parse({"packages": [{"name": "x"}], "allowSource": True})
    # 요청만 있어도 안 열린다
    assert "--only-binary=:all:" in PI.build_argv(asked, "e", allow_source=False)
    # 승인만 있어도 안 열린다
    assert "--only-binary=:all:" in PI.build_argv(plain, "e", allow_source=True)
    # 둘 다 맞을 때만 열린다
    assert "--only-binary=:all:" not in PI.build_argv(asked, "e", allow_source=True)


def test_conda_환경_이름을_검사한다():
    got = PS.parse({"packages": [{"name": "x"}]})
    for bad in ("", "a b", "a;b", "../x", "$(id)"):
        with pytest.raises(PI.InstallError):
            PI.build_argv(got, bad)


def test_셸을_안_거친다(monkeypatch):
    """`shell=False`로 넘긴다 — 인자에 `;`가 있어도 해석되지 않는다."""
    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    got = PS.parse({"packages": [{"name": "peft"}]})
    PI.install(got, "labenv", runner=fake)
    assert isinstance(seen["argv"], list)
    assert "shell" not in seen["kw"]


def test_실패해도_던지지_않고_원문을_보관한다():
    def fake(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: no matching distribution")

    got = PS.parse({"packages": [{"name": "nope-nope-nope"}]})
    result = PI.install(got, "labenv", runner=fake)
    assert result["ok"] is False and result["exitCode"] == 1
    assert "no matching distribution" in result["output"]


def test_타임아웃도_던지지_않는다():
    def fake(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    got = PS.parse({"packages": [{"name": "x"}]})
    result = PI.install(got, "labenv", runner=fake, timeout_sec=1)
    assert result["ok"] is False and result["exitCode"] is None


# --- 환경 ------------------------------------------------------------------

def test_require_made_는_없는_환경을_거절한다():
    """`check()`는 아직 없는 환경도 통과시킨다. **설치**는 있어야 한다."""
    from app.runner import condaenv

    assert condaenv.check("not-made-yet")["ok"] is True
    with pytest.raises(condaenv.EnvRefused) as exc:
        condaenv.require_made("not-made-yet")
    assert "conda create -n not-made-yet" in str(exc.value)
