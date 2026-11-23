"""자동 시작 — systemd 사용자 유닛 하나 (PLAN 1.1 · 6장 9단계).

    ~/.config/systemd/user/labremote-session.service
      └ tmux -L labremote "labremote"
          └ labremote serve   (127.0.0.1 · nice 19 · ionice idle — serve가 스스로 낮춰요)

- 이 모듈은 유닛 **내용을 만들고 읽기만** 한다. 켜고 끄는 건 `autostart.py`
  (사람이 `labremote autostart install|uninstall`로 부를 때만).
- code tunnel은 여기서 띄우지 않는다 — 사람이 `code tunnel service install`
  (VS Code 공식 명령)로 켜고, lab.remote는 상태만 읽는다 (2026-11-23 결정).
- tmux 안에 두는 까닭: `tmux -L labremote attach -t labremote`로 서버 출력을
  바로 볼 수 있다. serve가 끝나면 창이 닫히고 tmux가 끝나서 systemd가 다시 띄운다.
- **`ANTHROPIC_*`를 넣지 않고, 사용자 매니저 환경에 있어도 지운다.** 키가 섞이면
  구독이 아니라 종량제로 과금된다.
- 학습 실행 · 터미널은 각자 transient 사용자 서비스(`process.service_prefix`)라
  이 유닛을 다시 켜도 살아남는다. 에이전트 세션은 서버와 같이 끝나고, 다시 뜨면
  세션 목록에서 이어 간다.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from .. import paths, registry

__all__ = [
    "UNITS",
    "NAME",
    "TMUX_SOCKET",
    "unit_dir",
    "unit_path",
    "render",
    "unit_path_env",
    "write",
    "status",
]

NAME = "labremote-session"
TMUX_SOCKET = "labremote"
DEFAULT_PORT = 8000

#: 유닛 이름 → 설명
UNITS = {NAME: "lab.remote 서버 (tmux labremote)"}

_TEMPLATE = """[Unit]
Description={description}
After=network-online.target
Wants=network-online.target

