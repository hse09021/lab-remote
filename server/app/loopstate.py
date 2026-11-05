"""`state/State.yaml` 읽기 + `state/Current.yaml` 쓰기 + runstate 동시 갱신.

①의 숙제였다. 실측에서 Claude 가 *"EXP-002 가 이미 시작된 실험이면 막혀야
하는데"* 라고 혼동했다 — **잠금의 이유를 Claude 가 설명하지 못했다.**
runstate 는 서버 쪽(`server/data/runstate/`)이라 프로젝트에서 안 보이고,
`State.yaml` 은 AI 가 쓰는 파일이라 근거가 못 된다.

그래서 `state/Current.yaml` 을 둔다.

* **오케스트레이터만 쓴다.** 2단계에서 훅의 `selfProtect` 목록에 한 줄을
  더하면 AI 의 수정이 무조건 DENY 가 된다 (판정 코드는 한 줄도 안 고친다).
* `State.yaml` 은 **그대로 AI 소유**다 — PDF 의 Update Order 가 안 깨진다.
* `runstate` 와 **같은 함수에서 같이** 쓴다. 따로 쓰면 어긋나고, 어긋난 걸
  실측에서 이미 봤다 (loop 0 vs EXP-002 running).

`pyyaml` 을 쓴다 — 이 모듈은 **훅 경로가 아니다.**
"""

from __future__ import annotations

import os
from datetime import datetime

from . import loop_layout as L
from . import paths, registry, runstate

__all__ = [
    "current_path",
    "read_state",
    "read_current",
    "write_current",
    "set_running",
    "set_reviewing",
    "set_idle",
    "consistency",
]

#: 파일 맨 위에 붙이는 머리말. 사람과 AI 가 같이 읽는다.
HEADER = """\
# state/Current.yaml — lab.remote 오케스트레이터가 써요.
# 고치면 Hooks 가 막아요. "지금 어느 실험이 도는지" 의 유일한 근거예요.
"""


def current_path(root: str) -> str:
    return os.path.join(root, L.LOOP_LAYOUT["current"])


def state_path(root: str) -> str:
    return os.path.join(root, L.LOOP_LAYOUT["state"])


def _yaml():
    import yaml  # 지연 import — 훅 경로에서 이 모듈을 건드리지 않게

    return yaml


def _read_yaml(path: str) -> dict:
    """없거나 깨졌으면 빈 dict. **던지지 않는다** — AI 가 쓴 파일이라
    언제든 반쯤 쓰여 있거나 YAML 이 아닐 수 있다."""
    yaml = _yaml()
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_state(root: str) -> dict:
    """AI 가 쓴 `State.yaml`."""
    return _read_yaml(state_path(root))


def read_current(root: str) -> dict:
    """오케스트레이터가 쓴 `Current.yaml`."""
    return _read_yaml(current_path(root))


def _locked_now(state: runstate.RunState, started: list[str]) -> list[str]:
    """지금 잠겨 있는 것을 **사람 말로** 적는다. Claude 가 이유를 읽을 수 있게."""
    out: list[str] = []
    if state.running:
        config = L.LOOP_LAYOUT["config"]
        evaluation = L.LOOP_LAYOUT["evaluation"]
        out.append(f"{config} · {evaluation}  (실험이 도는 중이라 잠겨 있어요)")
    previous = [e for e in started if e != state.experiment_id]
    if previous:
        exp_dir = L.experiments_dir()
        shown = ", ".join(f"{exp_dir}/{e}/**" for e in previous[:6])
        if len(previous) > 6:
            shown += f" 외 {len(previous) - 6}건"
        out.append(f"{shown}   (이전 실험)")
    out.append(
        f"{L.LOOP_LAYOUT['current']} · .claude/** · {L.LOOP_LAYOUT['approval_log']}"
        "  (시스템이 쓰는 파일)"
    )
    return out


