"""📦 패키지 설치 — 검증·설치·승인 흐름.

왜 이 경로가 있나 (S1 의 M3 실측): **Claude 의 Bash 로는 `pip install` 이
조용히 실패한다.** conda 환경은 프로젝트 밖이라 샌드박스가 쓰기를 버리고,
프로그램에는 성공으로 보인다. 사람이 승인해도 아무 일이 안 난다.

그래서 설치는 승인 뒤 **오케스트레이터가 샌드박스 밖에서** 한다. AI 가 쓴
글자가 사용자 권한으로 도는 명령에 들어가므로 `pkgspec` 이 경계다.
"""

import json
import os
import subprocess

import pytest

from app.orchestrator import installs as I
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
    """`~/lab-cache` 는 모든 프로젝트가 공유해서 AI 코드가 오염시킬 수 있고,
    오케스트레이터는 **샌드박스 밖**에서 돈다 — 오염된 휠을 읽으면 그게 곧
    코드 실행이다."""
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
    # pip 전역 설정도 안 읽는다 — 거기 index-url 이 있으면 모르는 곳에서 받는다
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
    """`shell=False` 로 넘긴다 — 인자에 `;` 가 있어도 해석되지 않는다."""
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


# --- 승인 흐름 ---------------------------------------------------------------


@pytest.fixture()
def made_env(monkeypatch):
    """conda 환경이 **있는** 것으로 둔다.

    `installs.approve` 가 승인 전에 환경이 실제로 있는지 본다 — 없는 환경에
    승인하면 `pkg` 와 같은 함정이 된다(사람이 승인했고 기록에 남고 아무 일도
    안 일어난다). 환경 검사 자체는 `test_condaenv.py` 가 본다.
    """
    from app.runner import condaenv

    monkeypatch.setattr(
        condaenv, "require_made", lambda name: f"/fake/envs/{name}"
    )
    return "labenv"


@pytest.fixture()
def asked(project, project_root, made_env):
    """설치 요청이 놓인 프로젝트."""
    from app import loop_layout as L

    config = os.path.join(project_root, L.LOOP_LAYOUT["config"])
    os.makedirs(os.path.dirname(config), exist_ok=True)
    with open(config, "w", encoding="utf-8") as fh:
        fh.write("env:\n  conda: labenv\n")

    path = I.request_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"version": 1, "packages": [{"name": "peft", "spec": "==0.13.2"}],
             "reason": "LoRA 를 쓰려고요"},
            fh,
        )
    return project_root


def _ok_runner(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, "Successfully installed peft-0.13.2", "")


def test_요청을_읽어_승인_대기를_연다(asked, conn, monkeypatch):
    sent = []
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: sent.append(k) or {"ok": True})
    got = I.sync(conn, "hook-sandbox", asked)
    assert got["ok"] is True and got["opened"]
    items = I.pending(conn, "hook-sandbox")
    assert len(items) == 1 and "peft==0.13.2" in items[0]["request"]
    assert sent and "설치 승인이 필요해요" in sent[0]["title"]
    # AI 가 읽는 결과 파일에 "기다려 주세요" 가 적힌다
    payload = json.loads(open(I.result_path(asked), encoding="utf-8").read())
    assert payload["state"] == "waiting"


def test_같은_요청을_두_번_보면_새로_열지_않는다(asked, conn, monkeypatch):
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    first = I.sync(conn, "hook-sandbox", asked)
    second = I.sync(conn, "hook-sandbox", asked)
    assert second["opened"] == first["opened"]
    assert len(I.pending(conn, "hook-sandbox")) == 1


def test_승인하면_설치하고_결과를_남긴다(asked, conn, monkeypatch):
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]
    got = I.approve(conn, "hook-sandbox", opened, runner=_ok_runner)
    assert got["ok"] is True and got["env"] == "labenv"
    assert "--no-cache-dir" in got["result"]["argv"]

    payload = json.loads(open(I.result_path(asked), encoding="utf-8").read())
    assert payload["ok"] is True and payload["state"] == "installed"
    # 진본은 lab.db 다
    from app.store import approvals as AP

    assert AP.get(conn, opened)["state"] == "consumed"


