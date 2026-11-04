"""학습 샌드박스 (`bwrap`).

학습 스크립트는 **AI 가 쓴 코드**다. 훅은 도구 호출만 보므로 `train.py` 안의
`open("~/.claude/settings.json","w")` 는 훅을 한 번도 거치지 않는다. 막는
수단은 샌드박스뿐이다.

0단계 실측 15번에서 `bwrap` 으로 확정했다. 여기서는 **실제로 띄워서** 그
격리가 지금도 유효한지 본다 — 커널·AppArmor 설정이 바뀌면 조용히 뚫리므로
설정만 보고 믿지 않는다.

⚠ 시험은 **임시 폴더를 가려서** 잰다. 진짜 `~/.claude` 를 대상으로 쓰기를
시도하면, 샌드박스가 꺼져 있을 때 그게 그대로 실행된다.
"""

import json
import os
import shutil

import pytest

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
def secrets(tmp_path):
    """가려야 할 "비밀" 을 흉내 낸 폴더. 진짜 `~/.claude` 는 건드리지 않는다."""
    folder = tmp_path / "가짜비밀"
    folder.mkdir()
    (folder / "grant_key").write_text("비밀-서명-키\n", encoding="utf-8")
    return folder


def spec_for(root, *args):
    got = load(root, {"entrypoint": "src/train.py", "args": ["--epochs", "1", *args]})
    got.conda_env = ""
    got.args = [*got.args, "--out", got.exp_dir]
    return got


def run_sandboxed(spec, hide):
    launched = P.launch(spec, use_sandbox=True, hide=[str(h) for h in hide])
    outcome = P.wait(launched, timeout_sec=60, grace_sec=2, poll_sec=0.05)
    probes = {}
    probe_file = os.path.join(spec.output_dir, "probes.json")
    if os.path.exists(probe_file):
        probes = {p["path"]: p for p in json.load(open(probe_file, encoding="utf-8"))}
    return outcome, probes, open(spec.log_path, encoding="utf-8").read()


# --- 명령 조립 (bwrap 없이도 잰다) ---------------------------------------------


def test_쓸_수_있는_곳은_프로젝트_하나뿐(ready):
    argv = SB.command(["/bin/true"], project_root=ready, bwrap="/usr/bin/bwrap")
    assert argv[:4] == ["/usr/bin/bwrap", "--ro-bind", "/", "/"]
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert binds == [ready]  # 쓰기 가능한 bind 는 프로젝트뿐


def test_GPU_장치와_proc_는_보인다(ready):
    argv = SB.command(["/bin/true"], project_root=ready, bwrap="/usr/bin/bwrap")
    assert ["--dev-bind", "/dev", "/dev"] == argv[4:7]
    assert "--proc" in argv


def test_기본으로_가리는_것(ready):
    hidden = SB.hidden_paths(ready)
    assert any(h.endswith("/server") for h in hidden), hidden  # 정책·허가·lab.db
    assert any(".claude" in h for h in hidden), hidden
    assert ready not in hidden  # 프로젝트 자신은 안 가린다


def test_다른_실험_프로젝트도_가린다(ready, tmp_path):
    from app import registry

    other = tmp_path / "projects" / "다른프로젝트"
    other.mkdir(parents=True)
    registry.register(str(other), "other-proj")
    assert os.path.realpath(str(other)) in SB.hidden_paths(ready)


def test_die_with_parent_는_기본으로_끈다(ready):
    """켜면 오케스트레이터를 재시작할 때마다 몇 시간 돌던 학습이 같이 죽는다."""
    argv = SB.command(["/bin/true"], project_root=ready, bwrap="/usr/bin/bwrap")
    assert "--die-with-parent" not in argv
    argv = SB.command(["/bin/true"], project_root=ready, bwrap="/usr/bin/bwrap", die_with_parent=True)
    assert "--die-with-parent" in argv


def test_bwrap_이_없으면_던진다(ready, monkeypatch):
    """**학습을 띄우지 않는다.** 샌드박스 없이 도는 쪽으로 넘어가지 않는다."""
    monkeypatch.setenv("LAB_BWRAP", "/없는경로/bwrap")
    with pytest.raises(SB.SandboxError) as err:
        SB.command(["/bin/true"], project_root=ready)
    assert "bwrap 을 찾을 수 없어요" in str(err.value)


def test_없는_경로는_가리지_않는다(ready):
    """`--tmpfs` 는 없는 경로에 실패한다."""
    argv = SB.command(
        ["/bin/true"], project_root=ready, hide=["/없는폴더"], bwrap="/usr/bin/bwrap"
    )
    assert "/없는폴더" not in argv


# --- 실제로 띄워서 (bwrap 필요) -------------------------------------------------


@needs_bwrap
def test_available_은_띄워_보고_판정한다():
    assert STATE["ok"] is True
    assert STATE["bwrap"]


