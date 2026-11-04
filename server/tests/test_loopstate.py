"""`state/Current.yaml` — AI 가 못 고치는 "현재 실험" 표시.

①의 숙제였다. 실측에서 Claude 가 *"EXP-002 가 이미 시작된 실험이면 막혀야
하는데"* 라고 혼동했다 — 잠금의 이유를 설명하지 못했다. runstate 는 서버
쪽이라 프로젝트에서 안 보이고, `State.yaml` 은 AI 가 쓰는 파일이라 근거가
못 된다.

**runstate 가 단일 출처이고 이 파일은 거울이다.** 둘을 따로 쓰면 어긋나고,
어긋난 걸 실측에서 이미 봤다 (loop 0 vs EXP-002 running).
"""

import os

import pytest
import yaml

from app import loop_layout as L
from app import loopstate, runstate


@pytest.fixture()
def registered(isolated_data, project_root):
    from app import registry

    os.makedirs(os.path.join(project_root, "state"), exist_ok=True)
    registry.register(project_root, "hook-sandbox")
    return project_root


def read(root):
    with open(loopstate.current_path(root), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_경로가_레이아웃에서_온다(registered):
    assert L.LOOP_LAYOUT["current"] == "state/Current.yaml"
    assert loopstate.current_path(registered).endswith("state/Current.yaml")


def test_State_yaml_과_다른_파일이다(registered):
    assert loopstate.current_path(registered) != loopstate.state_path(registered)


def test_머리말에_고치지_말라고_적는다(registered):
    loopstate.write_current("hook-sandbox", registered)
    body = open(loopstate.current_path(registered), encoding="utf-8").read()
    assert body.startswith("# state/Current.yaml")
    assert "Hooks 가 막아요" in body


def test_실험을_시작하면_runstate_와_같이_쓴다(registered):
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered, loop_no=3)
    data = read(registered)
    assert data["current_experiment"] == "EXP-003"
    assert data["running"] is True
    assert data["loop_no"] == 3
    state = runstate.load("hook-sandbox")
    assert state.running is True and state.experiment_id == "EXP-003"


def test_멈추면_둘_다_바뀐다(registered):
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered)
    loopstate.set_idle("hook-sandbox", root=registered)
    data = read(registered)
    assert data["running"] is False
    assert data["current_experiment"] is None
    assert runstate.load("hook-sandbox").running is False


def test_시작된_실험_목록이_쌓인다(registered):
    for exp in ("EXP-001", "EXP-002", "EXP-003"):
        loopstate.set_running("hook-sandbox", exp, pid=os.getpid(), root=registered)
    assert read(registered)["started_experiments"] == ["EXP-001", "EXP-002", "EXP-003"]


def test_잠긴_이유를_사람_말로_적는다(registered):
    """Claude 가 읽고 "왜 막혔는지" 를 설명할 수 있어야 한다."""
    loopstate.set_running("hook-sandbox", "EXP-002", pid=os.getpid(), root=registered)
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered)
    locked = "\n".join(read(registered)["locked_now"])
    assert "docs/Evaluation.md" in locked
    assert "실험이 도는 중이라 잠겨 있어요" in locked
    assert "experiments/EXP-002/**" in locked  # 이전 실험
    assert "experiments/EXP-003/**" not in locked  # 지금 도는 건 이전 실험이 아니다
    assert "state/Current.yaml" in locked


def test_멈춰_있으면_종료_조건을_잠긴_것으로_안_적는다(registered):
    loopstate.write_current("hook-sandbox", registered)
    locked = "\n".join(read(registered)["locked_now"])
    assert "실험이 도는 중이라" not in locked


def test_좀비_상태를_적는다(registered):
    """running 이라는데 그 pid 가 없다."""
    runstate.set_running("hook-sandbox", "EXP-003", pid=999999)
    loopstate.write_current("hook-sandbox", registered)
    assert "안 보여요" in read(registered)["warning"]


def test_루트를_모르면_거절한다(isolated_data):
    with pytest.raises(ValueError):
        loopstate.write_current("등록안된프로젝트")


def test_등록된_이름이면_루트를_찾아_쓴다(registered):
    loopstate.write_current("hook-sandbox")
    assert os.path.exists(loopstate.current_path(registered))


# --- State.yaml 읽기 ---------------------------------------------------------


def test_State_yaml_이_없어도_빈_dict(registered):
    assert loopstate.read_state(registered) == {}


def test_깨진_State_yaml_도_던지지_않는다(registered):
    with open(loopstate.state_path(registered), "w", encoding="utf-8") as fh:
        fh.write("이건: [YAML 이\n  아니에요: {")
    assert loopstate.read_state(registered) == {}


# --- 정합 점검 ---------------------------------------------------------------


def test_정합이_맞으면_ok(registered):
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered)
    result = loopstate.consistency("hook-sandbox", registered)
    assert result["ok"] is True
    assert result["problems"] == []


def test_Current_yaml_이_없으면_알린다(registered):
    result = loopstate.consistency("hook-sandbox", registered)
    assert result["ok"] is False
    assert any("없어요" in p for p in result["problems"])


def test_어긋나면_알린다(registered):
    """실측에서 본 그 상황 — runstate 는 running, 거울은 옛 값."""
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered)
    runstate.set_running("hook-sandbox", "EXP-004", pid=os.getpid())  # 거울을 안 고쳤다
    result = loopstate.consistency("hook-sandbox", registered)
    assert result["ok"] is False
    assert any("현재 실험이 달라요" in p for p in result["problems"])


def test_State_yaml_이_다른_실험을_가리키면_보고한다(registered):
    loopstate.set_running("hook-sandbox", "EXP-003", pid=os.getpid(), root=registered)
    with open(loopstate.state_path(registered), "w", encoding="utf-8") as fh:
        yaml.safe_dump({"current_experiment": "EXP-002"}, fh, allow_unicode=True)
    result = loopstate.consistency("hook-sandbox", registered)
    assert result["ok"] is False
    assert any("State.yaml" in p for p in result["problems"])
    # AI 가 쓰는 파일이라 막지는 않는다 — 보고만 한다.
    assert result["stateYaml"]["currentExperiment"] == "EXP-002"