def test_승인_뒤_요청이_바뀌면_설치하지_않는다(asked, conn, monkeypatch):
    """🔑 사람이 본 목록과 다른 걸 깔지 않는다."""
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]

    with open(I.request_path(asked), "w", encoding="utf-8") as fh:
        json.dump({"packages": [{"name": "requests"}], "reason": "바꿔치기"}, fh)

    called = []
    got = I.approve(
        conn, "hook-sandbox", opened,
        runner=lambda *a, **k: called.append(a) or _ok_runner(*a, **k),
    )
    assert got["ok"] is False
    assert "달라요" in got["reason"]
    assert called == [], "설치를 띄우면 안 돼요"


def test_요청이_규칙에_안_맞으면_거부하고_알려_준다(project, project_root, conn):
    path = I.request_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"packages": [{"name": "git+https://evil/x"}]}, fh)
    got = I.sync(conn, "hook-sandbox", project_root)
    assert got["ok"] is False
    payload = json.loads(open(I.result_path(project_root), encoding="utf-8").read())
    assert payload["state"] == "rejected" and payload["reason"]


def test_요청_파일이_없으면_아무_일도_안_한다(project, project_root, conn):
    got = I.sync(conn, "hook-sandbox", project_root)
    assert got["ok"] is True and got["opened"] is None
    assert not os.path.exists(I.result_path(project_root))


def test_거절하면_결과에_적힌다(asked, conn, monkeypatch):
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]
    got = I.deny(conn, "hook-sandbox", opened, reason="버전이 안 맞아요")
    assert got["ok"] is True
    payload = json.loads(open(I.result_path(asked), encoding="utf-8").read())
    assert payload["state"] == "denied" and "버전이" in payload["reason"]


def test_환경_이름은_Config_yaml_에서_읽는다(asked, conn, monkeypatch):
    """요청이 환경을 정하게 두면 다른 환경에 깔 수 있다. `Config.yaml` 은
    실험이 도는 중에 잠겨 있다."""
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    from app import loop_layout as L

    with open(os.path.join(asked, L.LOOP_LAYOUT["config"]), "w", encoding="utf-8") as fh:
        fh.write("env:\n  conda: 다른환경\n")
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]
    got = I.approve(conn, "hook-sandbox", opened, runner=_ok_runner)
    # 한글 이름은 NAME_RE 를 못 지나간다 — 설치하지 않고 사유를 준다
    assert got["ok"] is False


# --- 훅의 안내 문구 ----------------------------------------------------------


def test_훅의_pkg_거절_사유가_요청_파일을_안내한다(ctx, hook_event):
    from app.hooks import decide, messages

    text = messages.pkg_hint()
    assert "state/Install_request.json" in text
    assert "state/Install_result.json" in text
    assert "샌드박스" in text

    got = messages.ask_action("패키지 설치", "pip install peft", action="pkg")
    assert "Install_request.json" in got
    # 다른 행동에는 안 붙는다
    assert "Install_request" not in messages.ask_action("파일 삭제", "x", action="del")
    assert decide is not None


# --- 🔑 환경이 없으면 승인 자체를 막는다 (S9 e2e) ----------------------------


def test_환경이_없으면_승인하지_않는다(project, project_root, conn, monkeypatch):
    """없는 환경에 승인하면 `pkg` 와 같은 함정이 된다 — 사람이 승인했고
    `approvals` 에 기록이 남고 **아무 일도 안 일어난다.**

    승인은 "이 일이 일어난다" 는 뜻이어야 한다.
    """
    from app import loop_layout as L

    config = os.path.join(project_root, L.LOOP_LAYOUT["config"])
    os.makedirs(os.path.dirname(config), exist_ok=True)
    with open(config, "w", encoding="utf-8") as fh:
        fh.write("env:\n  conda: nomade-env\n")
    path = I.request_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"packages": [{"name": "peft"}], "reason": "x"}, fh)

    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", project_root)["opened"]

    called = []
    got = I.approve(
        conn, "hook-sandbox", opened,
        runner=lambda *a, **k: called.append(a) or _ok_runner(*a, **k),
    )
    assert got["ok"] is False
    assert "없어요" in got["reason"] and "docs/SETUP.md" in got["reason"]
    assert got["needsEnv"] == "nomade-env"
    assert called == [], "설치를 띄우면 안 돼요"
    # 승인도 소비도 되지 않았다 — 다시 승인할 수 있다
    from app.store import approvals as AP

    assert AP.get(conn, opened)["state"] == "open"


