"""학습 프로세스 — 띄우기·타임아웃·손자 정리·종료코드.

가짜 학습(`tests/fixtures/fake_train.py`)으로 돌린다. 계획의 결정이다 —
**루프부터 가짜로 돌리고** 진짜 학습은 10단계다.

샌드박스는 여기서 끄고 띄운다(`use_sandbox=False`). 샌드박스 자체는
`test_runner_sandbox.py` 에서 따로 잰다.
"""

import json
import os
import shutil
import time

import pytest

from app.runner import process as P
from app.runner import spec as S
from tests.test_runner_spec import load, write_config

FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_train.py")


@pytest.fixture()
def ready(project, project_root):
    os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
    shutil.copy(FAKE, os.path.join(project_root, "src", "train.py"))
    write_config(project_root, entrypoints=["src/train.py"])
    os.makedirs(os.path.join(project_root, "experiments", "EXP-001"), exist_ok=True)
    return project_root


def run_spec(root, **payload):
    base = {"entrypoint": "src/train.py"}
    base.update(payload)
    got = load(root, base)
    # 가짜 학습은 결과를 실험 폴더에 쓴다. conda 는 시험 환경에 없으니 끈다.
    got.conda_env = ""
    got.args = [*got.args, "--out", got.exp_dir]
    return got


def run_to_end(spec, **kw):
    launched = P.launch(spec, use_sandbox=False)
    return launched, P.wait(
        launched,
        timeout_sec=kw.pop("timeout_sec", spec.timeout_sec),
        grace_sec=kw.pop("grace_sec", spec.grace_sec),
        poll_sec=0.05,
        **kw,
    )


# --- 정상 종료 ----------------------------------------------------------------


def test_정상_종료(ready):
    spec = run_spec(ready, args=["--epochs", "2"])
    launched, outcome = run_to_end(spec)
    assert outcome.state == "done"
    assert outcome.exit_code == 0
    assert outcome.leftover is False  # 손자도 안 남았다
    assert os.path.exists(os.path.join(spec.exp_dir, "result.csv"))
    assert "가짜 학습이 끝났어요" in open(spec.log_path, encoding="utf-8").read()


def test_종료코드_파일이_남는다(ready):
    """오케스트레이터가 죽어 있는 사이 끝나도 결과를 알아야 한다."""
    spec = run_spec(ready, args=["--epochs", "1"])
    launched, outcome = run_to_end(spec)
    assert P.read_exit_code(spec.exit_code_path) == 0
    assert outcome.exit_code == 0


def test_실패도_종료코드로_남는다(ready):
    spec = run_spec(ready, args=["--epochs", "3", "--crash-at", "2"])
    launched, outcome = run_to_end(spec)
    assert outcome.state == "failed"
    assert outcome.exit_code == 3
    assert P.read_exit_code(spec.exit_code_path) == 3


def test_로그는_덧붙인다(ready):
    """재개할 때 앞 기록이 사라지면 안 된다."""
    spec = run_spec(ready, args=["--epochs", "1"])
    run_to_end(spec)
    first = open(spec.log_path, encoding="utf-8").read()
    run_to_end(spec)
    after = open(spec.log_path, encoding="utf-8").read()
    assert after.startswith(first) and len(after) > len(first)


def test_지난_종료코드는_지우고_시작한다(ready):
    """남아 있으면 복구가 "이미 끝났다" 고 오판한다."""
    spec = run_spec(ready, args=["--epochs", "1"])
    P.write_exit_code(spec.exit_code_path, 99)
    launched, outcome = run_to_end(spec)
    assert outcome.exit_code == 0


# --- 인자가 셸을 거치지 않는다 -------------------------------------------------


def test_인자의_셸_문자가_해석되지_않는다(ready, tmp_path):
    """`args` 에 `; rm -rf` 가 있어도 그냥 인자 문자열이다."""
    canary = tmp_path / "있어야-하는-파일"
    canary.write_text("그대로\n", encoding="utf-8")
    spec = run_spec(ready, args=["--epochs", "1", "--lr", f"; rm -f {canary}"])
    launched, outcome = run_to_end(spec)
    assert outcome.state == "done"
    assert canary.exists()  # 셸이 해석했다면 사라졌다
    assert f"; rm -f {canary}" in open(spec.log_path, encoding="utf-8").read()


def test_인자가_argv_로_그대로_들어간다(ready):
    spec = run_spec(ready, args=["--epochs", "1", "--lr", "`whoami`"])
    argv = P.build_argv(spec, use_sandbox=False)
    assert "`whoami`" in argv  # 한 토큰으로 들어간다
    assert argv[0] == "/bin/sh" and argv[1] == "-c"
    # 셸 스크립트는 `"$@"` 뿐이다 — 인자를 문자열에 끼워 넣지 않는다.
    # 앞에 붙는 건 scope 전용 변수를 지우는 `unset` 한 줄뿐이다.
    # 앞머리는 소켓·버스 주소 변수를 지우는 `unset` 한 줄이다.
    head = argv[2].split('; "$@";', 1)[0]
    assert head.startswith("unset ")
    for name in P.SCOPE_ENV_KEEP:
        assert name in head
    assert "SSH_AUTH_SOCK" in head and "DBUS_SESSION_BUS_ADDRESS" in head
    assert argv[2].count('"$@"') == 1