[Service]
# tmux가 스스로 뒤로 빠진다 (fork)
Type=forking
WorkingDirectory={server_dir}
Environment=PATH={path}
Environment=LAB_DATA_DIR={data}
# 서버가 자기가 자동 시작 안에서 도는지 알게 ("세션 다시 켜기" · "자동 시작 끄기")
Environment=LAB_SESSION_UNIT={name}
# 키가 섞이면 구독이 아니라 종량제로 과금돼요 — 사용자 매니저 환경에 있어도 지워요
UnsetEnvironment=ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN TMUX TMUX_PANE
ExecStart={tmux} -L {socket} new-session -d -s {socket} -n serve {command}
ExecStop={tmux} -L {socket} kill-server
Restart=always
RestartSec=10
TimeoutStopSec=30
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def unit_dir() -> str:
    """`~/.config/systemd/user`. `XDG_CONFIG_HOME`을 따른다."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "systemd", "user")


def unit_path(name: str = NAME) -> str:
    if name not in UNITS:
        raise ValueError(f"모르는 유닛이에요: {name!r} · 아는 것: {', '.join(UNITS)}")
    return os.path.join(unit_dir(), f"{name}.service")


def log_path() -> str:
    return os.path.join(registry.data_dir(), "logs", "session.log")


#: 유닛의 `PATH`. **지금 셸의 PATH를 베끼지 않는다** — 거기엔 VS Code 서버
#: 경로처럼 나중에 없어질 것이 섞인다. 파이썬 환경 · `~/.local/bin`(`claude`) · 표준 폴더만.
_BASE_PATH = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")


def unit_path_env(python: str) -> str:
    out = [os.path.dirname(paths.real(python))]
    out.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    out += list(_BASE_PATH)
    return ":".join(dict.fromkeys(p for p in out if p))


def _server_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # app/
    return paths.real(os.path.dirname(here))


def _tmux() -> str:
    from .. import runs

    return runs.tmux_bin()


def _plain(value: str, what: str) -> str:
    """유닛 줄에 그대로 넣을 수 있는 값인지 — 공백 · 따옴표 · 줄바꿈 · %는 거절한다."""
    if not value or any(c in value for c in ' \t\n"\'\\%$'):
        raise ValueError(f"{what} 경로에 공백이나 특수 문자가 있어 유닛에 넣을 수 없어요: {value!r}")
    return value


def render(*, python: str = "", port: int = DEFAULT_PORT) -> str:
    """유닛 파일 내용. **쓰지는 않는다.**"""
    py = _plain(paths.real(python or sys.executable), "파이썬")
    tmux = _plain(_tmux() or "/usr/bin/tmux", "tmux")
    port = int(port)
    if not 1024 <= port <= 65535:
        raise ValueError("포트는 1024~65535 사이로 정해 주세요.")
    # tmux에는 셸 명령 한 줄로 넘긴다 (systemd는 큰따옴표 하나를 인자 하나로 본다)
    command = '"' + shlex.join(["exec", py, "-m", "app.cli", "serve", "--port", str(port)]) + '"'
    return _TEMPLATE.format(
        description=UNITS[NAME],
        name=NAME,
        server_dir=_plain(_server_dir(), "서버 폴더"),
        path=unit_path_env(py),
        data=_plain(registry.data_dir(), "데이터 폴더"),
        tmux=tmux,
        socket=TMUX_SOCKET,
        command=command,
        log=_plain(log_path(), "로그"),
    )


def write(*, python: str = "", port: int = DEFAULT_PORT) -> dict:
    """유닛 파일을 쓴다. `{"path", "changed"}`. **켜지 않는다.**"""
    body = render(python=python, port=port)
    target = unit_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.makedirs(os.path.dirname(log_path()), exist_ok=True)
    try:
        with open(target, encoding="utf-8") as fh:
            before = fh.read()
    except OSError:
        before = ""
    if before != body:
        tmp = f"{target}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, target)
    return {"path": target, "changed": before != body}


def port_of_unit() -> int | None:
    """설치된 유닛이 여는 포트 (없으면 None)."""
    try:
        with open(unit_path(), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    parts = text.split("--port", 1)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].split()[0].strip('"'))
    except (ValueError, IndexError):
        return None


def _systemctl() -> str:
    return shutil.which("systemctl") or ""


def _user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def linger() -> bool | None:
    user = _user()
    if not user or not shutil.which("loginctl"):
        return None
    try:
        done = subprocess.run(["loginctl", "show-user", user, "--property=Linger"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        # 로그인 세션이 없으면 show-user가 실패한다 — linger 파일로 본다
        return os.path.exists(f"/var/lib/systemd/linger/{user}")
    return done.stdout.strip().split("=", 1)[-1].lower() == "yes"


def status() -> dict:
    """우리 유닛만 본다 (`systemctl --user` 전체가 degraded 인 건 무관하다)."""
    out: dict = {"systemctl": _systemctl(), "linger": None, "units": {}}
    if not out["systemctl"]:
        return out
    out["linger"] = linger()
    row: dict = {"file": os.path.exists(unit_path()), "port": port_of_unit()}
    for key, flag in (("enabled", "is-enabled"), ("active", "is-active")):
        try:
            done = subprocess.run([out["systemctl"], "--user", flag, f"{NAME}.service"], capture_output=True, text=True, timeout=10)
            row[key] = (done.stdout or done.stderr or "").strip()
        except (OSError, subprocess.SubprocessError) as exc:
            row[key] = f"못 읽었어요: {exc}"
    try:
        done = subprocess.run(
            [out["systemctl"], "--user", "show", f"{NAME}.service", "--property=NRestarts", "--value"],
            capture_output=True, text=True, timeout=10,
        )
        row["restarts"] = int(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip().isdigit() else None
    except (OSError, subprocess.SubprocessError):
        row["restarts"] = None
    out["units"][NAME] = row
    return out


def inside() -> bool:
    """이 서버가 자동 시작 유닛 안에서 도는가 (유닛이 넣어 준 환경 변수로 본다)."""
    return os.environ.get("LAB_SESSION_UNIT") == NAME
