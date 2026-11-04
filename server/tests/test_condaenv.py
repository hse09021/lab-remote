"""🧪 실험용 conda 환경이 **우리 환경이 아닌지** — 보안 경계.

`.pth` 파일은 **인터프리터가 뜰 때 실행된다.** `site-packages` 에
`import os; os.system(...)` 한 줄이 든 `.pth` 가 있으면 그 환경의 파이썬이
뜨는 순간 돈다 — `import` 를 안 해도 된다.

훅은 래퍼에 박힌 파이썬으로 **도구 호출마다** 뜬다. 오케스트레이터도 같은
환경에서 돈다. 둘 다 샌드박스 **밖, 사용자 권한**이다.

그래서 실험용 환경이 `labremote` 나 `base` 면 **사람이 승인한 패키지 하나가**
잠금 판정 코드 안의 임의 코드 실행이 된다 — 샌드박스·훅·앵커·projectguard 가
전부 그 아래에서 돌기 때문에 **방어가 통째로 우회된다.**
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
    monkeypatch.setattr(C.sandbox, "conda_roots", lambda: [str(root)])
    monkeypatch.setattr(C, "_hook_python", lambda: str(ours / "bin" / "python"))
    monkeypatch.setattr(sys, "prefix", str(ours))
    monkeypatch.setattr(sys, "base_prefix", str(ours))
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)
    return {"root": str(root), "ours": str(ours), "ok": "exp-a"}


# --- 🔑 거부 ----------------------------------------------------------------


def test_우리_환경을_거부한다(fake_conda):
    got = C.check("labremote")
    assert got["ok"] is False
    assert "우리 코드가 도는 환경" in got["reason"]
    assert ".pth" in got["reason"] and "밖" in got["reason"]
    assert got["prefix"] == fake_conda["ours"]


def test_base_를_거부한다(fake_conda):
    for name in ("base", "root", "BASE", "Root"):
        got = C.check(name)
        assert got["ok"] is False, name
        assert "base" in got["reason"]


def test_conda_설치_폴더를_가리키면_거부한다(fake_conda, monkeypatch):
    """`<root>/envs/<이름>` 이 루트 자신이 되는 경우는 없지만, `CONDA_ENVS_PATH`
    로 루트를 가리킬 수 있다."""
    monkeypatch.setenv("CONDA_ENVS_PATH", os.path.dirname(fake_conda["root"]))
    got = C.check(os.path.basename(fake_conda["root"]))
    assert got["ok"] is False


def test_훅_래퍼의_환경을_거부한다(tmp_path, monkeypatch):
    """지금 프로세스와 **다른** 환경이어도 훅이 거기서 뜨면 막아야 한다."""
    root = tmp_path / "mc"
    hookenv = root / "envs" / "hookpy"
    (hookenv / "bin").mkdir(parents=True)
    (root / "envs" / "other").mkdir(parents=True)
    monkeypatch.setattr(C.sandbox, "conda_roots", lambda: [str(root)])
    monkeypatch.setattr(C, "_hook_python", lambda: str(hookenv / "bin" / "python"))
    monkeypatch.setattr(sys, "prefix", str(root / "envs" / "other"))
    monkeypatch.setattr(sys, "base_prefix", str(root / "envs" / "other"))
    monkeypatch.delenv("CONDA_ENVS_PATH", raising=False)

    assert C.check("hookpy")["ok"] is False
    assert C.check("other")["ok"] is False  # 지금 프로세스의 환경
    assert C.check("exp-b")["ok"] is True


@pytest.mark.parametrize(
    "bad",
    ["../labremote", "/home/u/miniconda3/envs/labremote", "~/x", "a b", "a;b",
     "a/b", "a\\b", "", "[미정]", ".hidden", "-x"],
)
def test_경로와_이상한_이름을_거부한다(fake_conda, bad):
    """🔑 비교는 이름이 아니라 실제 경로로 하지만, `conda run -n` 에 넘기는
    이름 자체도 평범해야 한다 — `../labremote` 로 우리 환경을 가리키는 길."""
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
    """만들기 전에도 `Config.yaml` 에 적을 수 있다. 이름이 겹칠 때만 막는다."""
    got = C.check("not-made-yet")
    assert got["ok"] is True and got["prefix"] == ""


def test_실행하지_않고_경로를_푼다(fake_conda, monkeypatch):
    """`conda run -n <이름> python` 으로 풀면 **그 .pth 가 이미 돈다.**
    그래서 subprocess 를 쓰지 않는다."""
    import subprocess

    def boom(*a, **k):
        raise AssertionError("아무것도 실행하면 안 돼요")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert C.check("exp-a")["ok"] is True
    assert C.candidates("exp-a")


# --- 설치기와 학습 실행기 **둘 다** ------------------------------------------


def test_설치기가_우리_환경을_거부한다(fake_conda):
    from app.runner import pkginstall as PI
    from app.runner import pkgspec as PS

    parsed = PS.parse({"packages": [{"name": "peft"}]})
    with pytest.raises(PI.InstallError) as err:
        PI.build_argv(parsed, "labremote")
    assert "우리 코드가 도는 환경" in str(err.value)

    # install() 은 던지지 않고 사유를 돌려준다
    got = PI.install(parsed, "labremote", runner=lambda *a, **k: None)
    assert got["ok"] is False and "환경" in got["reason"]

    # 정상 환경은 통과한다
    assert "--no-cache-dir" in PI.build_argv(parsed, "exp-a")


def test_학습_실행기가_우리_환경을_거부한다(fake_conda, tmp_path):
    from app.runner import process as P
    from app.runner.spec import RunSpec

    def make(env):
        return RunSpec(
            project="hook-sandbox",
            root=str(tmp_path),
            experiment_id="EXP-001",
            entrypoint="src/train.py",
            entrypoint_abs=str(tmp_path / "src" / "train.py"),
            conda_env=env,
        )

    with pytest.raises(C.EnvRefused):
        P.inner_argv(make("labremote"))
    with pytest.raises(C.EnvRefused):
        P.inner_argv(make("base"))
    got = P.inner_argv(make("exp-a"))
    assert got[:5] == ["conda", "run", "-n", "exp-a", "--no-capture-output"]


# --- 생성기와 doctor --------------------------------------------------------


def test_생성기가_우리_환경_이름을_거절한다(fake_conda):
    from app import registry
    from app.generator.spec import ProjectSpec

    with pytest.raises(registry.InvalidName):
        ProjectSpec("labremote")
    with pytest.raises(registry.InvalidName):
        ProjectSpec("myproj", env_name="base")
    # 평범한 이름은 된다
    assert ProjectSpec("myproj").env_name == "myproj"


def test_생성기_템플릿의_기본_환경이_우리_환경이_아니다():
    """템플릿의 `env.conda` 는 `$env_name` 이고 기본값은 프로젝트 이름이다."""
    from app.generator import render

    body = render.read_template("specifications/Config.yaml.tmpl")
    assert "conda: $env_name" in body
    assert "labremote" not in body


def test_doctor_가_우리_환경을_잡는다(project, project_root, fake_conda):
    from app import doctor, loop_layout as L

    path = os.path.join(project_root, L.LOOP_LAYOUT["config"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("env:\n  conda: labremote\n")
    got = doctor.project_env_check(project_root, "hook-sandbox")
    assert got["ok"] is False
    assert "우리 코드가 도는 환경" in got["detail"]
    assert "conda create" in got["hint"]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("env:\n  conda: exp-a\n")
    assert doctor.project_env_check(project_root, "hook-sandbox")["ok"] is True


# --- T7 · doctor 경고 단계 ---------------------------------------------------


def test_경고는_종료코드를_바꾸지_않는다():
    """전에는 `ok` 참/거짓뿐이라 권고 하나가 doctor 를 통째로 빨갛게 만들었다.
    고칠 수 없는 ✘ 가 섞이면 사람이 ✘ 를 무시하게 된다."""
    from app import doctor

    ok = doctor.Check(True, "좋아요")
    bad = doctor.Check(False, "나빠요", hint="고쳐요")
    warned = doctor.warn("권고예요", "이렇게 하면 좋아요", hint="이렇게요")

    assert ok["level"] == "ok" and ok["ok"] is True
    assert bad["level"] == "bad" and bad["ok"] is False
    assert warned["level"] == "warn" and warned["ok"] is False

    report = {"checks": [ok, warned], "limitations": []}
    text = doctor.render(report)
    assert "⚠ 권고예요" in text and "✔ 좋아요" in text
    assert "종료코드를 바꾸지 않아요" in text
    # 힌트는 ✔ 가 아닐 때만 보인다
    assert "이렇게요" in text

    with pytest.raises(ValueError):
        doctor.Check(False, "x", level="모르는값")


def test_doctor_가_경고만_있으면_종료코드_0(capsys, monkeypatch):
    from app import cli, doctor

    monkeypatch.setattr(
        doctor, "run",
        lambda: {
            "ok": True,
            "warnings": [doctor.warn("권고", "x")],
            "checks": [doctor.Check(True, "좋아요"), doctor.warn("권고", "x")],
            "limitations": [],
        },
    )
    assert cli.main(["doctor"]) == 0
    assert "⚠" in capsys.readouterr().out


def test_샌드박스가_꺼져_있으면_헤드리스가_안_뜬다고_경고한다(project, project_root):
    """원래 계획의 6번 — ✘ 가 아니라 ⚠ 다. 위험한 상태로 도는 게 아니라
    **안 도는** 상태다(런처가 fail-closed 로 거부한다)."""
    from app import doctor

    got = doctor.bash_sandbox_check(project_root, "hook-sandbox")
    assert got["level"] == "warn"
    assert "헤드리스 루프가 안 떠요" in got["detail"]


def test_셸_보호_함수를_찾는다(tmp_path, monkeypatch):
    from app import doctor

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home)))

    # 없으면 ⚠
    got = doctor.shell_guard_check()
    assert got["level"] == "warn"
    assert "docs/SETUP.md" in got["hint"]

    # 있으면 ✔ — 읽기만 한다
    rc = home / ".bashrc"
    rc.write_text("claude() { labremote claude x; }\n", encoding="utf-8")
    before = rc.read_text(encoding="utf-8")
    got = doctor.shell_guard_check()
    assert got["level"] == "ok" and ".bashrc" in got["detail"]
    assert rc.read_text(encoding="utf-8") == before, "셸 설정을 고치면 안 돼요"


def test_SETUP_문서에_셸_함수와_환경_안내가_있다():
    import pathlib

    body = pathlib.Path(__file__).resolve().parents[2] / "docs" / "SETUP.md"
    text = body.read_text(encoding="utf-8")
    # 셸 함수
    assert "labremote_projects_root" in text and "command claude" in text
    # 프로젝트마다 별도 환경
    assert "conda create -n" in text and ".pth" in text
    # 복구 절차
    assert "labremote git-backups" in text and "refs/heads/백업/*" in text