@needs_bwrap
def test_가려진_비밀은_읽히지_않는다(ready, secrets):
    spec = spec_for(ready, "--probe-read", str(secrets / "grant_key"))
    outcome, probes, log = run_sandboxed(spec, [secrets])
    assert outcome.state == "done"
    probe = probes[str(secrets / "grant_key")]
    assert probe["result"] == "BLOCKED", probe
    assert "비밀-서명-키" not in log


@needs_bwrap
def test_가려진_곳에_쓴_내용은_호스트에_안_남는다(ready, secrets):
    """⚠ 프로그램에는 **성공으로 보인다** (`--tmpfs` 가 버린다).
    그래서 `spec.py` 가 폴더 밖 경로를 미리 경고한다."""
    target = secrets / "몰래쓴파일"
    spec = spec_for(ready, "--probe-write", str(target))
    outcome, probes, _ = run_sandboxed(spec, [secrets])
    assert outcome.state == "done"
    assert probes[str(target)]["result"] == "MADE"  # 안에서는 성공으로 보인다
    assert not target.exists()  # 호스트에는 안 남는다


@needs_bwrap
def test_프로젝트_안_쓰기는_된다(ready, secrets):
    """가두되 일은 되게 해야 한다."""
    target = os.path.join(ready, "src", "쓴파일.txt")
    spec = spec_for(ready, "--probe-write", target)
    outcome, probes, _ = run_sandboxed(spec, [secrets])
    assert probes[target]["result"] == "MADE"
    assert os.path.exists(target)  # 실제로 남는다
    assert os.path.exists(os.path.join(spec.exp_dir, "result.csv"))


@needs_bwrap
def test_tmp_에_쓴_것은_버려진다(ready, secrets, tmp_path):
    """`/tmp` 는 샌드박스 안에서 **버려지는 tmpfs** 다. 쓰기는 성공으로 보이고
    호스트에는 안 남는다 — 막히는 것과 다르다."""
    target = tmp_path / "밖에쓴파일"  # pytest 임시 폴더는 /tmp 아래다
    assert str(target).startswith("/tmp/")
    spec = spec_for(ready, "--probe-write", str(target))
    outcome, probes, _ = run_sandboxed(spec, [secrets])
    assert probes[str(target)]["result"] == "MADE"
    assert not target.exists()  # 호스트에는 안 남는다


@needs_bwrap
def test_프로젝트_밖_쓰기는_막힌다(ready, secrets):
    """`/tmp` 밖은 루트 전체가 읽기 전용이라 **쓰기 자체가 실패**한다."""
    target = os.path.join(os.path.expanduser("~"), "labremote-sbx-probe.tmp")
    try:
        spec = spec_for(ready, "--probe-write", target)
        outcome, probes, _ = run_sandboxed(spec, [secrets])
        assert probes[target]["result"] == "BLOCKED", probes
        assert not os.path.exists(target)
    finally:
        # 샌드박스가 뚫렸다면 흔적을 남기지 않는다 (그래도 위 assert 가 알려 준다)
        try:
            os.remove(target)
        except OSError:
            pass


@needs_bwrap
def test_샌드박스_안에서도_타임아웃과_손자_정리가_된다(ready, secrets):
    spec = spec_for(ready, "--sleep", "1", "--children", "2")
    spec.args = [a if a != "1" else "50" for a in spec.args]  # --epochs 50
    launched = P.launch(spec, use_sandbox=True, hide=[str(secrets)])
    outcome = P.wait(launched, timeout_sec=2, grace_sec=1, poll_sec=0.05)
    assert outcome.state == "timeout"
    assert outcome.leftover is False
    assert P.group_alive(launched.pgid) is False


@needs_bwrap
def test_샌드박스_안에서도_종료코드가_남는다(ready, secrets):
    spec = spec_for(ready, "--crash-at", "1")
    outcome, _, _ = run_sandboxed(spec, [secrets])
    assert outcome.state == "failed"
    assert P.read_exit_code(spec.exit_code_path) == 3


@needs_bwrap
def test_기본_가림_목록으로도_돈다(ready):
    """시험용 목록이 아니라 **실제 목록**으로 한 번 돌려 본다.
    쓰기는 시도하지 않는다 — 읽기만 막히는지 본다."""
    probe = os.path.join(SB.hidden_paths(ready)[0], "아무파일")
    spec = spec_for(ready, "--probe-read", probe)
    launched = P.launch(spec, use_sandbox=True)
    outcome = P.wait(launched, timeout_sec=60, grace_sec=2, poll_sec=0.05)
    assert outcome.state == "done"
    probes = json.load(open(os.path.join(spec.output_dir, "probes.json"), encoding="utf-8"))
    assert probes[0]["result"] == "BLOCKED"
