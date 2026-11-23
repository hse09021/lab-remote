"""🧪 실행·설치에 쓸 conda 환경이 **lab.remote 자신의 환경이 아닌지.**

`.pth` 파일은 **인터프리터가 뜰 때 실행된다.** lab.remote 서버는 `labremote`
환경에서, `conda` 명령은 `base`의 파이썬으로 돈다. 그 둘에 실험용 패키지를
깔면 서버나 conda가 뜰 때 임의 코드가 돈다 — 그래서 막는다.
"""

import os
import sys

import pytest

from app.runner import condaenv as C


@pytest.fixture()
def fake_conda(tmp_path, monkeypatch):
    """conda 설치 폴더를 임시로 만든다. 우리 환경도 그 안에 둔다."""
    root = tmp_path / "miniconda3"
    ours = root / "envs" / "labremote"
    (ours / "bin").mkdir(parents=True)
    (ours / "bin" / "python").write_text("", encoding="utf-8")
    (root / "envs" / "exp-a").mkdir(parents=True)
    monkeypatch.setattr(C, "conda_roots", lambda: [str(root)])
    monkeypatch.setattr(sys, "prefix", str(ours))
    monkeypatch.setattr(sys, "base_prefix", str(ours))
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)
    return {"root": str(root), "ours": str(ours), "ok": "exp-a"}


# --- 🔑 거부 ----------------------------------------------------------------


def test_우리_환경을_거부한다(fake_conda):
    got = C.check("labremote")
    assert got["ok"] is False
    assert "lab.remote가 도는 환경" in got["reason"]
    assert got["prefix"] == fake_conda["ours"]


def test_base_를_거부한다(fake_conda):
    for name in ("base", "root", "BASE", "Root"):
        got = C.check(name)
        assert got["ok"] is False, name
        assert "base" in got["reason"]


def test_conda_설치_폴더를_가리키면_거부한다(fake_conda, monkeypatch):
    """`<root>/envs/<이름>`이 루트 자신이 되는 경우는 없지만, `CONDA_ENVS_PATH`
    로 루트를 가리킬 수 있다."""
    monkeypatch.setenv("CONDA_ENVS_PATH", os.path.dirname(fake_conda["root"]))
    got = C.check(os.path.basename(fake_conda["root"]))
    assert got["ok"] is False




@pytest.mark.parametrize(
    "bad",
    ["../labremote", "/home/u/miniconda3/envs/labremote", "~/x", "a b", "a;b",
     "a/b", "a\\b", "", "[미정]", ".hidden", "-x"],
)
def test_경로와_이상한_이름을_거부한다(fake_conda, bad):
    """🔑 비교는 이름이 아니라 실제 경로로 하지만, `conda run -n`에 넘기는
    이름 자체도 평범해야 한다 — `../labremote`로 우리 환경을 가리키는 길."""
    assert C.check(bad)["ok"] is False, bad


def test_시스템_파이썬을_거부한다(fake_conda, monkeypatch):
    monkeypatch.setenv("CONDA_ENVS_PATH", "/usr/lib")
    assert C.check("python3")["ok"] is False


# --- 통과 -------------------------------------------------------------------


def test_평범한_실험_환경은_통과한다(fake_conda):
    got = C.check(fake_conda["ok"])
    assert got["ok"] is True
    assert got["prefix"].endswith("envs/exp-a")


def test_아직_없는_환경도_통과한다(fake_conda):
    """만들기 전에도 이름은 받는다. 보호 대상과 겹칠 때만 막는다."""
    got = C.check("not-made-yet")
    assert got["ok"] is True and got["prefix"] == ""


def test_실행하지_않고_경로를_푼다(fake_conda, monkeypatch):
    """`conda run -n <이름> python`으로 풀면 **그 .pth가 이미 돈다.**
    그래서 subprocess를 쓰지 않는다."""
    import subprocess

    def boom(*a, **k):
        raise AssertionError("아무것도 실행하면 안 돼요")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert C.check("exp-a")["ok"] is True
    assert C.candidates("exp-a")


# --- 설치기 -------------------------------------------------------------------


def test_설치기가_우리_환경을_거부한다(fake_conda):
    from app.runner import pkginstall as PI
    from app.runner import pkgspec as PS

    parsed = PS.parse({"packages": [{"name": "peft"}]})
    with pytest.raises(PI.InstallError) as err:
        PI.build_argv(parsed, "labremote")
    assert "lab.remote가 도는 환경" in str(err.value)

    # install()은 던지지 않고 사유를 돌려준다
    got = PI.install(parsed, "labremote", runner=lambda *a, **k: None)
    assert got["ok"] is False and "환경" in got["reason"]

    # 정상 환경은 통과한다
    assert "--no-cache-dir" in PI.build_argv(parsed, "exp-a")
