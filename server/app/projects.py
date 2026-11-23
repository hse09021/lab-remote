"""프로젝트 — 등록·해제, `<프로젝트>/.labremote/`, 프로젝트 설정, 고정.

lab.remote 가 연구 프로젝트 안에 만드는 것은 `.labremote/` **하나뿐이다**
(PLAN 1장). 그 안의 `.gitignore` 가 `*` 한 줄이라 폴더가 스스로 git에서
빠진다 — 프로젝트의 `.gitignore` 는 건드리지 않는다.

"repo 에 같이 올리기" 를 켜면 그 `.gitignore` 만 바꿔서 `settings.json` 과
`scenarios/` 가 추적되게 한다(PLAN 3장).

등록 목록은 `registry` 가, 화면 상태(고정)는 데이터 폴더의 `ui.json` 이 갖는다.
"""

from __future__ import annotations

import json
import os
import re
import shutil

from . import paths, registry

__all__ = [
    "ProjectError",
    "LABREMOTE_DIR",
    "DEFAULT_SETTINGS",
    "labremote_dir",
    "ensure_labremote",
    "gitignore_text",
    "load_settings",
    "save_settings",
    "slug",
    "register",
    "unregister",
    "list_projects",
    "require",
    "pins",
    "set_pin",
    "activity_at",
    "display_path",
]

LABREMOTE_DIR = ".labremote"

#: `.labremote/.gitignore` — 기본은 폴더 전체를 git에서 뺀다
GITIGNORE_PRIVATE = "# lab.remote 가 만든 폴더예요. 통째로 git에서 빠져요.\n*\n"
#: "repo 에 같이 올리기" — `settings.json` 과 `scenarios/*.json` 만 추적
GITIGNORE_SHARED = (
    "# lab.remote 가 만든 폴더예요. 설정과 Scenario 만 같이 올려요.\n"
    "*\n"
    "!.gitignore\n"
    "!settings.json\n"
    "!scenarios/\n"
    "!scenarios/*.json\n"
)

DEFAULT_SETTINGS = {
    "version": 1,
    "condaEnv": "",
    "commands": [],
    "metricGlobs": [],
    "share": False,
    "papers": [],
}

ENV_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
MAX_COMMANDS = 20
MAX_GLOBS = 20
MAX_TEXT = 500


class ProjectError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


# --- .labremote/ -------------------------------------------------------------


def labremote_dir(root: str) -> str:
    return os.path.join(paths.real(root), LABREMOTE_DIR)


def gitignore_text(share: bool) -> str:
    return GITIGNORE_SHARED if share else GITIGNORE_PRIVATE


def _write_text(path: str, text: str) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def ensure_labremote(root: str) -> dict:
    """`.labremote/` 와 `.gitignore`·`settings.json` 을 만든다. 있으면 그대로 둔다.

    `.labremote` 가 심볼릭 링크거나 파일이면 거절한다 — 링크를 따라가 프로젝트
    밖에 쓰지 않으려고.
    """
    folder = labremote_dir(root)
    if os.path.islink(folder) or (os.path.exists(folder) and not os.path.isdir(folder)):
        raise ProjectError(f"{LABREMOTE_DIR} 가 폴더가 아니에요 (링크나 파일). 직접 확인해 주세요.")
    made = not os.path.exists(folder)
    os.makedirs(folder, exist_ok=True)
    settings_path = os.path.join(folder, "settings.json")
    if not os.path.exists(settings_path):
        registry.write_json(settings_path, dict(DEFAULT_SETTINGS))
    settings = load_settings(root)
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.exists(ignore):
        _write_text(ignore, gitignore_text(bool(settings.get("share"))))
    return {"path": folder, "made": made}


