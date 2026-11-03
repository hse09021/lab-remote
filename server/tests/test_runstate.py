"""실행 상태 시험. 종료 조건 잠금이 여기에 걸려 있다."""

import os

from app import registry, runstate


def test_파일이_없으면_안_돌고_있음():
    state = runstate.load("hook-sandbox")
    assert state.running is False and state.missing is True


def test_깨진_파일도_안_돌고_있음():
    path = registry.runstate_path("hook-sandbox")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("깨진 JSON")
    assert runstate.load("hook-sandbox").missing is True


def test_켜고_끄기():
    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    state = runstate.load("hook-sandbox")
    assert state.running and state.experiment_id == "EXP-007" and state.stale is False

    runstate.set_idle("hook-sandbox")
    assert runstate.load("hook-sandbox").running is False


def test_pid_가_죽어도_running_은_유지하고_표시만():
    """훅이 알아서 뒤집으면 nohup 으로 pid 가 바뀐 경우에 잠금이 조용히 풀린다."""
    dead = 2 ** 22  # 존재하지 않을 pid
    runstate.set_running("hook-sandbox", "EXP-007", pid=dead)
    state = runstate.load("hook-sandbox")
    assert state.running is True
    assert state.stale is True


def test_pid_가_없으면_살아_있다고_본다():
    runstate.set_running("hook-sandbox", "EXP-007", pid=None)
    assert runstate.load("hook-sandbox").stale is False


def test_상태_파일은_프로젝트_밖에_있다(project_root):
    from app import paths

    path = paths.real(registry.runstate_path("hook-sandbox"))
    assert paths.rel_or_none(project_root, path) is None