def _write_text(path: str, text: str) -> None:
    """원자적 텍스트 쓰기. 반쯤 쓰인 YAML 을 AI 가 읽으면 혼동한다."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _render(data: dict) -> str:
    yaml = _yaml()
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200)
    return HEADER + body


def write_current(name: str, root: str | None = None, *, loop_no: int | None = None) -> str:
    """`runstate` 를 그대로 베껴 `Current.yaml` 에 쓴다. 쓴 경로를 돌려준다.

    **runstate 가 단일 출처다.** 이 파일은 거울이라 손으로 고칠 값이 없다.
    """
    target_root = root or registry.root_of(name)
    if not target_root:
        raise ValueError(f"프로젝트 루트를 알 수 없어요: {name!r}")
    # 🔑 상대 경로를 거절한다. `Current.yaml` 은 "지금 어느 실험이 도는지" 의
    # **유일한 근거**인데, 상대 경로가 들어오면 지금 폴더 밑에 조용히 하나 더
    # 만들어 놓고 프로젝트 쪽은 낡은 채로 남는다 (실제로 `server/hook-sandbox/
    # state/Current.yaml` 이 그렇게 생겼다 — 손으로 부른 자리였다).
    if not os.path.isabs(target_root):
        raise ValueError(
            f"프로젝트 루트는 절대 경로여야 해요: {target_root!r} · "
            f"registry.root_of({name!r}) 의 값을 넘겨 주세요"
        )
    state = runstate.load(name)
    started = list(state.started or [])
    data = {
        "current_experiment": state.experiment_id,
        "running": bool(state.running),
        "started_experiments": started,
        "locked_now": _locked_now(state, started),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_by": "orchestrator",
    }
    if loop_no is not None:
        data["loop_no"] = int(loop_no)
    if state.stale:
        data["warning"] = "running 이라고 적혀 있는데 그 프로세스가 안 보여요."
    path = current_path(paths.real(target_root))
    _write_text(path, _render(data))
    return path


def set_running(
    name: str,
    experiment_id: str,
    *,
    pid: int | None = None,
    root: str | None = None,
    loop_no: int | None = None,
) -> str:
    """실험을 시작한다 — runstate 와 `Current.yaml` 을 **같이** 쓴다."""
    runstate.set_running(name, experiment_id, pid=pid)
    return write_current(name, root, loop_no=loop_no)


def set_reviewing(
    name: str,
    experiment_id: str,
    *,
    root: str | None = None,
    loop_no: int | None = None,
) -> str:
    """학습이 끝나고 **분석이 도는 중** — `runstate` 와 거울을 같이 쓴다."""
    runstate.set_reviewing(name, experiment_id)
    return write_current(name, root, loop_no=loop_no)


def set_idle(name: str, *, root: str | None = None, loop_no: int | None = None) -> str:
    runstate.set_idle(name)
    return write_current(name, root, loop_no=loop_no)


def consistency(name: str, root: str | None = None) -> dict:
    """runstate · Current.yaml · State.yaml 이 같은 말을 하는가.

    `doctor` 가 쓴다. **고치지는 않는다** — 어긋남 자체가 알릴 거리다.
    """
    target_root = root or registry.root_of(name) or ""
    state = runstate.load(name)
    current = read_current(target_root) if target_root else {}
    journal = read_state(target_root) if target_root else {}

    problems: list[str] = []
    if not target_root:
        problems.append(f"{name} 의 프로젝트 루트를 못 찾았어요")
    elif not os.path.exists(current_path(target_root)):
        problems.append(f"{L.LOOP_LAYOUT['current']} 이 없어요 (오케스트레이터가 아직 안 썼어요)")
    else:
        if bool(current.get("running")) != bool(state.running):
            problems.append(
                f"running 이 달라요: runstate={state.running} · "
                f"Current.yaml={current.get('running')}"
            )
        if (current.get("current_experiment") or None) != state.experiment_id:
            problems.append(
                f"현재 실험이 달라요: runstate={state.experiment_id} · "
                f"Current.yaml={current.get('current_experiment')}"
            )
    # State.yaml 은 AI 가 쓴다. 어긋나도 막지 않고 보고만 한다.
    ai_exp = journal.get("current_experiment") or journal.get("experiment_id")
    if ai_exp and state.experiment_id and str(ai_exp) != str(state.experiment_id):
        problems.append(
            f"State.yaml 이 가리키는 실험이 달라요: {ai_exp} · 시스템은 {state.experiment_id}"
        )
    if state.stale:
        problems.append("running 인데 그 프로세스가 안 보여요 (좀비 상태)")

    return {
        "ok": not problems,
        "problems": problems,
        "runstate": {
            "running": state.running,
            "experimentId": state.experiment_id,
            "started": list(state.started or []),
            "stale": state.stale,
        },
        "current": current,
        "stateYaml": {"currentExperiment": ai_exp} if ai_exp else {},
    }
