"""⚙️ 자동 시작 — systemd 사용자 유닛 **렌더**. 활성화는 사람이 합니다.

v3 가 바꾸는 시스템 설정은 이 유닛 하나와 `loginctl enable-linger` 뿐이고,
그것도 **자동 시작을 켤 때만**입니다 (docs/v3/PLAN.md 1장).

    ~/.config/systemd/user/labremote-session.service

## 왜 렌더만 하나

`systemctl --user enable` 과 `loginctl enable-linger` 는 사람의 세션
설정입니다. 이 모듈은 유닛 파일을 쓰고, 사람이 돌릴 명령을 찍어 줍니다.

## 못박아 둔 것

- **`ANTHROPIC_API_KEY` 를 넣지 않습니다.** 키가 섞이면 구독이 아니라
  종량제 과금입니다.
- **가볍게** — `Nice=19`, `IOSchedulingClass=idle` (PLAN 1.3).
- **`KillMode=process`** — 학습은 `systemd-run --user --scope` + tmux 로
  자기 cgroup 에서 돕니다. `mixed` 면 서버를 재시작할 때 cgroup 에 남은 것에
  SIGKILL 이 가서, 혹시 서버 cgroup 에 남은 자식이 있으면 같이 죽습니다.
- `Restart=always` + `RestartSec=10`.
"""

from __future__ import annotations

import os
import shutil
import sys

from .. import paths, registry

__all__ = [
    "UNITS",
    "unit_dir",
    "unit_path",
    "render",
    "unit_path_env",
    "install",
    "status",
    "enable_commands",
]

#: 유닛 이름 → (설명, 돌릴 명령 인자)
UNITS = {
    "labremote-session": ("lab.remote 서버", "app.cli serve"),
}

_TEMPLATE = """[Unit]
Description={description}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={server_dir}
Environment=PATH={path}
Environment=LAB_DATA_DIR={data}
# ⚠ ANTHROPIC_API_KEY 는 **일부러 넣지 않아요** — 키가 섞이면 구독이 아니라
# 종량제로 과금돼요.
ExecStart={python} -m {module}
Restart=always
RestartSec=10
# 가볍게 (PLAN 1.3)
Nice=19
IOSchedulingClass=idle
# 학습은 `systemd-run --user --scope` + tmux 로 자기 cgroup 에서 돌아요.
# `process` 는 서버 프로세스만 끝내고 남은 건 건드리지 않아요.
KillMode=process
TimeoutStopSec=60
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def unit_dir() -> str:
    """`~/.config/systemd/user`. `XDG_CONFIG_HOME` 을 따른다."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "systemd", "user")


def unit_path(name: str) -> str:
    if name not in UNITS:
        raise ValueError(f"모르는 유닛이에요: {name!r} · 아는 것: {', '.join(UNITS)}")
    return os.path.join(unit_dir(), f"{name}.service")


def log_path(name: str) -> str:
    return os.path.join(registry.data_dir(), "logs", f"{name.split('-', 1)[-1]}.log")


#: 유닛의 `PATH`. **지금 셸의 PATH 를 베끼지 않는다** — 거기엔 VS Code 서버
#: 경로처럼 **나중에 없어질 것**이 섞인다. 필요한 것만 고정으로 둔다:
#: 파이썬의 환경, `~/.local/bin`(`claude`),
#: 그리고 표준 폴더.
_BASE_PATH = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")


def unit_path_env(python: str) -> str:
    """유닛에 넣을 `PATH`. 중복을 지우고 순서를 고정한다."""
    out = [os.path.dirname(paths.real(python))]
    out.append(os.path.join(os.path.expanduser("~"), ".local", "bin"))
    out += list(_BASE_PATH)
    return ":".join(dict.fromkeys(p for p in out if p))


def render(name: str, *, python: str = "") -> str:
    """유닛 파일 내용. **쓰지는 않는다.**"""
    description, module = UNITS[name]
    server = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server = os.path.dirname(server) if os.path.basename(server) == "app" else server
    return _TEMPLATE.format(
        description=description,
        server_dir=paths.real(server),
        path=unit_path_env(python or sys.executable),
        data=registry.data_dir(),
        python=paths.real(python or sys.executable),
        module=module,
        log=log_path(name),
    )


def install(*, python: str = "") -> dict:
    """유닛 파일을 쓴다. **활성화하지 않는다.**

    `{"written": [경로], "changed": [경로], "dir": …}`.
    """
    folder = unit_dir()
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.dirname(log_path("labremote-session")), exist_ok=True)
    written, changed = [], []
    for name in sorted(UNITS):
        body = render(name, python=python)
        target = unit_path(name)
        before = ""
        try:
            with open(target, encoding="utf-8") as fh:
                before = fh.read()
        except OSError:
            before = ""
        written.append(target)
        if before != body:
            tmp = f"{target}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, target)
            changed.append(target)
    return {"written": written, "changed": changed, "dir": folder}


def _systemctl() -> str:
    return shutil.which("systemctl") or ""


def status() -> dict:
    """우리 유닛만 본다.

    `systemctl --user` 전체가 `degraded` 인 것은 snap·xdg-portal 탓이라
    무관하다 — 그래서 전체 상태를 보지 않는다.
    """
    import subprocess

    out = {"systemctl": _systemctl(), "linger": None, "units": {}}
    if not out["systemctl"]:
        return out

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if user and shutil.which("loginctl"):
        try:
            done = subprocess.run(
                ["loginctl", "show-user", user, "--property=Linger"],
                capture_output=True, text=True, timeout=10,
            )
            if done.returncode == 0:
                out["linger"] = done.stdout.strip().split("=", 1)[-1].lower() == "yes"
        except (OSError, subprocess.SubprocessError):
            out["linger"] = None

    for name in sorted(UNITS):
        row = {"file": os.path.exists(unit_path(name))}
        for key, flag in (("enabled", "is-enabled"), ("active", "is-active")):
            try:
                done = subprocess.run(
                    [out["systemctl"], "--user", flag, f"{name}.service"],
                    capture_output=True, text=True, timeout=10,
                )
                row[key] = (done.stdout or done.stderr or "").strip()
            except (OSError, subprocess.SubprocessError) as exc:
                row[key] = f"못 읽었어요: {exc}"
        out["units"][name] = row
    return out


def enable_commands() -> list[str]:
    """사람이 돌릴 명령. **`sudo` 가 필요한 것은 없다.**"""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "<사용자>"
    return [
        f"loginctl enable-linger {user}",
        "systemctl --user daemon-reload",
        "systemctl --user enable --now " + " ".join(sorted(UNITS)),
    ]
