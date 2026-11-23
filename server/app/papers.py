"""Papers — vault 를 **읽기만** 해서 라이브러리 목록과 지식그래프를 만든다 (8단계).

vault (Obsidian 폴더):
    <vault>/Papers/*.md   논문 노트. 앞쪽 메타(--- … ---)에 title · authors · year · venue ·
                          category · arxiv · cites([[링크]] 목록)
    <vault>/그 밖의 *.md   내 메모. 본문의 [[링크]] 가 논문이나 프로젝트를 가리키면 그래프에 나온다

- vault 위치는 사람이 정한다(설정, 2026-11-23). 정하지 않으면 데이터 폴더의 `vault/`.
- **노트 파일을 고치지 않는다.** 읽음 상태처럼 lab.remote 가 기억할 것은 데이터 폴더의
  `papers.json` 에 둔다.
- "프로젝트에서 사용" 은 프로젝트 설정의 `papers` 목록(사람이 고름)에서 온다.
- PDF 파싱 · AI 요약 · 리더 본문은 아직 없다(mock).
"""

from __future__ import annotations

import json
import os
import re
import time

from . import paths, projects, registry

__all__ = ["PapersError", "settings", "set_vault", "vault_path", "scan", "list_papers", "graph", "set_status", "body_of"]

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
            raise PapersError("홈 폴더나 / 전체는 vault 로 쓸 수 없어요.")
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
    """앞쪽 메타 `--- … ---` 를 아주 단순하게 읽는다 (key: value · key: [a, b] · - 목록)."""
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
    """vault 를 훑는다. 바뀐 게 없으면(파일 수 · 최근 수정 시각) 캐시를 쓴다."""
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


def list_papers() -> list[dict]:
    """라이브러리 목록 — 화면의 Paper 모양에 맞춘다."""
    status = settings().get("status") or {}
    out = []
    for p in scan()["papers"]:
        out.append({
            "id": p["id"],
            "title": p["title"],
            "authors": p["authors"],
            "venue": p["venue"],
            "field": p["category"],
            "model": "",
            "status": status.get(p["id"], "todo"),
            "source": p["source"],
            "summaryState": "done" if p["hasBody"] else "none",
            "access": _ago(p["mtime"]),
            "path": f"vault/{p['path']}",
        })
    return out


def body_of(pid: str) -> str:
    """요약 MD 로 보여 줄 논문 노트 본문 (앞쪽 메타 제외)."""
    for p in scan()["papers"]:
        if p["id"] == pid:
            return _front(_read(os.path.join(vault_path(), p["path"])))[1]
    raise PapersError(f"없는 논문이에요: {pid}")


def graph() -> dict:
    """노드: 논문 · 프로젝트 · 내 메모. 연결: 인용 · 프로젝트에서 사용 · 내 메모 링크."""
    data = scan()
    papers = data["papers"]
    # [[링크]] 를 논문 id 로 — 파일 이름 · 제목 · 별칭 무엇으로 적어도
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
