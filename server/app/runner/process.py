"""학습 프로세스를 띄우고, 끝까지 지켜보고, 정리한다.

### 왜 `subprocess` + 프로세스 그룹인가

| 안 | 평가 |
|---|---|
| **`Popen(..., start_new_session=True)`** | **채택.** 의존성 0, 시험하기 쉽다. `setsid` 효과라 **오케스트레이터가 재시작돼도 학습이 안 죽는다.** 종료는 `killpg` 라 DataLoader worker 같은 **손자까지** 정리된다 |
| `nohup` | ✕ 프로세스 그룹 제어가 없어 손자가 남는다 |
| `systemd-run --user` | ✕ 0단계 실측에서 경로 보호 속성이 전부 무효였다 |
| tmux | ②에서는 안 쓴다. pid 추적이 흐려진다 |

### `output/exit_code` 는 "무슨 일이 있었나" 의 기록이다

오케스트레이터가 죽어 있는 사이 학습이 끝날 수 있다. 그래서 셸이 끝나면서
종료코드를 파일로 남긴다. 반대로 타임아웃처럼 **오케스트레이터가 먼저 아는**
경우에는 오케스트레이터가 쓴다. 먼저 아는 쪽이 적고, 이미 있으면 덮지 않는다.

### 인자는 셸을 거치지 않는다

`run.json` 의 `args` 는 `"$@"` 로 넘긴다. `;`·`&&`·백틱이 들어 있어도 그냥
인자 문자열이다 (`runner/spec.py` 가 배열만 받고, 여기서 셸 해석을 안 한다).
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from .. import paths
from . import condaenv
from . import cache as cache_mod
from . import sandbox as sandbox_mod
from .spec import RunSpec

__all__ = [
    "Launched",
    "Outcome",
    "LaunchError",
    "inner_argv",
    "build_argv",
    "inject_tokens",
    "launch",
    "wait",
    "terminate_group",
    "alive",
    "starttime_of",
    "read_exit_code",
    "write_exit_code",
]

#: 종료를 기다리며 다시 보는 간격
POLL_SEC = 0.1

#: 환경에서 **반드시 지우는** 것. 구독으로만 돌린다 (추가 결제 금지).
ENV_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

#: 학습에 물려주는 기본 환경. 나머지는 지운다 — 오케스트레이터의 환경이
#: 그대로 새면 `LAB_*` 로 우리 폴더 위치까지 알려 주는 셈이다.
#:
#: 캐시 변수(`HF_HOME`·`TMPDIR` …)는 **일부러 빼 뒀다.** 물려받으면
#: `~/.cache/huggingface` 를 가리키는데 샌드박스에서 그건 쓸 수 없는 곳이고,
#: `TMPDIR` 은 tmpfs(메모리)로 간다. `runner/cache.py` 가 값을 정한다.
ENV_KEEP = (
    "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TZ", "TERM",
    "PATH", "CUDA_VISIBLE_DEVICES", "CUDA_HOME", "NVIDIA_VISIBLE_DEVICES",
    "CONDA_EXE", "CONDA_PREFIX", "CONDA_PYTHON_EXE", "MAMBA_EXE", "MAMBA_ROOT_PREFIX",
)


class LaunchError(RuntimeError):
    """띄우지 못했을 때. `blocked` 로 두고 알린다."""


@dataclass
class Launched:
    pid: int
    pgid: int
    argv: list[str]
    log_path: str
    exit_code_path: str
    started_at: float
    starttime: int | None = None
    proc: subprocess.Popen | None = field(default=None, repr=False)


@dataclass
class Outcome:
    #: done | timeout | failed
    state: str
    exit_code: int | None = None
    #: term | kill | None — 어떻게 정리했나
    killed: str | None = None
    seconds: float = 0.0
    leftover: bool = False  # 그룹에 아직 뭐가 남아 있나 (손자 정리 확인용)


def inner_argv(spec: RunSpec) -> list[str]:
    """`conda run` 과 인터프리터까지 붙인 **실제 명령**.

    `.py` 는 파이썬으로, `.sh` 는 `/bin/sh` 로, 나머지는 실행 파일로 본다.
    conda 환경이 적혀 있으면 그 안에서 돌린다 — `--no-capture-output` 이
    없으면 `conda run` 이 출력을 모아 뒀다가 한꺼번에 내놓아서 로그 꼬리가
    실시간으로 안 보인다.
    """
    target = spec.entrypoint_abs
    if target.endswith(".py"):
        interpreter = "python" if spec.conda_env else sys.executable
        inner = [interpreter, target]
    elif target.endswith((".sh", ".bash")):
        inner = ["/bin/sh", target]
    else:
        inner = [target]
    if spec.conda_env:
        # 🔑 우리 코드가 도는 환경(`labremote`)·`base`·시스템 파이썬에서는
        # 돌리지 않는다. 학습 스크립트는 AI 가 쓴 코드이고, 그 환경에 쓰기가
        # 되면 `.pth` 한 줄이 훅 프로세스 안에서 돈다 (`runner/condaenv.py`).
        condaenv.require(spec.conda_env)
        inner = ["conda", "run", "-n", spec.conda_env, "--no-capture-output", *inner]
    return [*inner, *spec.args]


def build_argv(spec: RunSpec, *, use_sandbox: bool = True, **sandbox_kw) -> list[str]:
    """실제로 `Popen` 에 넘길 argv. 셸은 종료코드를 남기는 용도로만 쓴다."""
    script = '"$@"; printf %s "$?" > ' + shlex.quote(spec.exit_code_path)
    wrapped = ["/bin/sh", "-c", script, "labremote-train", *inner_argv(spec)]
    if not use_sandbox:
        return wrapped
    sandbox_kw.setdefault("extra_ro", spec.data_paths)
    return sandbox_mod.command(wrapped, project_root=spec.root, **sandbox_kw)


def inject_tokens(policy) -> dict[str, str]:
    """정책이 허락한 토큰만 `~/.config/labremote/config.toml` 에서 가져온다.

    **기본은 아무것도 주입하지 않는다.** 정책의 `runner.injectTokens` 에 이름을
    적어야 그 이름만 들어간다.

    ⚠ 학습 코드는 AI 가 쓴 코드고, 환경 변수는 `os.environ` 한 줄이면 보인다.
    샌드박스는 파일을 가려 주지만 환경 변수는 못 가린다. 그래서 **읽기 전용·
    최소 권한 토큰만** 쓴다 (`docs/operations.md`).
    """
    from .. import config as config_mod

    allowed = []
    if policy is not None:
        allowed = (getattr(policy, "runner", {}) or {}).get("injectTokens") or []
    wanted = {str(name).strip() for name in allowed if str(name).strip()}
    if not wanted:
        return {}
    have = config_mod.tokens()
    out = {name: have[name] for name in sorted(wanted) if name in have}
    # 끼워 넣는 변수는 토큰으로도 못 들어온다.
    from .spec import ENV_MANAGED, ENV_NEVER

    return {k: v for k, v in out.items() if k not in ENV_NEVER and k not in ENV_MANAGED}


def build_env(spec: RunSpec, *, cache_dir: str = "", policy=None) -> dict[str, str]:
    """학습이 받을 환경 변수.

    순서가 의미를 가진다 — **캐시 값이 맨 마지막이라 이긴다.** `run.json` 이
    같은 이름을 넣지 못하게 `spec.py` 가 이미 막지만(`ENV_MANAGED`), 여기서도
    뒤에 둬서 두 겹으로 둔다.
    """
    out = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    out.setdefault("PYTHONUNBUFFERED", "1")  # 로그 꼬리가 실시간으로 보이게
    out.update(inject_tokens(policy))  # 정책이 허락한 이름만
    out.update(spec.env)  # spec 이 이미 envAllow 로 걸렀다
    if cache_dir:
        out.update(cache_mod.env_for(cache_dir))
    for name in ENV_STRIP:
        out.pop(name, None)
    return out


def starttime_of(pid: int) -> int | None:
    """`/proc/<pid>/stat` 의 starttime (22번째 칸).

    pid 는 재사용된다. 복구가 "그 pid 가 **그** 프로세스인가" 를 가르려면
    시작 시각까지 봐야 한다.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None
    # 프로그램 이름에 공백·괄호가 있을 수 있어서 마지막 ')' 뒤부터 센다.
    try:
        rest = raw[raw.rindex(")") + 2 :].split()
        return int(rest[19])
    except (ValueError, IndexError):
        return None