def _clean_list(value, *, limit: int, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectError(f"{field} 는 목록이어야 해요.")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ProjectError(f"{field} 에 글자가 아닌 값이 있어요.")
        text = item.strip()
        if not text:
            continue
        if len(text) > MAX_TEXT or "\x00" in text or "\n" in text:
            raise ProjectError(f"{field} 의 한 줄이 너무 길거나 줄바꿈이 있어요.")
        if text not in out:
            out.append(text)
    if len(out) > limit:
        raise ProjectError(f"{field} 는 {limit}개까지 둘 수 있어요.")
    return out


def _normalize(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ProjectError("설정은 JSON 객체여야 해요.")
    env = raw.get("condaEnv") or ""
    if not isinstance(env, str) or (env and not ENV_RE.match(env)):
        raise ProjectError(f"conda 환경 이름이 규칙에 안 맞아요: {env!r}")
    globs = _clean_list(raw.get("metricGlobs"), limit=MAX_GLOBS, field="지표 파일 규칙")
    for g in globs:
        if g.startswith("/") or ".." in g.split("/"):
            raise ProjectError(f"지표 파일 규칙은 프로젝트 안 상대 경로여야 해요: {g!r}")
    return {
        "version": 1,
        "condaEnv": env,
        "commands": _clean_list(raw.get("commands"), limit=MAX_COMMANDS, field="자주 쓰는 명령"),
        "metricGlobs": globs,
        "share": bool(raw.get("share")),
        # 이 프로젝트가 쓰는 논문 (vault 논문 노트 이름) — 지식그래프의 "프로젝트에서 사용"
        "papers": _clean_list(raw.get("papers"), limit=100, field="쓰는 논문"),
    }


def load_settings(root: str) -> dict:
    """`.labremote/settings.json`. 없거나 깨졌으면 기본값 (깨진 파일은 고치지 않는다)."""
    try:
        with open(os.path.join(labremote_dir(root), "settings.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
        return _normalize({**DEFAULT_SETTINGS, **raw})
    except (OSError, json.JSONDecodeError, ProjectError):
        return dict(DEFAULT_SETTINGS)


def save_settings(root: str, raw: dict) -> dict:
    """검사해서 쓰고, `share` 에 맞춰 `.labremote/.gitignore` 를 다시 쓴다."""
    clean = _normalize(raw)
    ensure_labremote(root)
    folder = labremote_dir(root)
    registry.write_json(os.path.join(folder, "settings.json"), clean)
    _write_text(os.path.join(folder, ".gitignore"), gitignore_text(clean["share"]))
    return clean


# --- 등록 ---------------------------------------------------------------------


def slug(text: str) -> str:
    """폴더 이름에서 프로젝트 이름 후보를 만든다."""
    s = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-._")
    return s[:64].rstrip("-._") or "project"


def _forbidden_roots() -> list[str]:
    home = paths.real("~")
    server = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.sep, home, paths.real(registry.data_dir()), paths.real(os.path.dirname(server))]


def register(path: str, name: str = "") -> dict:
    """폴더를 등록하고 `.labremote/` 를 만든다.

    거절: 없는 폴더 · `/`·홈 폴더 자체 · lab.remote 저장소와 데이터 폴더 ·
    이미 등록된 프로젝트와 겹치는(안에 있거나 품는) 폴더.
    """
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise ProjectError("폴더 경로를 적어 주세요.")
    root = paths.real(path.strip())
    if not os.path.isdir(root):
        raise ProjectError(f"폴더가 없어요: {root}")
    for bad in _forbidden_roots():
        if root == bad or paths.is_inside(root, bad):
            raise ProjectError(f"이 폴더는 등록할 수 없어요: {root}")
    if paths.is_inside(paths.real(registry.data_dir()), root):
        raise ProjectError("lab.remote 데이터 폴더 안은 등록할 수 없어요.")
    for other_root, other_name in registry.load().items():
        if other_root == root:
            raise ProjectError(f"이미 {other_name!r} 로 등록돼 있어요.")
        if paths.is_inside(other_root, root) or paths.is_inside(root, other_root):
            raise ProjectError(f"등록된 프로젝트 {other_name!r} 와 겹쳐요 ({other_root}).")
    name = (name or "").strip() or slug(os.path.basename(root))
    try:
        registry.valid_name(name)
    except registry.InvalidName as exc:
        raise ProjectError(str(exc)) from None
    ensure_labremote(root)
    try:
        registry.register(root, name)
    except registry.InvalidName as exc:
        raise ProjectError(str(exc)) from None
    return {"name": name, "root": root}


def require(name: str) -> str:
    """등록된 이름의 루트. 없으면 `ProjectError`."""
    root = registry.root_of(name) if isinstance(name, str) else None
    if not root:
        raise ProjectError(f"등록된 프로젝트가 아니에요: {name!r}")
    return root


def unregister(name: str, *, remove_labremote: bool = False) -> dict:
    """등록을 지운다. `remove_labremote` 면 `.labremote/` 도 지운다(기본은 남김).

    지우는 건 **`.labremote` 폴더 하나**다. 링크면 따라가지 않고 거절한다.
    """
    root = require(name)
    removed = False
    if remove_labremote:
        folder = labremote_dir(root)
        if os.path.islink(folder):
            raise ProjectError(f"{LABREMOTE_DIR} 가 링크라 지우지 않았어요.")
        trees = os.path.join(folder, "worktrees")
        if os.path.isdir(trees) and os.listdir(trees):
            # worktree 안에는 커밋 안 한 작업이 있을 수 있다 — 통째로 지우지 않는다
            raise ProjectError(
                "`.labremote/worktrees/` 에 worktree 가 남아 있어요. 먼저 정리하거나 "
                "`.labremote/` 는 남겨 두고 해제해 주세요."
            )
        if os.path.isdir(folder):
            shutil.rmtree(folder)
            removed = True
    registry.unregister(name)
    set_pin(name, False)
    return {"name": name, "root": root, "removedLabremote": removed}


# --- 화면 상태 (고정) -------------------------------------------------------------


def _ui_path() -> str:
    return os.path.join(registry.data_dir(), "ui.json")


def _load_ui() -> dict:
    try:
        with open(_ui_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def pins() -> list[str]:
    value = _load_ui().get("pins")
    return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []


def set_pin(name: str, pinned: bool) -> list[str]:
    ui = _load_ui()
    current = pins()
    if pinned and name not in current:
        current.append(name)
    if not pinned:
        current = [p for p in current if p != name]
    ui["pins"] = current
    registry.write_json(_ui_path(), ui)
    return current


# --- 목록 ---------------------------------------------------------------------


def activity_at(root: str) -> float:
    """"최근 활동" 정렬용 시각. 폴더·git 인덱스·`.labremote` 중 가장 늦은 것."""
    best = 0.0
    for rel in ("", ".git/index", ".git/HEAD", f"{LABREMOTE_DIR}/settings.json"):
        try:
            best = max(best, os.stat(os.path.join(root, rel)).st_mtime)
        except OSError:
            pass
    return best


def display_path(root: str) -> str:
    home = paths.real("~")
    return "~" + root[len(home):] if paths.is_inside(home, root) and root != home else root


def list_projects() -> list[dict]:
    pinned = set(pins())
    out = []
    for root, name in registry.load().items():
        out.append(
            {
                "name": name,
                "root": root,
                "path": display_path(root),
                "exists": os.path.isdir(root),
                "pinned": name in pinned,
                "activityAt": activity_at(root) or None,
            }
        )
    out.sort(key=lambda p: -(p["activityAt"] or 0))
    return out
