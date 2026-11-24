"""System 화면 — 서버·터널·자동 시작·GPU 상태와 "lab.remote가 바꾼 것".

GPU는 `nvidia-smi`를 부르므로 짧게 캐시한다(여러 탭이 동시에 폴링해도 한 번).
화면을 볼 때만 불린다 — 서버가 혼자 폴링하지 않는다(PLAN 1.3).
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time

from . import paths, projects, registry
from .monitor import gpu as gpu_mod
from .monitor import host as host_mod
from .runner import condaenv
from .service import units

__all__ = ["server_info", "gpu_summary", "host_summary", "autostart", "tunnel", "changes", "overview"]

STARTED_AT = time.time()
GPU_CACHE_SEC = 5.0

_gpu_lock = threading.Lock()
_gpu_cache: tuple[float, dict] | None = None
_cpu_sample: tuple[int, int] | None = None


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("lab-remote-server")
    except Exception:  # 설치 안 된 채 돌릴 때
        return ""


def server_info(*, port: int | None = None) -> dict:
    try:
        nice = os.getpriority(os.PRIO_PROCESS, 0)
    except OSError:
        nice = None
    return {
        "version": _version(),
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "port": port,
        "startedAt": STARTED_AT,
        "uptimeSec": round(time.time() - STARTED_AT),
        "nice": nice,
        "python": sys.executable,
        "dataDir": registry.data_dir(),
        "hostname": socket.gethostname(),
    }


def gpu_summary(*, probe=None) -> dict:
    """GPU 한 덩어리 + 헤더 한 줄(`label`). 실패도 정상 반환."""
    global _gpu_cache
    with _gpu_lock:
        now = time.monotonic()
        if probe is None and _gpu_cache and now - _gpu_cache[0] < GPU_CACHE_SEC:
            return _gpu_cache[1]
        raw = (probe or gpu_mod.probe)()
        devices = raw.get("devices") or []
        label = "GPU 조회 불가"
        if raw.get("available") and devices:
            d = devices[0]
            util = d.get("utilPct")
            used, total = d.get("memUsedMb"), d.get("memTotalMb")
            if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total:
                mem = f"{used / 1024:.1f}/{total / 1024:.0f}G"
            else:
                mem = "?"
            label = f"GPU {round(util) if isinstance(util, (int, float)) else '?'}% · {mem}"
        out = {
            "available": bool(raw.get("available")),
            "reason": raw.get("reason") or "",
            "label": label,
            "devices": devices,
            "driver": raw.get("driver") or {},
        }
        if probe is None:
            _gpu_cache = (now, out)
        return out


def host_summary() -> dict:
    """CPU는 직전 호출과의 차분이다 — 첫 호출은 `None`."""
    global _cpu_sample
    raw = host_mod.probe(registry.data_dir(), before=_cpu_sample)
    _cpu_sample = raw.pop("cpuSample", None)
    return raw


def autostart() -> dict:
    """사용자 서비스 + linger. 켜고 끄기는 `labremote autostart`(CLI) · "자동 시작 끄기…"(화면)."""
    from .service import autostart as auto

    st = units.status()
    unit = (st.get("units") or {}).get(units.NAME) or {}
    rec = auto.record()
    return {
        "unit": f"{units.NAME}.service",
        "unitFile": units.unit_path(),
        "installed": bool(unit.get("file")),
        "enabled": unit.get("enabled") or "",
        "active": unit.get("active") or "",
        "restarts": unit.get("restarts"),
        "port": unit.get("port"),
        "linger": st.get("linger"),
        "lingerBefore": rec.get("lingerBefore"),
        "systemctl": bool(st.get("systemctl")),
        # 이 서버가 그 유닛 안에서 도는가 — 아니면 "세션 다시 켜기"가 이 서버를 다시 켜지 않는다
        "inside": units.inside(),
        "tmux": f"{units._tmux() or 'tmux'} -L {units.TMUX_SOCKET} attach -t {units.TMUX_SOCKET}",
        "installCommand": "labremote autostart install",
    }


def tunnel() -> dict:
    """code tunnel — 읽기만 (켜고 끄기는 사람이 `code tunnel service install|uninstall`)."""
    from . import remote
    from . import tunnel as tunnel_mod

    return {**tunnel_mod.status(), **remote.info()}


def _conda_env_row() -> dict:
    found = [p for p in condaenv.candidates("labremote") if os.path.isdir(p)]
    return {
        "what": "conda 환경 labremote",
        "where": found[0] if found else "",
        "present": bool(found),
        "when": "설치할 때",
        "undo": "conda env remove -n labremote",
    }


def changes() -> list[dict]:
    """"lab.remote가 바꾼 것" — PLAN 1장 목록 그대로. 있는지만 본다."""
    rows = [_conda_env_row()]
    unit_file = units.unit_path()
    from .service import autostart as auto

    before = auto.record().get("lingerBefore")
    rows.append(
        {
            "what": "사용자 서비스 labremote-session",
            "where": unit_file,
            "present": os.path.exists(unit_file),
            "when": "labremote autostart install",
            "undo": "labremote autostart uninstall",
        }
    )
    linger = units.status().get("linger")
    rows.append(
        {
            "what": "linger (로그아웃해도 서비스 유지)",
            "where": f"loginctl · 사용자 {os.environ.get('USER') or ''}",
            "present": linger,
            "when": "labremote autostart install" + (" (원래 no)" if before is False else " (원래 yes)" if before is True else ""),
            "undo": "uninstall하면 원래대로 돌려요 (code tunnel 서비스가 있으면 그대로 둬요)" if before is False else "lab.remote가 켠 게 아니라 그대로 둬요" if before is True else "loginctl disable-linger",
        }
    )
    for root, name in sorted(registry.load().items(), key=lambda kv: kv[1]):
        folder = os.path.join(root, projects.LABREMOTE_DIR)
        present = os.path.isdir(folder) and not os.path.islink(folder)
        rows.append(
            {
                "what": f"{name}의 .labremote/",
                "where": projects.display_path(paths.real(folder)),
                "present": present,
                "when": "프로젝트를 등록할 때",
                "undo": "Projects › 설정 › 등록 해제",
                "project": name,
            }
        )
    return rows


def overview(*, port: int | None = None) -> dict:
    return {
        "server": server_info(port=port),
        "tunnel": tunnel(),
        "autostart": autostart(),
        "gpu": gpu_summary(),
        "host": host_summary(),
        "changes": changes(),
        "clock": _clock(),
        "uninstall": uninstall_steps(),
    }


def uninstall_steps() -> list[str]:
    """System 화면 "지우기" — 이 컴퓨터의 실제 경로로."""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data = registry.data_dir()
    out = ["labremote autostart uninstall   # 자동 시작을 켰다면", "conda env remove -n labremote", f"rm -rf {repo}"]
    if not paths.is_inside(paths.real(repo), paths.real(data)):
        out.append(f"rm -rf {data}   # 데이터 폴더 (lab.remote 폴더 밖에 있어요)")
    out.append("# 등록했던 프로젝트의 .labremote/ 는 남아요. 필요하면 프로젝트마다 지워요.")
    out.append("# code tunnel을 켰다면: code tunnel service uninstall · code tunnel user logout")
    return out


def _clock() -> dict:
    try:
        from . import scheduler

        return scheduler.status()
    except Exception as exc:
        return {"running": False, "error": type(exc).__name__}