# --- 타임아웃 ------------------------------------------------------------------


def test_타임아웃이면_정리하고_timeout(ready):
    spec = run_spec(ready, args=["--epochs", "50", "--sleep", "1"])
    launched = P.launch(spec, use_sandbox=False)
    outcome = P.wait(launched, timeout_sec=1, grace_sec=1, poll_sec=0.05)
    assert outcome.state == "timeout"
    assert outcome.killed in ("term", "kill", "gone")
    assert P.read_exit_code(spec.exit_code_path) == 124
    assert P.group_alive(launched.pgid) is False


def test_타임아웃에_손자까지_정리한다(ready):
    """DataLoader worker 가 남으면 GPU 메모리를 계속 잡는다."""
    spec = run_spec(ready, args=["--epochs", "50", "--sleep", "1", "--children", "3"])
    launched = P.launch(spec, use_sandbox=False)
    children_file = os.path.join(spec.output_dir, "children.json")
    for _ in range(100):
        if os.path.exists(children_file):
            break
        time.sleep(0.05)
    children = json.load(open(children_file, encoding="utf-8"))
    assert len(children) == 3
    assert any(P.alive(pid) for pid in children)

    outcome = P.wait(launched, timeout_sec=1, grace_sec=1, poll_sec=0.05)
    assert outcome.state == "timeout"
    assert outcome.leftover is False
    for _ in range(100):
        if not any(P.alive(pid) for pid in children):
            break
        time.sleep(0.05)
    assert not any(P.alive(pid) for pid in children), children


def test_유예를_주고_나서_SIGKILL(ready):
    """유예는 체크포인트를 저장할 틈이다."""
    spec = run_spec(ready, args=["--epochs", "50", "--sleep", "0.2"])
    launched = P.launch(spec, use_sandbox=False)
    started = time.time()
    outcome = P.wait(launched, timeout_sec=1, grace_sec=1, poll_sec=0.05)
    assert outcome.state == "timeout"
    assert time.time() - started >= 1.0


def test_이미_끝난_그룹_정리는_gone(ready):
    spec = run_spec(ready, args=["--epochs", "1"])
    launched, outcome = run_to_end(spec)
    assert P.terminate_group(launched.pgid, grace_sec=1) == "gone"


# --- 중간 사망과 복구 ----------------------------------------------------------


def test_프로세스를_밖에서_죽이면_살아있지_않다(ready):
    spec = run_spec(ready, args=["--epochs", "50", "--sleep", "1"])
    launched = P.launch(spec, use_sandbox=False)
    assert P.alive(launched.pid, launched.starttime) is True
    P.terminate_group(launched.pgid, grace_sec=1)
    launched.proc.wait(timeout=5)
    assert P.alive(launched.pid, launched.starttime) is False


def test_pid_재사용을_starttime_으로_가른다(ready):
    """pid 는 돌고 돈다. 시작 시각까지 봐야 "그 프로세스" 인지 안다."""
    spec = run_spec(ready, args=["--epochs", "1"])
    launched, _ = run_to_end(spec)
    assert launched.starttime is not None
    assert P.alive(os.getpid(), launched.starttime) is False
    assert P.alive(os.getpid(), P.starttime_of(os.getpid())) is True


def test_없는_pid_는_살아있지_않다():
    assert P.alive(None) is False
    assert P.alive(0) is False
    assert P.starttime_of(999999) is None


def test_먼저_아는_쪽이_종료코드를_적는다(tmp_path):
    path = str(tmp_path / "exit_code")
    assert P.write_exit_code(path, 0) is True
    assert P.write_exit_code(path, 124) is False  # 이미 있으면 안 덮는다
    assert P.read_exit_code(path) == 0
    assert P.write_exit_code(path, 124, overwrite=True) is True
    assert P.read_exit_code(path) == 124


def test_종료코드_파일이_깨졌으면_None(tmp_path):
    path = tmp_path / "exit_code"
    path.write_text("알수없음", encoding="utf-8")
    assert P.read_exit_code(str(path)) is None


# --- 환경 ---------------------------------------------------------------------


