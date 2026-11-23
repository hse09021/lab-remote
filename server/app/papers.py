"""Papers — vault를 **읽기만** 해서 라이브러리 목록과 지식그래프를 만든다 (8단계).

vault (Obsidian 폴더):
    <vault>/Papers/*.md   논문 노트. 앞쪽 메타(--- … ---)에 title · authors · year · venue ·
                          category · arxiv · cites([[링크]] 목록)
    <vault>/그 밖의 *.md   내 메모. 본문의 [[링크]]가 논문이나 프로젝트를 가리키면 그래프에 나온다

- vault 위치는 사람이 정한다(설정, 2026-11-23). 정하지 않으면 데이터 폴더의 `vault/`.
- **있는 노트 파일을 고치지 않는다.** 읽음 상태처럼 lab.remote가 기억할 것은 데이터 폴더의
  `papers.json`에 둔다.
- 논문 추가(2026-11-24 결정)만 vault에 **새 파일을 쓴다** — `Papers/<이름>.md`와
  `Papers/pdf/<이름>.pdf`. 같은 이름이 있으면 뒤에 번호를 붙이고, 덮어쓰지 않는다.
  - arXiv 링크: arXiv API(export.arxiv.org)에서 제목 · 저자 · 연도 · 분야 · 초록을 받고 PDF도 받는다
  - PDF 올리기: 파일을 두고 파일 이름으로 노트를 만든다(메타는 사람이 채운다)
- "프로젝트에서 사용"은 프로젝트 설정의 `papers` 목록(사람이 고름)에서 온다.
- 리더 본문은 화면이 PDF(pdf.js) · arXiv HTML로 그린다. AI 요약 · 분석 · 설명은 누를 때만 (summaries · reader_ai).
"""

from __future__ import annotations

import json
import os
import re
import time

from . import paths, projects, registry

__all__ = ["PapersError", "settings", "set_vault", "vault_path", "scan", "list_papers", "graph", "set_status", "body_of",
           "arxiv_id", "add_arxiv", "add_pdf", "pdf_of"]

WIKI_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MAX_NOTES = 5000
MAX_BYTES = 512 * 1024
STATUSES = ("todo", "reading", "done")


class PapersError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


# --- 설정 ---------------------------------------------------------------------


def _settings_path() -> str:
    return os.path.join(registry.data_dir(), "papers.json")


def settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    registry.write_json(_settings_path(), data)


def vault_path() -> str:
    custom = settings().get("vault")
    return paths.real(custom) if isinstance(custom, str) and custom.strip() else os.path.join(registry.data_dir(), "vault")


def set_vault(path: str) -> dict:
    """vault 위치를 정한다. 빈 값이면 기본(데이터 폴더의 vault/)으로."""
    data = settings()
    path = (path or "").strip()
    if not path:
        data.pop("vault", None)
    else:
        real = paths.real(path)
        if not os.path.isdir(real):
            raise PapersError(f"폴더가 없어요: {real}")
        if real in (os.sep, paths.real("~")):
            raise PapersError("홈 폴더나 / 전체는 vault로 쓸 수 없어요.")
        data["vault"] = real
    _save(data)
    return info()


def info() -> dict:
    root = vault_path()
    exists = os.path.isdir(root)
    found = scan() if exists else {"papers": [], "notes": []}
    return {
        "path": root,
        "custom": bool(settings().get("vault")),
        "exists": exists,
        "papers": len(found["papers"]),
        "notes": len(found["notes"]),
    }


def set_status(pid: str, status: str) -> dict:
    if status not in STATUSES:
        raise PapersError(f"읽음 상태는 {', '.join(STATUSES)} 중 하나예요.")
    data = settings()
    data.setdefault("status", {})[pid] = status
    _save(data)
    return {"id": pid, "status": status}


# --- 읽기 ---------------------------------------------------------------------


