"""lab.remote 데이터 폴더의 설정과 비밀.

v3 는 데이터 폴더(`registry.data_dir()`) 밖에 설정을 두지 않는다
(docs/v3/PLAN.md 1장 · 3장). 그래서 v1 의 `~/.config/labremote/` 는 쓰지 않는다.

    <data>/discord.json   Discord 웹훅 주소·채널 라우팅·알림 쿨다운 (권한 0600)

**웹훅 주소는 비밀이다.** 로그·화면·에러에 원문을 찍지 않는다 — 화면에는
`masked_webhook()`으로 가려서 보인다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os

from . import registry

__all__ = [
    "SECRET_MODE",
    "COOLDOWN_DEFAULTS",
    "discord_path",
    "load",
    "save",
    "discord_webhook",
    "route_label",
    "set_webhook",
    "check_webhook",
    "clear_webhook",
    "masked_webhook",
    "cooldown_sec",
    "mode_of",
    "is_private",
]

#: 알림 종류별 기본 쿨다운(초). `discord.json` 의 `cooldownSec`로 덮어쓴다.
COOLDOWN_DEFAULTS = {
    "approval": 0,  # 답이 필요한 건 묵히지 않는다
    "failure": 300,
    "gpu": 1800,
    "driver": 1800,
    "start": 0,
    "done": 0,
}

#: 비밀 파일에 요구하는 권한. 다른 사용자가 읽을 수 있으면 비밀이 아니다.
SECRET_MODE = 0o600


def discord_path() -> str:
    return os.path.join(registry.data_dir(), "discord.json")


def load() -> dict:
    """`discord.json` 을 읽는다. 없거나 깨졌으면 빈 dict. **던지지 않는다.**

    설정이 없어도 서버는 돌아야 한다 — 알림만 안 간다.
    """
    try:
        with open(discord_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> str:
    """원자적으로 쓴다. **만들 때부터 0600** 이다 — 쓰고 나서 chmod 하면 그
    사이에 남이 읽을 수 있는 틈이 생긴다."""
    path = discord_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECRET_MODE)
    try:
        os.write(fd, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, SECRET_MODE)  # umask와 상관없이
    os.replace(tmp, path)
    return path


def discord_webhook(kind: str = "") -> str:
    """보낼 주소. 우선순위: `LAB_DISCORD_WEBHOOK` → `routes.<종류>` → `webhook`."""
    env = os.environ.get("LAB_DISCORD_WEBHOOK", "").strip()
    if env:
        return env
    data = load()
    routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
    if kind:
        route = routes.get(kind)
        if isinstance(route, str) and route.strip():
            return route.strip()
    default = data.get("webhook")
    return default.strip() if isinstance(default, str) else ""


def route_label(kind: str = "") -> str:
    """어느 주소로 보내는지의 **이름**. 주소 원문이 아니다.

    `env` · `routes.<종류>` · `default` · 빈 문자열(주소 없음). 보낸 기록
    (`notifications.route`)에는 이것만 남긴다 — 웹훅 주소는 0600 파일에만 둔다.
    """
    if os.environ.get("LAB_DISCORD_WEBHOOK", "").strip():
        return "env"
    data = load()
    routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
    if kind and isinstance(routes.get(kind), str) and routes[kind].strip():
        return f"routes.{kind}"
    default = data.get("webhook")
    return "default" if isinstance(default, str) and default.strip() else ""


#: 받는 웹훅 주소 꼴. 화면에서 붙여 넣은 값이 엉뚱한 곳으로 새지 않게.
WEBHOOK_HOSTS = ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com")


def check_webhook(url: str) -> str:
    """Discord 웹훅 주소인지. 아니면 `ValueError` — **문구에 주소를 싣지 않는다.**"""
    from urllib.parse import urlsplit

    url = (url or "").strip()
    if not url:
        raise ValueError("웹훅 주소가 비어 있어요")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or (parts.hostname or "") not in WEBHOOK_HOSTS
        or not parts.path.startswith("/api/webhooks/")
        or parts.username
        or parts.password
        or any(c.isspace() for c in url)
    ):
        raise ValueError("Discord 웹훅 주소가 아니에요 (https://discord.com/api/webhooks/… 꼴)")
    return url


def set_webhook(url: str) -> str:
    """기본 주소를 바꾼다. 다른 칸(라우팅·쿨다운)은 그대로 둔다."""
    url = check_webhook(url)
    data = load()
    data["webhook"] = url
    return save(data)


def clear_webhook() -> str:
    """기본 주소를 끊는다(지운다). 라우팅·쿨다운은 그대로 둔다."""
    data = load()
    data.pop("webhook", None)
    return save(data)


def masked_webhook(url: str | None = None) -> str:
    """화면용으로 가린 주소. 원문은 **어디에도** 내보내지 않는다.

    호스트만 남기고 경로(ID·토큰)는 `••••`로 가린다.
    """
    url = discord_webhook() if url is None else url
    if not url:
        return ""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return "••••"
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/••••"


def cooldown_sec(kind: str) -> int:
    """같은 알림을 다시 보내기까지 묵힐 시간(초)."""
    table = load().get("cooldownSec")
    value = table.get(kind) if isinstance(table, dict) else None
    if isinstance(value, bool):  # true 를 1로 읽지 않는다
        value = None
    if isinstance(value, int) and value >= 0:
        return value
    return COOLDOWN_DEFAULTS.get(kind, 300)


def mode_of(path: str) -> int | None:
    """파일 권한 비트. 없으면 None."""
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return None


def is_private(path: str) -> bool:
    """남이 못 읽는가. 0600보다 넓으면 거짓."""
    mode = mode_of(path)
    return mode is not None and mode & 0o077 == 0
