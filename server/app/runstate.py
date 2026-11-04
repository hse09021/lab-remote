"""실험이 지금 돌고 있는가.

프로젝트 **밖**(`server/data/runstate/<이름>.json`)에 둔다. 프로젝트 안에
두면 AI 가 `running: false` 로 바꿔 종료 조건 잠금을 스스로 풀 수 있다.

①단계에서는 사람이 `labremote run-state` 로 바꾼다. ②의 오케스트레이터가
생기면 같은 함수를 호출한다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from . import registry

__all__ = ["RunState", "load", "set_running", "set_idle", "mark_started", "locked"]


@dataclass
class RunState:
    running: bool = False
    experiment_id: str | None = None
    pid: int | None = None
    started_at: str | None = None
    #: 한 번이라도 시작된 실험 ID. "이전 실험 폴더" 판정의 **주 근거**다.
    #: 서버 쪽에만 쌓이므로 AI 가 프로젝트 안에서 지울 수 없다.
    started: list = None  # type: ignore[assignment]
    #: running 이라는데 pid 가 죽어 있다. 상태를 뒤집지는 않고 알리기만 한다.
    stale: bool = False
    #: 파일이 없거나 깨져서 기본값(안 돌고 있음)으로 봤다.
    missing: bool = False


def _alive(pid: int | None) -> bool:
    if not pid:
        return True  # pid 를 안 적었으면 살아 있다고 본다
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 남의 프로세스 — 살아 있다
    except OSError:
        return True
    return True


def load(name: str) -> RunState:
    """파일이 없거나 깨졌으면 "안 돌고 있음".

    이렇게 두는 게 안전하다. `stop` 잠금의 비실행 경로가 `allow` 가 아니라
    `ask` 라서 조용히 열리지 않고, 반대로 "돌고 있음" 으로 가정하면
    오케스트레이터가 생기기 전까지 아무도 종료 조건을 못 고친다.
    """
    try:
        with open(registry.runstate_path(name), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError, registry.InvalidName):
        return RunState(missing=True, started=[])
    if not isinstance(raw, dict):
        return RunState(missing=True, started=[])

    pid = raw.get("pid")
    pid = int(pid) if isinstance(pid, (int, str)) and str(pid).isdigit() else None
    started = raw.get("started")
    state = RunState(
        running=bool(raw.get("running")),
        experiment_id=raw.get("experimentId") or None,
        pid=pid,
        started_at=raw.get("startedAt") or None,
        started=[str(x) for x in started] if isinstance(started, list) else [],
    )
    # 좀비 상태. 훅이 알아서 running 을 뒤집으면 학습이 nohup 으로 떠서 pid 가
    # 바뀐 경우에 잠금이 조용히 풀린다. 그래서 running 은 그대로 두고 표시만 한다.
    if state.running and not _alive(state.pid):
        state.stale = True
    return state


@contextmanager
def locked(name: str):
    """읽고-고쳐-쓰기를 감싼다.

    `started` 목록은 읽어서 더하고 다시 쓴다. ②에서는 오케스트레이터와 CLI 가
    같이 건드릴 수 있어서, 잠그지 않으면 **한쪽의 추가가 사라진다**(실험 ID 가
    started 에서 빠지면 "이전 실험" 잠금이 풀린다). 쓰기 자체는
    `registry.write_json` 이 원자적이라 반쯤 쓰인 파일은 안 생긴다.
    """
    folder = os.path.dirname(registry.runstate_path(name))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f".{registry.valid_name(name)}.lock")
    with open(path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _write(name: str, data: dict, *, keep_started: bool = True) -> None:
    if keep_started:
        data.setdefault("started", load(name).started or [])
    data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    registry.write_json(registry.runstate_path(name), data)


def mark_started(name: str, experiment_id: str) -> list[str]:
    """실험 ID 를 "한 번이라도 시작됨" 목록에 넣는다 (중복 없이, 순서 유지)."""
    with locked(name):
        return _mark_started(name, experiment_id)


def _mark_started(name: str, experiment_id: str) -> list[str]:
    state = load(name)
    started = list(state.started or [])
    if experiment_id and experiment_id not in started:
        started.append(experiment_id)
    _write(
        name,
        {
            "running": state.running,
            "experimentId": state.experiment_id,
            "pid": state.pid,
            "startedAt": state.started_at,
            "started": started,
            "source": "cli",
        },
        keep_started=False,
    )
    return started


def set_running(name: str, experiment_id: str, pid: int | None = None) -> None:
    """실험을 시작한다. **started 목록에 영구히 남는다.**

    끝났는지 실패했는지와 상관없이, 한 번 시작된 폴더는 다시 손대면 안 된다
    (spec: 실패한 실험 폴더도 남기고 새 폴더에서 재실행).
    """
    with locked(name):
        _set_running(name, experiment_id, pid)


def _set_running(name: str, experiment_id: str, pid: int | None) -> None:
    started = list(load(name).started or [])
    if experiment_id and experiment_id not in started:
        started.append(experiment_id)
    _write(
        name,
        {
            "running": True,
            "experimentId": experiment_id,
            "pid": pid,
            "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "started": started,
            "source": "cli",
        },
        keep_started=False,
    )


def set_idle(name: str) -> None:
    """실행을 멈춘다. started 목록은 지우지 않는다."""
    with locked(name):
        _write(
            name, {"running": False, "experimentId": None, "pid": None, "source": "cli"}
        )
