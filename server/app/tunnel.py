"""code tunnel 상태 — **읽기만** 한다 (2026-11-23 결정: 터널은 사람이 공식 명령으로 켠다).

    code tunnel user login          # GitHub 로그인 (사람이)
    code tunnel service install     # 상시 켜기 (사람이, VS Code 공식 명령)

lab.remote 가 부르는 것은 두 가지뿐이다 (둘 다 로그인 · 상태를 바꾸지 않는다):

    code tunnel status      → {"tunnel": null | {...}, "service_installed": bool}   (실측: 꺼져 있을 때)
    code tunnel user show   → "not logged in"(종료코드 1, 실측) | 로그인한 계정

- 켜져 있을 때 (실측 2026-11-23, VS Code CLI 1.131):
      {"tunnel": {"name": "...", "started_at": "...", "tunnel": "Connected",
                  "last_connected_at": "...", "last_disconnected_at": null, "last_fail_reason": null},
       "service_installed": true}
  안쪽 `tunnel` 이 "Connected" 일 때만 켜짐으로 본다. 그 밖의 값이면 그 값과 실패 사유를 보여 준다.
- `code tunnel service install` 은 사용자 서비스 `~/.config/systemd/user/code-tunnel.service`
  (→ `~/.vscode/cli/code-tunnel.service`)를 만들고 켠다. 로그아웃 뒤에도 돌려면 linger 가 필요하다.
- VS Code 원격 창 안의 셸에는 `.../remote-cli/code` 가 PATH 앞에 있는데, 그건 터널 CLI 가 아니라 건너뛴다.
- 느린 명령이라 30초 캐시한다. 화면을 볼 때만 불린다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

__all__ = ["cli_path", "status", "CACHE_SEC"]

CACHE_SEC = 30.0
_lock = threading.Lock()
_cache: tuple[float, dict] | None = None

#: 데스크톱 VS Code에 딸린 터널 CLI · 따로 받은 CLI
_CANDIDATES = (
    "/usr/share/code/bin/code-tunnel",
    "/usr/share/code-insiders/bin/code-tunnel-insiders",
    "/snap/code/current/usr/share/code/bin/code-tunnel",
    os.path.expanduser("~/.local/bin/code"),
    "/usr/local/bin/code",
)


def cli_path() -> str:
    found = shutil.which("code-tunnel")
    if found:
        return found
    for path in _CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    found = shutil.which("code") or ""
    if found and "/remote-cli/" not in found:
        return found
    return ""


def _run(argv: list[str]) -> tuple[int, str]:
    env = dict(os.environ)
    for key in ("VSCODE_IPC_HOOK_CLI", "VSCODE_CLI"):  # 원격 창 셸에서 불려도 로컬 CLI로 돌게
        env.pop(key, None)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return done.returncode, (done.stdout or "").strip() or (done.stderr or "").strip()


def _probe(run=_run) -> dict:
    cli = cli_path()
    out: dict = {
        "cli": cli,
        "state": "absent",  # absent(CLI 없음) · off(안 떠 있음) · up(떠 있음) · unknown
        "service": False,
        "loggedIn": None,
        "name": "",
        "url": "",
        "detail": "",
    }
    if not cli:
        out["detail"] = "VS Code(또는 VS Code CLI)가 없어요"
        return out
    code, text = run([cli, "tunnel", "status"])
    try:
        data = json.loads(text) if code == 0 else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        out.update(state="unknown", detail=(text or f"종료코드 {code}")[:200])
    else:
        out["service"] = bool(data.get("service_installed"))
        tun = data.get("tunnel")
        if isinstance(tun, dict):
            inner = tun.get("tunnel")
            name = tun.get("name") or (inner.get("name") if isinstance(inner, dict) else "") or ""
            out["name"] = str(name)
            word = inner if isinstance(inner, str) else (next(iter(inner), "") if isinstance(inner, dict) else "")
            if word == "Connected" or (not word and not tun.get("last_fail_reason")):
                out["state"] = "up"
            else:
                out["state"] = "off"
                reason = tun.get("last_fail_reason") or ""
                out["detail"] = " · ".join(x for x in (str(word), str(reason)) if x)[:200]
        elif tun:
            out["state"] = "up"
        else:
            out["state"] = "off"
    code, text = run([cli, "tunnel", "user", "show"])
    # 실측: 로그인 안 했으면 "not logged in"과 종료코드 1. 계정 이름은 내보내지 않는다 — 로그인했는지만
    if "not logged in" in text.lower():
        out["loggedIn"] = False
    elif code == 0 and text:
        out["loggedIn"] = True
    if out["name"]:
        out["url"] = f"https://vscode.dev/tunnel/{out['name']}"
    return out


def status(*, fresh: bool = False, run=None) -> dict:
    global _cache
    with _lock:
        now = time.monotonic()
        if not fresh and run is None and _cache and now - _cache[0] < CACHE_SEC:
            return _cache[1]
        got = _probe(run or _run)
        if run is None:
            _cache = (now, got)
        return got
