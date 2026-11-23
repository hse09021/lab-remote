"""`labremote autostart install|uninstall` — 자동 시작 켜고 끄기 (PLAN 1.1 · 6장 9단계).

lab.remote 가 바꾸는 시스템 설정은 **이것뿐**이고, 사람이 명령을 부르고 확인했을 때만 바꾼다.

    켜기   ① ~/.config/systemd/user/labremote-session.service 쓰기
           ② linger 가 꺼져 있으면 `loginctl enable-linger` (원래 값을 기억)
           ③ `systemctl --user daemon-reload` · `enable --now`
    끄기   ① `disable` ② 유닛 파일 지우기 · daemon-reload
           ③ linger 를 **lab.remote 가 켰을 때만** 원래대로(`disable-linger`)
           ④ 마지막에 멈추기 — 이 서버가 그 유닛 안에서 돌면 여기서 같이 끝난다

sudo 는 필요 없다. 원래 linger 값은 데이터 폴더 `autostart.json`에 둔다.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Callable

from .. import registry
from . import units

__all__ = ["AutostartError", "plan", "install", "uninstall", "restart", "record", "later"]

Runner = Callable[[list[str]], tuple[int, str]]


class AutostartError(RuntimeError):
    """사람에게 그대로 보여 줄 수 있는 실패 사유."""


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def _record_path() -> str:
    return os.path.join(registry.data_dir(), "autostart.json")


def record() -> dict:
    try:
        with open(_record_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _systemctl() -> str:
    path = units._systemctl()
    if not path:
        raise AutostartError("systemctl 이 없어요 — systemd 가 아닌 환경이라 자동 시작을 쓸 수 없어요.")
    return path


def plan(*, port: int = units.DEFAULT_PORT) -> list[dict]:
    """켜면 무엇이 바뀌나 — 사람에게 먼저 보여 준다."""
    user = units._user() or "<사용자>"
    linger = units.linger()
    steps = [
        {"what": "사용자 서비스 파일 쓰기", "detail": units.unit_path()},
        {"what": "서비스 켜기", "detail": f"systemctl --user enable --now {units.NAME} · 127.0.0.1:{port}"},
    ]
    if linger is not True:
        steps.insert(1, {
            "what": "linger 켜기 (로그아웃 · 재부팅 뒤에도 서비스 유지)",
            "detail": f"loginctl enable-linger {user} · 지금 {'꺼짐' if linger is False else '모름'} — 끌 때 원래대로 돌려요",
        })
    return steps


def install(*, port: int = units.DEFAULT_PORT, python: str = "", run: Runner = _run) -> list[dict]:
    """자동 시작을 켠다. 단계마다 결과를 돌려준다. 실패하면 거기서 멈춘다."""
    systemctl = _systemctl()
    done: list[dict] = []

    def step(what: str, argv: list[str]) -> None:
        code, out = run(argv)
        done.append({"what": what, "ok": code == 0, "detail": out[-300:]})
        if code != 0:
            raise AutostartError(f"{what}에서 멈췄어요: {out[-300:] or f'종료코드 {code}'}")

    try:
        written = units.write(python=python, port=port)
    except (ValueError, OSError) as exc:
        raise AutostartError(str(exc)) from None
    done.append({"what": "사용자 서비스 파일", "ok": True, "detail": written["path"] + (" (바뀜)" if written["changed"] else " (그대로)")})

    # 원래 linger 값은 처음 켤 때 한 번만 기억한다 (다시 켜도 "원래" 가 바뀌지 않게)
    rec = record()
    before = units.linger()
    if "lingerBefore" not in rec:
        rec = {"lingerBefore": before, "installedAt": time.time()}
    rec["port"] = int(port)
    registry.write_json(_record_path(), rec)

    if before is not True:
        user = units._user()
        if not user:
            raise AutostartError("사용자 이름을 몰라 linger 를 켤 수 없어요.")
        step("linger 켜기", ["loginctl", "enable-linger", user])
    step("daemon-reload", [systemctl, "--user", "daemon-reload"])
    step("서비스 켜기", [systemctl, "--user", "enable", "--now", f"{units.NAME}.service"])
    return done


def uninstall(*, run: Runner = _run, stop: bool = True) -> list[dict]:
    """자동 시작을 끈다. 이 서버가 그 유닛 안에서 돌면 마지막 단계에서 같이 끝난다."""
    systemctl = _systemctl()
    done: list[dict] = []

    def step(what: str, argv: list[str], *, must: bool = True) -> None:
        code, out = run(argv)
        done.append({"what": what, "ok": code == 0, "detail": out[-300:]})
        if code != 0 and must:
            raise AutostartError(f"{what}에서 멈췄어요: {out[-300:] or f'종료코드 {code}'}")

    unit_file = units.unit_path()
    step("서비스 끄기 (다음 부팅부터)", [systemctl, "--user", "disable", f"{units.NAME}.service"], must=False)
    if os.path.exists(unit_file):
        os.remove(unit_file)
        done.append({"what": "사용자 서비스 파일 지우기", "ok": True, "detail": unit_file})
    step("daemon-reload", [systemctl, "--user", "daemon-reload"], must=False)

    rec = record()
    if rec.get("lingerBefore") is False and units.linger() is True and _tunnel_service():
        # code tunnel 서비스도 linger에 기대요 — 끄면 로그아웃할 때 터널도 내려가요
        done.append({"what": "linger", "ok": True, "detail": "code tunnel 서비스가 써서 그대로 둬요 (끄려면 loginctl disable-linger)"})
    elif rec.get("lingerBefore") is False and units.linger() is True:
        user = units._user()
        step("linger 원래대로 (끄기)", ["loginctl", "disable-linger", user], must=False)
    elif "lingerBefore" not in rec:
        done.append({"what": "linger", "ok": True, "detail": "lab.remote 가 켠 기록이 없어 그대로 둬요"})
    else:
        done.append({"what": "linger", "ok": True, "detail": "원래 켜져 있어서 그대로 둬요"})
    try:
        os.remove(_record_path())
    except FileNotFoundError:
        pass

    # 마지막: 멈추기. 이 서버가 그 안에 있으면 여기서 끝난다 — 화면에서 부를 때는 답을 돌려준 뒤 `later`로
    if stop:
        step("멈추기", [systemctl, "--user", "stop", "--no-block", f"{units.NAME}.service"], must=False)
    else:
        done.append({"what": "멈추기", "ok": True, "detail": "곧 멈춰요"})
    return done


def later(argv_tail: list[str], *, delay: float = 1.0) -> None:
    """화면의 요청에 답을 돌려준 뒤 systemctl 을 부른다 (이 서버가 그 유닛 안일 때)."""
    import threading

    systemctl = _systemctl()
    threading.Timer(delay, _run, args=([systemctl, "--user", *argv_tail, f"{units.NAME}.service"],)).start()


def _tunnel_service() -> bool:
    """`code tunnel service install`로 깐 터널 서비스가 있나 (linger 를 같이 쓴다)."""
    try:
        from .. import tunnel

        return bool(tunnel.status().get("service"))
    except Exception:
        return False


def restart(*, run: Runner = _run, now: bool = True) -> dict:
    """"세션 다시 켜기" — 자동 시작이 켜져 있을 때만. 답을 먼저 돌려주고 다시 뜬다."""
    systemctl = _systemctl()
    if not os.path.exists(units.unit_path()):
        raise AutostartError("자동 시작이 꺼져 있어요 — labremote autostart install로 켜요.")
    if not now:
        later(["restart", "--no-block"])
        return {"ok": True}
    code, out = run([systemctl, "--user", "restart", "--no-block", f"{units.NAME}.service"])
    if code != 0:
        raise AutostartError(f"다시 켜지 못했어요: {out[-300:] or f'종료코드 {code}'}")
    return {"ok": True}
