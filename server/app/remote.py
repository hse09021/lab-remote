"""바깥 주소 — 터널로 전달한 lab.remote 주소 (9단계).

code tunnel로 들어온 브라우저는 VS Code 의 Ports 보기에서 8000 을 전달해 받은
"Forwarded Address"로 lab.remote 를 연다. 그 주소의 정확한 모양은 공식 문서에
없어서(실측 전) 코드가 짐작하지 않는다 — **사람이 그 주소를 그대로 적는다.**

    labremote remote set https://<전달된 주소>/

적으면 두 가지가 된다.
- 그 Host 가 허용 목록에 들어간다 (main.py 의 Host · Origin 검사).
- Discord 알림에 "답하기" 링크가 붙는다 (alerts.py).

데이터 폴더의 `remote.json`에 둔다. 환경 변수 `LAB_ALLOWED_HOSTS` 도 그대로 먹는다.
"""

from __future__ import annotations

import json
import os
from urllib.parse import quote, urlsplit

from . import registry

__all__ = ["RemoteError", "settings", "set_url", "clear", "public_url", "extra_hosts", "link_for"]


class RemoteError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def _path() -> str:
    return os.path.join(registry.data_dir(), "remote.json")


def settings() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _clean(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise RemoteError("https://로 시작하는 전체 주소를 적어 주세요 (VS Code Ports 보기의 Forwarded Address).")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RemoteError("주소에 계정 · ? · # 은 넣지 말아 주세요.")
    if parts.hostname in ("127.0.0.1", "localhost", "::1"):
        raise RemoteError("이 컴퓨터 주소는 적을 필요가 없어요. 터널로 전달된 바깥 주소를 적어 주세요.")
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"https://{netloc}{parts.path.rstrip('/')}"


def set_url(url: str) -> dict:
    clean = _clean(url)
    registry.write_json(_path(), {"publicUrl": clean})
    return info()


def clear() -> dict:
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass
    return info()


def public_url() -> str:
    value = settings().get("publicUrl")
    return value if isinstance(value, str) else ""


def extra_hosts() -> set[str]:
    out = {h.strip().lower() for h in (os.environ.get("LAB_ALLOWED_HOSTS") or "").split(",") if h.strip()}
    url = public_url()
    if url:
        host = urlsplit(url).hostname
        if host:
            out.add(host.lower())
    return out


def info() -> dict:
    url = public_url()
    env = sorted(h for h in (os.environ.get("LAB_ALLOWED_HOSTS") or "").split(",") if h.strip())
    return {"publicUrl": url, "hosts": sorted(extra_hosts()), "envHosts": env}


def link_for(ref: dict | None) -> str:
    """알림이 가리키는 화면의 바깥 주소. 바깥 주소가 없으면 ""."""
    base = public_url()
    if not base or not ref:
        return ""
    project = ref.get("project") or ""
    if ref.get("session") and project:
        return f"{base}/projects/{quote(project)}/ade?session={quote(str(ref['session']))}"
    if ref.get("run") and project:
        return f"{base}/projects/{quote(project)}?tab=work&run={quote(str(ref['run']))}"
    if project:
        return f"{base}/projects/{quote(project)}"
    return f"{base}/inbox"
