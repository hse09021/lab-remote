"""`~/.config/labremote/` 의 설정과 비밀.

프로젝트 폴더 **밖**에 둔다. 그래야 AI 가 웹훅 주소나 허가 서명 키를 못
고치고, 저장소에 비밀이 섞이지도 않는다. 이 폴더는 이미 정책의
`SECRET_FILES` 라 **Claude 가 읽기까지 막힌다** (`policy_defaults.SECRET_FILES`).

읽는 것
    config.toml          웹훅 주소·채널 라우팅·알림 쿨다운
    grant_key            1회용 허가 서명 키 (32바이트, 0600)
    usage_patterns.json  "사용량 한도" 로 볼 문구 (실측 전까지 비어 있다)

`tomllib` 은 3.11 표준 라이브러리라 훅 경로 원칙을 깨지 않는다. 이 모듈은
`notify` 가 import 하므로 **sqlite3·외부 패키지를 쓰지 않는다.**
"""

from __future__ import annotations

import json
import os
import tomllib

__all__ = [
    "config_dir",
    "config_path",
    "load",
    "tokens",
    "discord_webhook",
    "cooldown_sec",
    "grant_key_path",
    "grant_key",
    "ensure_grant_key",
    "usage_patterns",
    "mode_of",
    "is_private",
]

#: 알림 종류별 기본 쿨다운(초). `config.toml` 의 `[notify.cooldown_sec]` 로 덮어쓴다.
COOLDOWN_DEFAULTS = {
    "approval": 0,  # 승인은 사람을 기다리게 하니 묵히지 않는다
    "failure": 300,
    "gpu": 1800,
    "usage_limit": 1800,
    "driver": 1800,
    "start": 0,
    "done": 0,
    "recovery": 0,
}

#: 비밀 파일에 요구하는 권한. 다른 사용자가 읽을 수 있으면 비밀이 아니다.
SECRET_MODE = 0o600

_KEY_BYTES = 32


def config_dir() -> str:
    """`LAB_CONFIG_DIR` 이 있으면 그것(테스트용), 없으면 `~/.config/labremote`."""
    override = os.environ.get("LAB_CONFIG_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(os.path.abspath(os.path.expanduser(base)), "labremote")


def config_path() -> str:
    return os.path.join(config_dir(), "config.toml")


def load() -> dict:
    """`config.toml` 을 읽는다. 없거나 깨졌으면 빈 dict.

    **던지지 않는다.** 설정이 없어도 돌아야 하고(알림만 안 감), 훅 경로에서
    불리므로 판정을 막아서는 안 된다.
    """
    try:
        with open(config_path(), "rb") as fh:
            data = tomllib.load(fh)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _section(data: dict, *keys: str) -> dict:
    cur = data
    for key in keys:
        nxt = cur.get(key) if isinstance(cur, dict) else None
        if not isinstance(nxt, dict):
            return {}
        cur = nxt
    return cur


def discord_webhook(kind: str = "") -> str:
    """보낼 주소. **환경 변수가 이깁니다.**

    우선순위: `LAB_DISCORD_WEBHOOK` -> `[discord.routes].<종류>` ->
    `[discord].webhook` -> 빈 문자열.

    환경 변수를 맨 앞에 둔 건 ①의 동작(`notify.webhook_url`)과 테스트를
    그대로 두기 위해서다. 종류별 채널은 설정 파일에만 있다.
    """
    env = os.environ.get("LAB_DISCORD_WEBHOOK", "").strip()
    if env:
        return env
    data = load()
    routes = _section(data, "discord", "routes")
    if kind:
        route = routes.get(kind)
        if isinstance(route, str) and route.strip():
            return route.strip()
    default = _section(data, "discord").get("webhook")
    return default.strip() if isinstance(default, str) else ""


def cooldown_sec(kind: str) -> int:
    """같은 알림을 다시 보내기까지 묵힐 시간(초)."""
    value = _section(load(), "notify", "cooldown_sec").get(kind)
    if isinstance(value, bool):  # TOML 의 true 를 1 로 읽지 않는다
        value = None
    if isinstance(value, int) and value >= 0:
        return value
    return COOLDOWN_DEFAULTS.get(kind, 300)


def tokens() -> dict[str, str]:
    """`[tokens]` 절. 학습에 꼭 필요한 토큰만 둔다.

        [tokens]
        HF_TOKEN = "hf_..."          # 읽기 전용 토큰만
        WANDB_API_KEY = "..."

    ⚠ **AI 가 쓴 학습 코드가 이 값을 읽을 수 있다는 전제로 둔다.** 학습
    프로세스의 환경 변수로 들어가므로 `os.environ` 한 줄이면 보인다. 샌드박스는
    파일을 가려 주지만 환경 변수는 가려 주지 않는다 — 가리면 학습이 모델을
    못 내려받는다.

    그래서 **읽기 전용·최소 권한 토큰만** 쓴다. 쓰기 권한이 있는 토큰을 넣으면
    AI 가 저장소나 모델 허브에 쓸 수 있다.

    기본은 **아무것도 주입하지 않는다.** 정책의 `runner.injectTokens` 에 이름을
    적어야 그 이름만 들어간다.
    """
    section = _section(load(), "tokens")
    out: dict[str, str] = {}
    for name, value in section.items():
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if text and not text.startswith("["):  # 자리표시는 건너뛴다
            out[str(name)] = text
    return out


# --- 1회용 허가 서명 키 -----------------------------------------------------


def grant_key_path() -> str:
    return os.path.join(config_dir(), "grant_key")


def mode_of(path: str) -> int | None:
    """파일 권한 비트. 없으면 None."""
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return None


def is_private(path: str) -> bool:
    """남이 못 읽는가. 0600 보다 넓으면 거짓."""
    mode = mode_of(path)
    return mode is not None and mode & 0o077 == 0


def grant_key() -> bytes | None:
    """서명 키. 없거나 읽을 수 없으면 None.

    **None 이면 허가가 전부 무효가 된다** (`grants.verify`). 키 없이 서명을
    건너뛰는 길을 두면 AI 가 쓴 코드가 허가 파일을 직접 만들어 넣을 수 있다.
    """
    try:
        with open(grant_key_path(), "rb") as fh:
            raw = fh.read().strip()
    except OSError:
        return None
    return raw or None


def ensure_grant_key() -> str:
    """없으면 32바이트 랜덤으로 만든다(0600). 있으면 그대로 두고 경로를 돌려준다."""
    path = grant_key_path()
    if os.path.exists(path):
        if not is_private(path):
            os.chmod(path, SECRET_MODE)
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    # 만들 때부터 0600 이어야 한다. 쓰고 나서 chmod 하면 그 사이가 열린다.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_MODE)
    try:
        os.write(fd, os.urandom(_KEY_BYTES).hex().encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def usage_patterns() -> list[str]:
    """"사용량 한도" 로 볼 문구. 실측 전까지 비어 있다.

    패턴을 코드에 박지 않는다 — 한도 메시지를 아직 못 봤고, 틀린 패턴은
    인증 만료 같은 다른 오류를 한도로 오인해 영원히 기다리게 만든다.
    """
    path = os.path.join(config_dir(), "usage_patterns.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("patterns")
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, (str, int, float)) and str(x).strip()]