def _front(text: str) -> tuple[dict, str]:
    """앞쪽 메타 `--- … ---`를 아주 단순하게 읽는다 (key: value · key: [a, b] · - 목록)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict = {}
    key = None
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(("  -", "- ")) and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(line.split("-", 1)[1].strip().strip("\"'"))
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if value.startswith("[") and value.endswith("]") and not value.startswith("[["):
                meta[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
            elif value:
                meta[key] = value.strip("\"'")
            else:
                meta[key] = []
    return meta, text[end + 4 :].lstrip("\n")


def _links(values) -> list[str]:
    out = []
    for v in values if isinstance(values, list) else [values]:
        found = WIKI_RE.findall(str(v))
        out += [f.strip() for f in found] if found else ([str(v).strip()] if str(v).strip() else [])
    return out


def _read(path: str) -> str:
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return ""
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


_cache: dict = {"key": None, "value": None}


def scan() -> dict:
    """vault를 훑는다. 바뀐 게 없으면(파일 수 · 최근 수정 시각) 캐시를 쓴다."""
    root = vault_path()
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]  # .obsidian · .trash
        for f in filenames:
            if f.endswith(".md"):
                files.append(os.path.join(dirpath, f))
        if len(files) > MAX_NOTES:
            break
    key = (root, len(files), max((os.path.getmtime(f) for f in files), default=0))
    if _cache["key"] == key:
        return _cache["value"]
    papers, notes = [], []
    paper_dir = os.path.join(root, "Papers")
    for f in sorted(files):
        text = _read(f)
        meta, body = _front(text)
        if meta.get("summary_of"):
            continue  # lab.remote가 만든 요약 파일 — 논문도 메모도 아니다
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        stem = os.path.splitext(os.path.basename(f))[0]
        if paths.is_inside(paths.real(paper_dir), paths.real(f)):
            year = str(meta.get("year") or "")
            authors = meta.get("authors") or ""
            if isinstance(authors, list):
                authors = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            papers.append({
                "id": stem,
                "title": str(meta.get("title") or stem),
                "authors": " · ".join(x for x in (str(authors), year) if x),
                "venue": str(meta.get("venue") or ""),
                "category": str(meta.get("category") or meta.get("field") or "기타"),
                "arxiv": str(meta.get("arxiv") or ""),
                "source": "arxiv-html" if meta.get("arxiv") else "pdf",
                "cites": _links(meta.get("cites") or meta.get("references") or []),
                "aliases": [str(a) for a in (meta.get("aliases") or [])] if isinstance(meta.get("aliases"), list) else [],
                "path": rel,
                "mtime": os.path.getmtime(f),
                "hasBody": bool(body.strip()),
                "hasPdf": bool(str(meta.get("pdf") or "").strip()),
                "authorList": [str(a) for a in meta.get("authors")] if isinstance(meta.get("authors"), list) else [a.strip() for a in str(meta.get("authors") or "").split(",") if a.strip()],
                "year": year,
            })
        else:
            heading = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), "")
            notes.append({"id": "note:" + rel, "title": str(meta.get("title") or heading or stem), "path": rel, "links": _links([body]), "mtime": os.path.getmtime(f)})
    value = {"papers": papers, "notes": notes}
    _cache.update(key=key, value=value)
    return value


def _ago(ts: float) -> str:
    d = time.time() - ts
    if d < 3600:
        return "방금"
    if d < 86400:
        return f"{int(d // 3600)}시간 전"
    return time.strftime("%m/%d", time.localtime(ts))


def _hidden() -> set[str]:
    return {str(x) for x in (settings().get("hidden") or [])}


def _collections() -> dict[str, list[str]]:
    raw = settings().get("collections") or {}
    return {str(k): [str(x) for x in v] for k, v in raw.items() if isinstance(v, list)} if isinstance(raw, dict) else {}


def list_papers(*, trash: bool = False) -> list[dict]:
    """라이브러리 목록 — 화면의 Paper 모양에 맞춘다. 휴지통에 넣은 건 `trash=True` 일 때만."""
    status = settings().get("status") or {}
    hidden = _hidden()
    cols = _collections()
    from . import paperhtml, summaries

    made = set(summaries.load_all())
    html = paperhtml.states()
    running = summaries.running_ids()
    out = []
    for p in scan()["papers"]:
        if (p["id"] in hidden) != trash:
            continue
        out.append({
            "id": p["id"],
            "title": p["title"],
            "authors": p["authors"],
            "venue": p["venue"],
            "field": p["category"],
            "model": "",
            "status": status.get(p["id"], "todo"),
            "source": p["source"],
            "summaryState": "done" if p["id"] in made else "running" if p["id"] in running else "none",
            "access": _ago(p["mtime"]),
            "path": f"vault/{p['path']}",
            "hasPdf": p.get("hasPdf", False),
            "arxiv": p.get("arxiv") or "",
            # arXiv HTML 본문 — done · running · none(arXiv에 없음) · error · missing(아직 안 받음)
            "htmlState": html.get(p["id"], ""),
            "collections": sorted(name for name, ids in cols.items() if p["id"] in ids),
        })
    return out


def body_of(pid: str) -> str:
    """요약 MD로 보여 줄 논문 노트 본문 (앞쪽 메타 제외)."""
    for p in scan()["papers"]:
        if p["id"] == pid:
            return _front(_read(os.path.join(vault_path(), p["path"])))[1]
    raise PapersError(f"없는 논문이에요: {pid}")


def graph() -> dict:
    """노드: 논문 · 프로젝트 · 내 메모. 연결: 인용 · 프로젝트에서 사용 · 내 메모 링크."""
    data = scan()
    hidden = _hidden()
    papers = [p for p in data["papers"] if p["id"] not in hidden]
    # [[링크]]를 논문 id로 — 파일 이름 · 제목 · 별칭 무엇으로 적어도
    alias: dict[str, str] = {}
    for p in papers:
        for name in [p["id"], p["title"], *p["aliases"]]:
            alias[name.strip().lower()] = p["id"]
    project_names = {name for _root, name in registry.load().items()}
    nodes, edges = [], []
    for p in papers:
        nodes.append({"id": p["id"], "kind": "paper", "name": p["title"], "category": p["category"], "meta": p["authors"], "path": p["path"]})
        for c in p["cites"]:
            target = alias.get(c.lower())
            if target and target != p["id"]:
                edges.append({"from": p["id"], "to": target, "kind": "cite"})
    for root, name in sorted(registry.load().items(), key=lambda kv: kv[1]):
        used = projects.load_settings(root).get("papers") or []
        linked = [alias.get(u.lower(), u) for u in used if alias.get(u.lower(), u) in {p["id"] for p in papers}]
        nodes.append({"id": f"project:{name}", "kind": "project", "name": name, "category": "프로젝트", "meta": projects.display_path(root), "path": ""})
        edges += [{"from": f"project:{name}", "to": t, "kind": "use"} for t in linked]
    for n in data["notes"]:
        targets = []
        for link in n["links"]:
            key = link.lower()
            if key in alias:
                targets.append(alias[key])
            elif link in project_names:
                targets.append(f"project:{link}")
        targets = list(dict.fromkeys(targets))
        if not targets:
            continue  # 논문 · 프로젝트와 안 이어진 메모는 그래프에 안 나온다
        nodes.append({"id": n["id"], "kind": "note", "name": n["title"], "category": "내 메모", "meta": f"vault/{n['path']}", "path": n["path"]})
        edges += [{"from": n["id"], "to": t, "kind": "note"} for t in targets]
    # 어디와도 안 이어진 프로젝트는 뺀다
    linked_ids = {e["from"] for e in edges} | {e["to"] for e in edges}
    nodes = [n for n in nodes if n["kind"] != "project" or n["id"] in linked_ids]
    return {"nodes": nodes, "edges": edges, "vault": vault_path()}


# --- 추가 (vault에 새 파일만) --------------------------------------------------

ARXIV_API = "https://export.arxiv.org/api/query?id_list={id}"
ARXIV_PDF = "https://arxiv.org/pdf/{id}"
USER_AGENT = "lab.remote/0.1 (personal research tool)"
MAX_PDF = 100 * 1024 * 1024
_NEW_ID = re.compile(r"\A\d{4}\.\d{4,5}(v\d+)?\Z")
_OLD_ID = re.compile(r"\A[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?\Z")
_BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+')


def arxiv_id(text: str) -> str:
    """링크나 번호에서 arXiv 번호만 (버전 제외). 아니면 PapersError."""
    t = (text or "").strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^?#\s]+)", t)
    if m:
        t = m.group(1)
    t = t.removeprefix("arXiv:").removeprefix("arxiv:").removesuffix(".pdf").strip("/")
    if not (_NEW_ID.match(t) or _OLD_ID.match(t)):
        raise PapersError("arXiv 링크나 번호가 아니에요 (예: https://arxiv.org/abs/1706.03762).")
    return re.sub(r"v\d+\Z", "", t)


def _papers_dir() -> str:
    root = vault_path()
    folder = os.path.join(root, "Papers")
    os.makedirs(os.path.join(folder, "pdf"), exist_ok=True)
    return folder


def _safe_name(title: str) -> str:
    """노트 파일 이름 — "LoRA: Low-Rank …"처럼 콜론 앞이 짧으면 그것만."""
    head = title.split(":")[0].strip()
    name = head if 2 <= len(head) <= 40 else title
    name = _BAD_NAME.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80] or "paper"


def _create(path: str, data: bytes) -> str:
    """없는 이름으로 만든다 — 있으면 " (2)"를 붙인다. 덮어쓰지 않는다."""
    stem, ext = os.path.splitext(path)
    n = 1
    while True:
        target = path if n == 1 else f"{stem} ({n}){ext}"
        try:
            with open(target, "xb") as fh:
                fh.write(data)
            return target
        except FileExistsError:
            n += 1
            if n > 99:
                raise PapersError("같은 이름이 너무 많아요.") from None


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _note(meta: dict, body: str) -> bytes:
    lines = ["---"]
    for key, value in meta.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f"  - {_yaml(str(v))}" for v in value]
        else:
            lines.append(f"{key}: {_yaml(str(value)) if not isinstance(value, int) else value}")
    lines.append("---")
    return ("\n".join(lines) + "\n" + body).encode("utf-8")


def _get(url: str, *, limit: int, timeout: int = 30) -> bytes:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = res.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise PapersError(f"arXiv가 거절했어요 ({exc.code}). 잠시 뒤 다시 해 주세요.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PapersError(f"arXiv에 닿지 못했어요: {getattr(exc, 'reason', exc)}") from None
    if len(data) > limit:
        raise PapersError("파일이 너무 커요.")
    return data


def _existing_arxiv(aid: str) -> dict | None:
    for p in scan()["papers"]:
        if arxiv_id_or_none(p.get("arxiv") or "") == aid:
            return p
    return None


def arxiv_id_or_none(text: str) -> str | None:
    try:
        return arxiv_id(text)
    except PapersError:
        return None


def add_arxiv(link: str, *, fetch=_get) -> dict:
    """arXiv 링크로 논문 노트(+ PDF)를 만든다. 이미 있으면 그 논문을 돌려준다."""
    import xml.etree.ElementTree as ET

    aid = arxiv_id(link)
    found = _existing_arxiv(aid)
    if found:
        return {"id": found["id"], "created": False, "path": f"vault/{found['path']}"}
    xml = fetch(ARXIV_API.format(id=aid), limit=2 * 1024 * 1024)
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise PapersError("arXiv 답을 읽지 못했어요.") from None
    entry = root.find("a:entry", ns)
    entry_id = (entry.findtext("a:id", "", ns) if entry is not None else "") or ""
    if entry is None or "/abs/" not in entry_id:
        raise PapersError(f"arXiv에 없는 번호예요: {aid}")
    clean = lambda t: re.sub(r"\s+", " ", t or "").strip()  # noqa: E731
    title = clean(entry.findtext("a:title", "", ns)) or aid
    authors = [clean(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)]
    published = entry.findtext("a:published", "", ns) or ""
    primary = entry.find("x:primary_category", ns)
    journal = clean(entry.findtext("x:journal_ref", "", ns))
    abstract = clean(entry.findtext("a:summary", "", ns))

    folder = _papers_dir()
    name = _safe_name(title)
    pdf_rel = ""
    try:
        pdf = fetch(ARXIV_PDF.format(id=aid), limit=MAX_PDF, timeout=120)
        if pdf.startswith(b"%PDF-"):
            made = _create(os.path.join(folder, "pdf", f"{name}.pdf"), pdf)
            pdf_rel = os.path.relpath(made, vault_path()).replace(os.sep, "/")
    except PapersError:
        pdf_rel = ""  # PDF는 못 받아도 노트는 만든다
    meta = {
        "title": title,
        "authors": authors,
        "year": int(published[:4]) if published[:4].isdigit() else "",
        "venue": journal or "arXiv",
        "category": primary.get("term") if primary is not None else "",
        "arxiv": aid,
        "pdf": pdf_rel,
        "cites": [],
    }
    body = "## 초록\n\n" + abstract + "\n" if abstract else ""
    note = _create(os.path.join(folder, f"{name}.md"), _note(meta, body))
    stem = os.path.splitext(os.path.basename(note))[0]
    return {"id": stem, "created": True, "path": "vault/" + os.path.relpath(note, vault_path()).replace(os.sep, "/"), "pdf": bool(pdf_rel)}


def add_pdf(filename: str, data: bytes) -> dict:
    """올린 PDF를 vault에 두고 파일 이름으로 노트를 만든다."""
    if not data.startswith(b"%PDF-"):
        raise PapersError("PDF 파일이 아니에요.")
    if len(data) > MAX_PDF:
        raise PapersError("PDF가 너무 커요 (100MB까지).")
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    name = _safe_name(base) if base else "paper"
    folder = _papers_dir()
    made = _create(os.path.join(folder, "pdf", f"{name}.pdf"), data)
    pdf_rel = os.path.relpath(made, vault_path()).replace(os.sep, "/")
    meta = {"title": base or name, "authors": [], "year": "", "venue": "", "category": "", "pdf": pdf_rel, "cites": []}
    note = _create(os.path.join(folder, f"{name}.md"), _note(meta, ""))
    stem = os.path.splitext(os.path.basename(note))[0]
    return {"id": stem, "created": True, "path": "vault/" + os.path.relpath(note, vault_path()).replace(os.sep, "/"), "pdf": True}


def pdf_rel(pid: str) -> str:
    """vault 안 PDF의 상대 경로 (없으면 "")."""
    try:
        return os.path.relpath(pdf_of(pid), paths.real(vault_path())).replace(os.sep, "/")
    except PapersError:
        return ""


def pdf_of(pid: str) -> str:
    """논문 노트의 `pdf:`가 가리키는 파일 (vault 안만)."""
    for p in scan()["papers"]:
        if p["id"] == pid:
            meta, _ = _front(_read(os.path.join(vault_path(), p["path"])))
            rel = str(meta.get("pdf") or "").strip()
            rel = WIKI_RE.sub(lambda m: m.group(1), rel)  # [[pdf/x.pdf]]로 적어도
            if not rel:
                break
            root = paths.real(vault_path())
            for cand in (os.path.join(root, rel), os.path.join(root, "Papers", rel)):
                target = paths.real(cand)
                if paths.is_inside(root, target) and os.path.isfile(target) and target.lower().endswith(".pdf"):
                    return target
            break
    raise PapersError("이 논문에는 PDF가 없어요.")


# --- 휴지통 · 모음 · BibTeX (lab.remote에만 기록 — vault는 그대로) ----------------------

COLLECTION_RE = re.compile(r"\A[^/\\\x00-\x1f]{1,40}\Z")


def _known(pid: str) -> None:
    if pid not in {p["id"] for p in scan()["papers"]}:
        raise PapersError(f"없는 논문이에요: {pid}")


def set_trashed(pid: str, on: bool) -> dict:
    """휴지통 — 목록 · 그래프에서만 뺀다. vault 파일은 그대로다."""
    _known(pid)
    data = settings()
    hidden = [x for x in (data.get("hidden") or []) if x != pid]
    if on:
        hidden.append(pid)
    data["hidden"] = hidden
    _save(data)
    return {"id": pid, "trashed": on}


def collections() -> list[dict]:
    cols = _collections()
    known = {p["id"] for p in scan()["papers"]} - _hidden()
    return [{"name": n, "count": len([i for i in ids if i in known])} for n, ids in sorted(cols.items())]


def add_collection(name: str) -> list[dict]:
    name = (name or "").strip()
    if not COLLECTION_RE.match(name):
        raise PapersError("모음 이름은 1~40자, / 없이 적어 주세요.")
    data = settings()
    cols = data.setdefault("collections", {})
    if name in cols:
        raise PapersError(f"이미 있는 모음이에요: {name}")
    cols[name] = []
    _save(data)
    return collections()


def remove_collection(name: str) -> list[dict]:
    """모음만 지운다 — 안의 논문은 그대로."""
    data = settings()
    if name not in (data.get("collections") or {}):
        raise PapersError(f"없는 모음이에요: {name}")
    del data["collections"][name]
    _save(data)
    return collections()


def set_in_collection(name: str, ids: list[str], on: bool) -> list[dict]:
    data = settings()
    cols = data.get("collections") or {}
    if name not in cols:
        raise PapersError(f"없는 모음이에요: {name}")
    for pid in ids:
        _known(pid)
    current = [x for x in cols[name] if x not in ids]
    cols[name] = current + list(dict.fromkeys(ids)) if on else current
    data["collections"] = cols
    _save(data)
    return collections()


def _bib_key(p: dict) -> str:
    first = (p.get("authorList") or ["paper"])[0]
    last = re.sub(r"[^A-Za-z]", "", first.split()[-1] if first.split() else first) or "paper"
    word = re.sub(r"[^A-Za-z]", "", (p["title"].split() or ["x"])[0]) or "x"
    return f"{last.lower()}{p.get('year') or ''}{word.lower()}"


def bibtex(ids: list[str]) -> str:
    """고른 논문의 BibTeX — 노트 앞쪽 메타로 만든다."""
    by_id = {p["id"]: p for p in scan()["papers"]}
    out = []
    for pid in ids:
        p = by_id.get(pid)
        if not p:
            continue
        esc = lambda t: str(t).replace("{", "\\{").replace("}", "\\}")  # noqa: E731
        fields = [("title", "{" + esc(p["title"]) + "}"), ("author", " and ".join(esc(a) for a in p.get("authorList") or []))]
        if p.get("year"):
            fields.append(("year", p["year"]))
        if p.get("arxiv"):
            fields += [("eprint", p["arxiv"]), ("archivePrefix", "arXiv")]
            if p.get("venue") in ("", "arXiv"):
                fields.append(("journal", f"arXiv preprint arXiv:{p['arxiv']}"))
        if p.get("venue") and p.get("venue") != "arXiv":
            fields.append(("booktitle", esc(p["venue"])))
        body = ",\n".join(f"  {k:<13} = {{{v}}}" for k, v in fields if v)
        out.append(f"@article{{{_bib_key(p)},\n{body}\n}}")
    return "\n\n".join(out) + ("\n" if out else "")


def add_reference(title: str, authors: str = "", year: str = "", venue: str = "") -> dict:
    """arXiv 번호가 없는 참고문헌 — 메타만으로 노트를 만든다 (PDF 없음)."""
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title:
        raise PapersError("제목이 없어요.")
    for p in scan()["papers"]:
        if p["title"].strip().lower() == title.lower():
            return {"id": p["id"], "created": False, "path": f"vault/{p['path']}"}
    folder = _papers_dir()
    names = [a.strip() for a in re.split(r",| and |&", authors or "") if a.strip() and a.strip().lower() not in ("et al.", "et al")]
    meta = {"title": title, "authors": names, "year": int(year) if str(year).isdigit() else "", "venue": venue, "category": "", "cites": []}
    note = _create(os.path.join(folder, f"{_safe_name(title)}.md"), _note(meta, ""))
    stem = os.path.splitext(os.path.basename(note))[0]
    return {"id": stem, "created": True, "path": "vault/" + os.path.relpath(note, vault_path()).replace(os.sep, "/"), "pdf": False}
