"""실험 프로젝트 레지스트리와 서버 쪽 저장 위치.

훅은 사용자 설정(`~/.claude/settings.json`)에 등록되므로 **모든 프로젝트에서**
뜬다. 그래서 "여기가 등록된 실험 프로젝트인가" 를 먼저 판정해야 하고,
그 판정 근거가 이 레지스트리다. 프로젝트 안에 두면 AI 가 고쳐서 자기 정책을
갈아탈 수 있으니 서버 쪽(`server/data/`)에 둔다.

표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

import fcntl
import json
import os
import re

from . import paths

__all__ = [
    "InvalidName",
    "valid_name",
    "data_dir",
    "projects_root",
    "projects_file",
    "policy_path",
    "runstate_path",
    "pending_dir",
    "load",
    "register",
    "unregister",
    "lookup",
    "root_of",
    "write_json",
]

#: 프로젝트 이름. 그대로 파일 이름이 되므로 경로 조각이 섞이면 안 된다.
NAME_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?\Z")

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InvalidName(ValueError):
    """프로젝트 이름이 규칙에 안 맞을 때."""


def valid_name(name: str) -> str:
    """이름을 검사해 그대로 돌려준다.

    `../../x` 같은 값이 `policies/<이름>.json` 으로 들어가면 정책 파일을
    프로젝트 밖 아무 곳에나 쓸 수 있게 되므로 여기서 막는다.
    """
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise InvalidName(
            f"프로젝트 이름이 규칙에 안 맞아요: {name!r} · "
            "영소문자·숫자로 시작하고 끝나며 . _ - 만 섞을 수 있어요 (최대 64자)"
        )
    return name


def data_dir() -> str:
    """런타임 상태 폴더. `.gitignore` 에 걸려 있어 커밋되지 않는다."""
    return os.path.abspath(os.environ.get("LAB_DATA_DIR") or os.path.join(_SERVER_DIR, "data"))


def projects_root() -> str:
    """실험 프로젝트들의 부모 폴더. 기본 `~/projects`."""
    return paths.real(os.environ.get("LAB_PROJECTS_DIR") or "~/projects")


def projects_file() -> str:
    return os.path.join(data_dir(), "projects.json")


def policy_path(name: str) -> str:
    return os.path.join(data_dir(), "policies", f"{valid_name(name)}.json")


def runstate_path(name: str) -> str:
    return os.path.join(data_dir(), "runstate", f"{valid_name(name)}.json")


def pending_dir(name: str) -> str:
    return os.path.join(data_dir(), "pending", valid_name(name))


def write_json(path: str, data) -> None:
    """원자적 쓰기. 반쯤 쓰인 JSON 이 남으면 훅이 fail-closed 로 멈춘다."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load() -> dict[str, str]:
    """`{프로젝트 루트 절대경로: 이름}`. 파일이 없거나 깨졌으면 빈 dict."""
    try:
        with open(projects_file(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    projects = raw.get("projects") if isinstance(raw, dict) else None
    if not isinstance(projects, dict):
        return {}
    return {str(k): str(v) for k, v in projects.items()}


def _save(projects: dict[str, str]) -> None:
    write_json(projects_file(), {"version": 1, "projects": projects})


def register(root: str, name: str) -> str:
    """프로젝트를 등록하고 해소된 루트 경로를 돌려준다.

    같은 이름이 다른 경로에 이미 등록돼 있으면 거절한다 — 정책 파일이
    엉뚱한 프로젝트에 붙는 사고를 막는다.
    """
    valid_name(name)
    root_real = paths.real(root)
    os.makedirs(data_dir(), exist_ok=True)
    lock = os.path.join(data_dir(), ".projects.lock")
    with open(lock, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            projects = load()
            for other_root, other_name in projects.items():
                if other_name == name and other_root != root_real:
                    raise InvalidName(
                        f"이름 {name!r} 은 이미 {other_root} 에 쓰고 있어요. "
                        "다른 이름을 쓰거나 먼저 등록을 지워 주세요."
                    )
            projects[root_real] = name
            _save(projects)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return root_real


def unregister(name: str) -> bool:
    """등록을 지운다. 정책 파일은 건드리지 않는다."""
    with open(os.path.join(data_dir(), ".projects.lock"), "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            projects = load()
            left = {r: n for r, n in projects.items() if n != name}
            if len(left) == len(projects):
                return False
            _save(left)
            return True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def lookup(path: str) -> tuple[str, str] | None:
    """경로(보통 훅의 `cwd`)가 속한 프로젝트의 `(루트, 이름)`.

    등록된 프로젝트가 아니면 `None` — 훅은 간섭하지 않고 `defer` 한다.
    중첩된 경우 가장 깊은 루트가 이긴다.
    """
    target = paths.real(path)
    best: tuple[str, str] | None = None
    for root, name in load().items():
        if paths.is_inside(root, target) and (best is None or len(root) > len(best[0])):
            best = (root, name)
    return best


def root_of(name: str) -> str | None:
    for root, other in load().items():
        if other == name:
            return root
    return None