def test_실패_사유가_사람이_읽을_문구다():
    """⚠ 전에는 CLI 가 `✘ None` 을 찍었다 — `approve()` 의 반환에 `reason` 이
    없었다(S9 e2e 가 잡았다)."""
    raw = "EnvironmentLocationNotFound: Not a conda environment: /home/u/envs/x"
    got = I._human({"ok": False, "reason": raw, "exitCode": 1}, "hook-sandbox")
    assert "실험 환경 hook-sandbox 이 없어요" in got
    assert "docs/SETUP.md" in got and "conda create -n hook-sandbox" in got

    got = I._human({"ok": False, "reason": "ERROR: No matching distribution found",
                    "exitCode": 1}, "e")
    assert "그런 패키지·버전이 없어요" in got

    # 모르는 실패는 **지어내지 않고** 원문 꼬리를 보여 준다
    got = I._human({"ok": False, "reason": "알 수 없는 오류\n마지막 줄이에요",
                    "exitCode": 7}, "e")
    assert got == "마지막 줄이에요"
    # 원문이 비면 종료코드라도 보여 준다
    assert "7" in I._human({"ok": False, "reason": "", "exitCode": 7}, "e")


def test_require_made_는_없는_환경을_거절한다():
    """`check()` 는 아직 없는 환경도 통과시킨다 — `Config.yaml` 에 만들기 전에
    이름을 적을 수 있어야 한다. **설치**는 있어야 한다."""
    from app.runner import condaenv

    assert condaenv.check("not-made-yet")["ok"] is True
    with pytest.raises(condaenv.EnvRefused) as exc:
        condaenv.require_made("not-made-yet")
    assert "docs/SETUP.md" in str(exc.value)


def test_깔리면_오케스트레이터가_요청_파일을_지운다(asked, conn, monkeypatch):
    """🔑 프롬프트가 Claude 에게 "요청 파일은 지워 주세요" 라고 했는데
    **삭제는 `del` → ask** 였다 — 쓰기 쪽과 같은 순환이었다(S9 e2e 가 잡았다).

    요청 파일의 수명은 시스템의 일이다: 요청은 AI 가 쓰고 **소비는 우리가**
    한다. 안 지우면 다음 루프에서 같은 요청이 또 열린다.
    """
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]
    assert os.path.exists(I.request_path(asked))

    got = I.approve(conn, "hook-sandbox", opened, runner=_ok_runner)

    assert got["ok"] is True
    assert not os.path.exists(I.request_path(asked)), "깔렸으면 지워야 해요"
    payload = json.loads(open(I.result_path(asked), encoding="utf-8").read())
    assert payload["state"] == "installed" and payload["requestRemoved"] is True
    assert "시스템이 지웠어요" in payload["hint"]
    # 다음 루프에서 같은 요청이 또 열리지 않는다
    assert I.sync(conn, "hook-sandbox", asked)["opened"] is None


def test_실패하면_요청_파일을_남긴다(asked, conn, monkeypatch):
    """사람이 고칠 수 있게 둔다 — 지우면 무엇을 요청했는지 사라진다."""
    monkeypatch.setattr(I.notifier, "send", lambda *a, **k: {"ok": True})
    opened = I.sync(conn, "hook-sandbox", asked)["opened"]

    def fail(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "ERROR: no matching distribution")

    got = I.approve(conn, "hook-sandbox", opened, runner=fail)
    assert got["ok"] is False
    assert os.path.exists(I.request_path(asked))
    payload = json.loads(open(I.result_path(asked), encoding="utf-8").read())
    assert payload["state"] == "failed" and payload["requestRemoved"] is False


def test_프롬프트가_지우라고_하지_않는다():
    """프롬프트와 코드가 어긋나면 Claude 가 못 할 일을 시킨다."""
    from app.agent import prompts

    body = prompts.render("resume_after_approval",
                          {"request": "x", "actions": "y", "context": "z"})
    assert "시스템이 지웠어요" in body
    assert "요청 파일(`state/Install_request.json`)은 지워 주세요" not in body
