"""arXiv HTML 본문 — 리더의 "arXiv HTML" 보기에 쓴다.

- arXiv 링크로 논문을 넣으면 PDF와 함께 `https://arxiv.org/html/<번호>`도 받는다(뒤에서).
  예전에 넣은 arXiv 논문은 리더에서 "arXiv HTML"을 누를 때 받는다.
- vault는 건드리지 않는다. 받은 본문 · 그림은 데이터 폴더 `papers_html/<키>/`에 둔다
  (언제든 다시 받을 수 있는 캐시라 Obsidian 폴더를 어지럽히지 않게).
- 그림 주소는 `/api/papers/<id>/html/assets/<이름>`으로 바꿔 둔다 — 화면은 같은 출처만 읽어요.
- arXiv에 HTML이 없는 논문(오래됐거나 변환 실패)은 `none`으로 적어 둔다.
- 받는 곳은 `arxiv.org`뿐이다. 스크립트 · 바깥 링크는 화면의 DOMPurify가 한 번 더 걸러요.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse

from . import papers, registry

__all__ = ["state", "states", "start", "fetch", "html_of", "asset_of", "arxiv_of"]

ARXIV_HTML = "https://arxiv.org/html/{id}"
MAX_HTML = 30 * 1024 * 1024
MAX_IMAGE = 15 * 1024 * 1024
MAX_IMAGES = 300
MAX_TOTAL = 200 * 1024 * 1024
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

_lock = threading.Lock()
_running: set[str] = set()


def _dir(pid: str) -> str:
    return os.path.join(registry.data_dir(), "papers_html", hashlib.sha1(pid.encode()).hexdigest()[:16])


def _meta_path(pid: str) -> str:
    return os.path.join(_dir(pid), "meta.json")


def _read_meta(pid: str) -> dict:
    try:
        with open(_meta_path(pid), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def arxiv_of(pid: str) -> str:
    for p in papers.scan()["papers"]:
        if p["id"] == pid:
            return papers.arxiv_id_or_none(p.get("arxiv") or "") or ""
    raise papers.PapersError("그런 논문이 없어요.")


def state(pid: str) -> str:
    """`done` · `running` · `none`(arXiv에 HTML 없음) · `error` · `missing`(아직 안 받음)"""
    if pid in _running:
        return "running"
    meta = _read_meta(pid)
    if meta.get("state") == "done" and os.path.isfile(os.path.join(_dir(pid), "index.html")):
        return "done"
    return str(meta.get("state") or "missing") if meta.get("state") in ("none", "error") else "missing"


def states() -> dict[str, str]:
    """목록용 — 받은 것만 빨리 본다"""
    out: dict[str, str] = {}
    for p in papers.scan()["papers"]:
        if p.get("arxiv"):
            out[p["id"]] = state(p["id"])
    return out


def _arxiv_url(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" and u.hostname == "arxiv.org"


def _get(url: str, *, limit: int, timeout: int = 60) -> tuple[bytes, str]:
    """(내용, 최종 주소). 404면 빈 내용"""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": papers.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            final = res.geturl()
            data = res.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return b"", url
        raise papers.PapersError(f"arXiv가 거절했어요 ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise papers.PapersError(f"arXiv에 연결하지 못했어요: {getattr(exc, 'reason', exc)}") from None
    if len(data) > limit:
        raise papers.PapersError("파일이 너무 커요.")
    return data, final


_IMG = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.I | re.S)


def fetch(pid: str, *, get=None) -> str:
    """받아서 저장하고 상태를 돌려준다. 실패하면 `error`를 적고 예외를 올린다."""
    get = get or _get  # 부를 때 찾아요 — 시험에서 바꿔 끼울 수 있게
    aid = arxiv_of(pid)
    if not aid:
        raise papers.PapersError("arXiv 번호가 없는 논문이에요.")
    out = _dir(pid)
    tmp = out + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        raw, final = get(ARXIV_HTML.format(id=aid), limit=MAX_HTML)
        if not raw or not _arxiv_url(final) or b"<html" not in raw[:4096].lower():
            _write_meta(tmp, {"state": "none", "arxiv": aid, "at": time.time()})
            _swap(tmp, out)
            return "none"
        html = raw.decode("utf-8", errors="replace")
        # 상대 주소의 기준 — 브라우저와 같게 최종 주소(<base href>가 있으면 그것)로 풀어요.
        # arXiv는 /html/2305.14314v1 처럼 끝에 / 없이 주고 그림을 "2305.14314v1/x.png"로 적어요
        bm = re.search(r"""<base\b[^>]*\bhref\s*=\s*["']([^"']+)""", html, re.I)
        base = urllib.parse.urljoin(final, bm.group(1)) if bm else final
        # 본문(<article>)만 남겨요 — arXiv 사이트 머리글 · 목차 · 신고 창 · 꼬리말은 빼요
        am = re.search(r"<article\b.*</article>", html, re.S | re.I)
        if am:
            html = am.group(0)
        names: dict[str, str] = {}
        total = 0
        quoted = urllib.parse.quote(pid, safe="")

        def swap(m: re.Match) -> str:
            nonlocal total
            src = m.group(3).strip()
            if src.startswith("data:"):
                return m.group(0)
            url = urllib.parse.urljoin(base, src)
            if not _arxiv_url(url):
                return m.group(0)
            if url not in names:
                ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
                if ext not in IMAGE_EXT or len(names) >= MAX_IMAGES or total >= MAX_TOTAL:
                    return m.group(0)
                try:
                    data, _ = get(url, limit=MAX_IMAGE, timeout=30)
                except papers.PapersError:
                    return m.group(0)
                if not data:
                    return m.group(0)
                name = f"a{len(names) + 1}{ext}"
                with open(os.path.join(tmp, name), "wb") as f:
                    f.write(data)
                total += len(data)
                names[url] = name
            return f"{m.group(1)}{m.group(2)}/api/papers/{quoted}/html/assets/{names[url]}{m.group(2)}"

        html = _IMG.sub(swap, html)
        with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        _write_meta(tmp, {"state": "done", "arxiv": aid, "url": final, "images": len(names), "at": time.time()})
        _swap(tmp, out)
        return "done"
    except papers.PapersError:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        if _read_meta(pid).get("state") != "done":
            _write_meta(out, {"state": "error", "arxiv": aid, "at": time.time()})
        raise


def _write_meta(folder: str, meta: dict) -> None:
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def _swap(tmp: str, out: str) -> None:
    old = out + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(out):
        os.replace(out, old)
    os.replace(tmp, out)
    shutil.rmtree(old, ignore_errors=True)


def start(pid: str, *, get=None) -> str:
    """뒤에서 받기 시작한다(이미 받는 중이면 그대로). 지금 상태를 돌려준다."""
    if not arxiv_of(pid):  # 없는 논문이면 여기서 PapersError
        raise papers.PapersError("arXiv 번호가 없는 논문이에요.")
    with _lock:
        if pid in _running:
            return "running"
        _running.add(pid)

    def run() -> None:
        try:
            fetch(pid, get=get)
        except papers.PapersError:
            pass
        finally:
            with _lock:
                _running.discard(pid)

    threading.Thread(target=run, name=f"arxiv-html:{pid}", daemon=True).start()
    return "running"


def html_of(pid: str) -> str:
    if state(pid) != "done":
        raise papers.PapersError("arXiv HTML을 아직 받지 않았어요.")
    with open(os.path.join(_dir(pid), "index.html"), encoding="utf-8") as f:
        return f.read()


def asset_of(pid: str, name: str) -> str:
    if not re.fullmatch(r"a\d{1,4}\.(png|jpg|jpeg|gif|svg|webp)", name):
        raise papers.PapersError("그런 그림이 없어요.")
    path = os.path.join(_dir(pid), name)
    if not os.path.isfile(path):
        raise papers.PapersError("그런 그림이 없어요.")
    return path