def alive(pid: int | None, starttime: int | None = None) -> bool:
    """그 프로세스가 아직 살아 있는가. pid 재사용을 starttime 으로 가른다."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # 남의 프로세스 — 살아 있다
    except OSError:
        return False
    if starttime is None:
        return True
    now = starttime_of(pid)
    return now is None or now == starttime


def group_alive(pgid: int | None) -> bool:
    """그룹에 **아직 뭐가 남아 있나.** 손자까지 정리됐는지 보는 데 쓴다."""
    if not pgid:
        return False
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def read_exit_code(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def write_exit_code(path: str, code: int, *, overwrite: bool = False) -> bool:
    """**먼저 아는 쪽이 적는다.** 이미 있으면 덮지 않는다.

    학습이 스스로 끝냈으면 셸이 이미 적었다. 타임아웃처럼 우리가 먼저 아는
    경우에만 우리가 적는다.
    """
    if not overwrite and os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(int(code)))
    os.replace(tmp, path)
    return True


def launch(
    spec: RunSpec,
    *,
    use_sandbox: bool = True,
    append_log: bool = True,
    cache_dir: str | None = None,
    policy=None,
    **sandbox_kw,
) -> Launched:
    """학습을 띄운다. **기다리지 않는다** (`wait` 가 기다린다).

    공용 캐시 폴더를 검사하고 만들어서 샌드박스에 쓰기로 물려준다.
    `cache_dir=""` 로 끄면 캐시 없이 돈다(시험용) — 그러면 모델을 매번
    다시 내려받고 `TMPDIR` 이 tmpfs 로 간다.
    """
    # `is_inside` 는 **이미 해소된** 경로를 받는다. 그냥 넘기면
    # `<루트>/experiments/../../etc` 가 문자열로는 루트 안처럼 보인다.
    exp_dir_real = paths.real(spec.exp_dir)
    if not paths.is_inside(paths.real(spec.root), exp_dir_real):
        raise LaunchError(f"실험 폴더가 프로젝트 밖이에요: {exp_dir_real}")
    os.makedirs(spec.output_dir, exist_ok=True)
    # 지난 실행의 종료코드가 남아 있으면 복구가 헷갈린다.
    try:
        os.remove(spec.exit_code_path)
    except OSError:
        pass

    cache = cache_mod.cache_dir(policy) if cache_dir is None else cache_dir
    if cache:
        # 겹치면 `CacheError` 다 — **학습을 띄우지 않는다.**
        cache = cache_mod.ensure(cache, spec.root)["dir"]
        if use_sandbox:
            sandbox_kw.setdefault("cache_dir", cache)

    argv = build_argv(spec, use_sandbox=use_sandbox, **sandbox_kw)
    env = build_env(spec, cache_dir=cache, policy=policy)
    mode = "ab" if append_log else "wb"
    try:
        log_fh = open(spec.log_path, mode)
    except OSError as exc:
        raise LaunchError(f"로그 파일을 열 수 없어요: {exc}") from None
    try:
        proc = subprocess.Popen(
            argv,
            cwd=spec.root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            # 자기만의 세션·프로세스 그룹. 오케스트레이터가 죽어도 안 죽고,
            # 끝낼 때는 그룹째로 정리해 손자까지 잡는다.
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        log_fh.close()
        raise LaunchError(f"학습을 띄우지 못했어요: {exc}") from None
    finally:
        try:
            log_fh.close()
        except OSError:
            pass

    return Launched(
        pid=proc.pid,
        pgid=proc.pid,  # start_new_session 이라 세션 리더 = pgid
        argv=argv,
        log_path=spec.log_path,
        exit_code_path=spec.exit_code_path,
        started_at=time.time(),
        starttime=starttime_of(proc.pid),
        proc=proc,
    )


def terminate_group(pgid: int, *, grace_sec: int = 120, poll_sec: float = POLL_SEC) -> str:
    """`SIGTERM` -> 유예 -> `SIGKILL`. 어떻게 정리했는지 돌려준다.

    유예는 **체크포인트를 저장할 틈**이다. 그룹째로 보내서 DataLoader worker
    같은 손자까지 받는다.
    """
    if not group_alive(pgid):
        return "gone"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return "gone"
    deadline = time.time() + max(0.0, float(grace_sec))
    while time.time() < deadline:
        if not group_alive(pgid):
            return "term"
        time.sleep(poll_sec)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return "term"
    # SIGKILL 은 거절할 수 없지만, 커널이 거두는 데 잠깐 걸린다.
    for _ in range(50):
        if not group_alive(pgid):
            break
        time.sleep(poll_sec)
    return "kill"


def wait(
    launched: Launched,
    *,
    timeout_sec: int,
    grace_sec: int = 120,
    on_tick=None,
    tick_sec: float = 10.0,
    poll_sec: float = POLL_SEC,
) -> Outcome:
    """끝날 때까지 기다린다. 넘기면 정리하고 `timeout` 으로 돌려준다.

    `on_tick` 은 `tick_sec` 마다 불린다 — 오케스트레이터가 심장 소리를 올리고
    로그 꼬리를 읽는 자리다.
    """
    proc = launched.proc
    if proc is None:
        raise LaunchError("기다릴 프로세스가 없어요 (복구 경로는 alive 를 쓰세요)")
    deadline = launched.started_at + max(1, int(timeout_sec))
    next_tick = time.time() + tick_sec
    while True:
        code = proc.poll()
        if code is not None:
            seconds = time.time() - launched.started_at
            # 셸이 적은 게 있으면 그걸 믿는다 (`conda run` 이 코드를 바꿀 수 있다).
            from_file = read_exit_code(launched.exit_code_path)
            final = from_file if from_file is not None else code
            write_exit_code(launched.exit_code_path, final)
            return Outcome(
                state="done" if final == 0 else "failed",
                exit_code=final,
                seconds=seconds,
                leftover=group_alive(launched.pgid),
            )
        now = time.time()
        if now >= deadline:
            how = terminate_group(launched.pgid, grace_sec=grace_sec, poll_sec=poll_sec)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL 뒤라 드물다
                pass
            # 타임아웃은 **우리가 먼저 안다.** 셸이 적을 틈이 없으니 우리가 적는다.
            write_exit_code(launched.exit_code_path, 124)
            return Outcome(
                state="timeout",
                exit_code=read_exit_code(launched.exit_code_path),
                killed=how,
                seconds=now - launched.started_at,
                leftover=group_alive(launched.pgid),
            )
        if on_tick and now >= next_tick:
            next_tick = now + tick_sec
            try:
                on_tick(launched)
            except Exception:
                pass  # 심장 소리가 학습을 멈추게 하면 안 된다
        time.sleep(poll_sec)
