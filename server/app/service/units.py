"""⚙️ systemd 사용자 유닛 **렌더**. 활성화는 사람이 합니다.

## 왜 렌더만 하나

`systemctl --user enable` 과 `loginctl enable-linger` 는 **사람의 세션
설정**입니다. 지금까지의 규칙(규칙 0 — 사람의 설정 파일은 코드가 쓰지
않는다)과 같습니다. 그리고 `enable --now` 는 **루프를 실제로 띄웁니다** —
그건 사람이 "이제 돌려라" 라고 말하는 순간이어야 합니다.

그래서 이 모듈은

1. `~/.config/systemd/user/*.service` 를 **씁니다** (우리가 만든 파일입니다)
2. 사람이 돌릴 명령을 **찍어 줍니다** (`sudo` 없이 되는 것들입니다)

8단계에서 실제 재부팅까지 확인합니다.

## 유닛 둘

| | 하는 일 |
|---|---|
| `labremote-orchestrator` | 루프 (설계 → 실행 → 분석) |
| `labremote-monitor` | 5초마다 GPU·호스트·로그를 읽어 스냅샷 |

## 못박아 둔 것

- **`ANTHROPIC_API_KEY` 를 넣지 않습니다.** 키가 섞이면 구독이 아니라 종량제
  과금입니다(`agent/launch.ENV_STRIP` 가 한 번 더 지웁니다).
- `KillMode=mixed` — 학습은 `start_new_session=True` 로 떼어 놔서 유닛을
  멈춰도 **안 죽습니다.** 몇 시간 돌던 학습을 재시작으로 잃지 않으려는
  것입니다.
- `Restart=always` + `RestartSec=10` — 죽으면 다시 뜨고, 복구가 이어받습니다.
- `DISABLE_AUTOUPDATER=1` — 도구 이름이 바뀌면 방어에 틈이 생깁니다(S5b).
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

#: 유닛 이름 → (설명, 돌릴 모듈)
UNITS = {
    "labremote-orchestrator": ("lab.remote 오케스트레이터", "app.orchestrator"),
    "labremote-monitor": ("lab.remote 모니터", "app.monitor.daemon"),
}

_TEMPLATE = """[Unit]
Description={description}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={server_dir}
Environment=PATH={path}
Environment=LAB_PROJECTS_DIR={projects}
Environment=LAB_DATA_DIR={data}
# 🔑 Claude Code 가 저절로 올라가면 도구 이름이 바뀌어 방어에 틈이 생겨요 (S5b).
Environment=DISABLE_AUTOUPDATER=1
Environment=DISABLE_UPDATES=1
# ⚠ ANTHROPIC_API_KEY 는 **일부러 넣지 않아요** — 키가 섞이면 구독이 아니라
# 종량제로 과금돼요. 런처가 한 번 더 지워요 (agent/launch.ENV_STRIP).
ExecStart={python} -m {module}
Restart=always
RestartSec=10
# 학습은 start_new_session 으로 떼어 놔서 유닛을 멈춰도 안 죽어요.
# 몇 시간 돌던 학습을 재시작으로 잃지 않으려는 거예요.
KillMode=mixed
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
#: 파이썬의 환경(`conda run` 없이도 돌게), `~/.local/bin`(`claude`),
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
        projects=registry.projects_root(),
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
    os.makedirs(os.path.dirname(log_path("labremote-monitor")), exist_ok=True)
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
    """우리 유닛 **둘만** 본다.

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
