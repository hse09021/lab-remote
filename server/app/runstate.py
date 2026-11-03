"""실험이 지금 돌고 있는가.

프로젝트 **밖**(`server/data/runstate/<이름>.json`)에 둔다. 프로젝트 안에
두면 AI 가 `running: false` 로 바꿔 종료 조건 잠금을 스스로 풀 수 있다.

①단계에서는 사람이 `labremote run-state` 로 바꾼다. ②의 오케스트레이터가
생기면 같은 함수를 호출한다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from . import registry

__all__ = ["RunState", "load", "set_running", "set_idle"]


@dataclass
class RunState:
    running: bool = False
    experiment_id: str | None = None
    pid: int | None = None
    started_at: str | None = None
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
        return RunState(missing=True)
    if not isinstance(raw, dict):
        return RunState(missing=True)

    pid = raw.get("pid")
    pid = int(pid) if isinstance(pid, (int, str)) and str(pid).isdigit() else None
    state = RunState(
        running=bool(raw.get("running")),
        experiment_id=raw.get("experimentId") or None,
        pid=pid,
        started_at=raw.get("startedAt") or None,
    )
    # 좀비 상태. 훅이 알아서 running 을 뒤집으면 학습이 nohup 으로 떠서 pid 가
    # 바뀐 경우에 잠금이 조용히 풀린다. 그래서 running 은 그대로 두고 표시만 한다.
    if state.running and not _alive(state.pid):
        state.stale = True
    return state


def _write(name: str, data: dict) -> None:
    data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    registry.write_json(registry.runstate_path(name), data)


def set_running(name: str, experiment_id: str, pid: int | None = None) -> None:
    _write(
        name,
        {
            "running": True,
            "experimentId": experiment_id,
            "pid": pid,
            "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "cli",
        },
    )


def set_idle(name: str) -> None:
    _write(name, {"running": False, "experimentId": None, "pid": None, "source": "cli"})