def test_API_키를_물려주지_않는다(ready, monkeypatch):
    """구독으로만 돌린다. 어떤 경우에도 추가 결제하지 않는다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-새면안되는값")
    spec = run_spec(ready, args=["--epochs", "1"])
    assert "ANTHROPIC_API_KEY" not in P.build_env(spec)


def test_우리_폴더_위치를_물려주지_않는다(ready):
    """`LAB_DATA_DIR` 이 새면 학습 코드가 정책·허가 위치를 알게 된다."""
    env = P.build_env(run_spec(ready, args=["--epochs", "1"]))
    assert not [k for k in env if k.startswith("LAB_")]


def test_로그가_실시간으로_보이게_버퍼를_끈다(ready):
    assert P.build_env(run_spec(ready, args=["--epochs", "1"]))["PYTHONUNBUFFERED"] == "1"


# --- 명령 조립 ----------------------------------------------------------------


def test_py_는_파이썬으로_sh_는_셸로(ready):
    spec = run_spec(ready, args=[])
    assert P.inner_argv(spec)[0].endswith("python") or "python" in P.inner_argv(spec)[0]
    shell_spec = run_spec(ready, args=[])
    shell_spec.entrypoint_abs = os.path.join(ready, "src", "run.sh")
    assert P.inner_argv(shell_spec)[:2] == ["/bin/sh", shell_spec.entrypoint_abs]


def test_conda_환경이_있으면_그_안에서_돌린다(ready):
    spec = run_spec(ready, args=[])
    spec.conda_env = "labremote-test"
    argv = P.inner_argv(spec)
    assert argv[:5] == ["conda", "run", "-n", "labremote-test", "--no-capture-output"]
    assert argv[5] == "python"  # 환경 안의 파이썬을 쓴다


def test_실험_폴더가_프로젝트_밖이면_안_띄운다(ready):
    """검증을 지나왔어도 한 번 더 본다 (두 번째 자물쇠)."""
    spec = run_spec(ready, args=["--epochs", "1"])
    spec.experiment_id = "../../etc"
    with pytest.raises(P.LaunchError):
        P.launch(spec, use_sandbox=False)


def test_실험_ID_에_경로_조각은_못_들어온다(ready):
    """실험 ID 는 폴더 이름이 된다."""
    for bad in ("../../etc", "a/b", ".", "", "EXP 001"):
        with pytest.raises(S.SpecError):
            S.check_experiment_id(bad)
    assert S.check_experiment_id("EXP-001") == "EXP-001"


# --- scope 를 띄우는 환경 ----------------------------------------------------------


def test_탐침은_학습이_받을_환경으로_잰다(ready, monkeypatch):
    """실측 2026-11-05: 탐침은 `os.environ` 으로 **성공**했는데 학습은
    `ENV_KEEP` 화이트리스트만 받아 버스 주소가 없었다. 그래서 학습이
    `Failed to connect to bus` 로 즉사하고 한 바퀴가 날아갔다.
    """
    seen = {}

    def fake_run(argv, **kw):
        seen["env"] = kw.get("env")

        class Done:
            returncode = 0

        return Done()

    monkeypatch.delenv(P.NO_SCOPE_ENV, raising=False)  # 시험 기본값은 scope 끔
    monkeypatch.setattr(P.shutil, "which", lambda name, path=None: "/usr/bin/systemd-run")
    monkeypatch.setattr(P.subprocess, "run", fake_run)

    assert P.scope_available({"PATH": "/usr/bin", "ONLY": "이것만"}) is True
    assert seen["env"] == {"PATH": "/usr/bin", "ONLY": "이것만"}


def test_scope_환경은_학습에_새지_않는다(ready, monkeypatch):
    """`systemd-run` 에게만 주고 셸 첫 줄에서 지운다.

    학습은 AI 가 쓴 코드다. 세션 버스가 보이면 사용자 서비스를 띄우거나
    멈출 수 있고, 그건 파일 경계를 지키는 샌드박스가 못 가린다.
    """
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    # 1) 화이트리스트에는 **없다** — scope 를 안 쓰면 아예 안 물려준다
    spec = run_spec(ready)
    env = P.build_env(spec)
    assert "DBUS_SESSION_BUS_ADDRESS" not in env
    assert "XDG_RUNTIME_DIR" not in env

    # 2) 셸이 첫 줄에서 지운다 — scope 로 들어와도 학습은 못 본다
    argv = P.build_argv(spec, use_sandbox=False)
    head = argv[2].split('; "$@";', 1)[0]
    assert head.startswith("unset ")
    assert "XDG_RUNTIME_DIR" in head and "DBUS_SESSION_BUS_ADDRESS" in head


def test_scope_를_쓸_때만_버스를_물려준다(ready, monkeypatch):
    spec = run_spec(ready)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setattr(P, "scope_available", lambda env=None: False)
    launched = P.launch(spec, use_sandbox=False, cache_dir="")
    P.wait(launched, timeout_sec=30, grace_sec=1, poll_sec=0.05)
    assert launched.scope == ""
    assert "systemd-run" not in launched.argv
