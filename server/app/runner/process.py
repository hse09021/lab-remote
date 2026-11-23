"""실행 프로세스의 기본 부품 — cgroup 분리, 생존 판정, 그룹 종료, 종료코드 기록.

v3 의 실행(`labremote run`)은 `systemd-run --user --scope` + tmux + 로그
파일로 돈다(docs/v3/PLAN.md 4.1). 실행을 띄우는 쪽은 2단계에서 그 모양으로
새로 만들고, 여기에는 그대로 다시 쓸 부품만 남겼다.

### 왜 `systemd-run --user --scope` 인가

> ⚠ **`setsid`(`start_new_session=True`) 는 cgroup 을 바꾸지 않습니다**
> (실측 2026-11-05). 세션 ID 는 떨어지지만 cgroup 은 그대로라 서버 유닛의
> cgroup 안에 남고, 유닛을 재시작할 때 같이 죽을 수 있습니다. scope 는
> `/user.slice/…/app.slice/<이름>.scope` 로 **아예 다른 자리**라 서버와
> 무관하게 살아남습니다.

### 종료코드 파일

서버가 죽어 있는 사이 학습이 끝날 수 있다. 그래서 셸이 끝나면서 종료코드를
파일로 남긴다. 먼저 아는 쪽이 적고, 이미 있으면 덮지 않는다.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time

__all__ = [
    "POLL_SEC",
    "ENV_STRIP",
    "ENV_STRIP_PREFIXES",
    "NO_SCOPE_ENV",
    "LaunchError",
    "scrub_env",
    "scope_name",
    "scope_available",
    "scope_prefix",
    "starttime_of",
    "alive",
    "group_alive",
    "read_exit_code",
    "write_exit_code",
    "terminate_group",
]

POLL_SEC = 0.1

#: 실행에 **절대** 물려주지 않는 변수.
#:
#: `ANTHROPIC_*` 가 섞이면 구독이 아니라 종량제로 과금된다. 에이전트·키
#: 소켓 주소(`SSH_AUTH_SOCK`·`GPG_AGENT_INFO`·`DBUS_*`)는 실행되는 코드에게
#: "여기 붙어라" 를 알려 주는 셈이라 지운다.
ENV_STRIP = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "SSH_AUTH_SOCK", "SSH_AGENT_PID", "GPG_AGENT_INFO", "GPG_TTY",
    "DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS",
)

#: 이 접두사로 시작하는 건 전부 지운다 (`DBUS_STARTER_ADDRESS` 등).
ENV_STRIP_PREFIXES = ("DBUS_",)

#: `1` 이면 scope 를 쓰지 않는다. 시험과 scope 가 말썽인 환경에서 쓴다.
NO_SCOPE_ENV = "LAB_NO_SCOPE"


class LaunchError(RuntimeError):
    """실행을 띄우지 못했을 때."""


def scrub_env(env: dict[str, str]) -> dict[str, str]:
    """`ENV_STRIP`·`ENV_STRIP_PREFIXES` 를 뺀 새 dict."""
    return {
        k: v for k, v in env.items()
        if k not in ENV_STRIP and not any(k.startswith(p) for p in ENV_STRIP_PREFIXES)
    }


def scope_name(*parts: str) -> str:
    """scope 유닛 이름. systemd 가 받는 글자만 남긴다.

    `scope_name("myproj", "EXP-007")` → `labremote-run-myproj-EXP-007`
    """
    def clean(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "-", str(text or ""))[:48] or "x"

    return "labremote-run-" + "-".join(clean(p) for p in parts if p)


def scope_available(env: dict | None = None) -> bool:
    """`systemd-run --user --scope` 를 **실제로 띄워 보고** 판정한다.

    설정만 보고 믿지 않는다. user systemd·dbus 가 없는 환경(컨테이너·cron)
    에서는 안 된다.

    🔑 **실행이 받을 환경으로 잰다.** 서버의 환경으로 재면 탐침은 성공하고
    실제 실행은 버스를 못 찾아 즉사할 수 있다(실측 2026-11-05).
    """
    source = os.environ if env is None else env
    if source.get(NO_SCOPE_ENV) == "1" or os.environ.get(NO_SCOPE_ENV) == "1":
        return False
    binary = shutil.which("systemd-run", path=source.get("PATH") or os.defpath)
    if not binary:
        return False
    try:
        done = subprocess.run(
            [binary, "--user", "--scope", "--quiet", "--", "/bin/true"],
            capture_output=True, text=True, timeout=20,
            env=None if env is None else dict(env),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def scope_prefix(unit: str, description: str = "") -> list[str]:
    """명령을 **자기 cgroup** 에 담는 접두사.

    같은 이름의 scope 가 이미 돌고 있으면 `systemd-run` 이 거절한다 — 같은
    실행을 두 번 띄우는 사고를 막는다.
    """
    out = ["systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}"]
    if description:
        out.append(f"--description={description}")
    # scope 가 끝나면 cgroup 도 같이 사라진다
    return out + ["--collect", "--"]


def starttime_of(pid: int) -> int | None:
    """`/proc/<pid>/stat` 의 starttime (22번째 칸).

    pid 는 재사용된다. "그 pid 가 **그** 프로세스인가" 를 가르려면 시작
    시각까지 봐야 한다.
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
    """그룹에 **아직 뭐가 남아 있나.** 손자까지 정리됐는지 보는 데 쓴다.

    ⚠ 좀비도 "남아 있음" 으로 보인다. 우리가 그 프로세스의 부모라면 `wait`
    로 거둬야 이 값이 거짓이 된다.
    """
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
    """**먼저 아는 쪽이 적는다.** 이미 있으면 덮지 않는다."""
    if not overwrite and os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(int(code)))
    os.replace(tmp, path)
    return True


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
