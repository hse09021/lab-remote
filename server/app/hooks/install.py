"""훅 설치 — 래퍼 렌더링 + `~/.claude/settings.json` 병합.

훅은 프로젝트 `.claude/settings.json` 이 아니라 **사용자 설정**에 등록한다.
AI 가 프로젝트 안에서 훅 설정을 고치지 못하게 하려는 것이고, 대신 모든
프로젝트에서 뜨게 되므로 래퍼가 "실험 프로젝트 밖이면 건너뛰기" 를 맡는다.

모드 두 가지:
  dump    — 모든 이벤트를 `app.hooks.debug` 로 보내 stdin 을 그대로 받아 적는다.
            설치된 Claude Code 의 실제 필드명을 실측하는 단계(구현 순서 4).
  enforce — 진짜 판정기를 건다. 판정 모듈이 아직 없으면 설치를 거절한다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from datetime import datetime

from .. import paths, registry

__all__ = [
    "MARKER",
    "SHELL_LIMITATION_NOTE",
    "settings_path",
    "wrapper_path",
    "render_wrapper",
    "install",
    "uninstall",
    "status",
    "limitations",
    "main",
]

#: 우리 항목을 알아보는 표식. command 문자열에 들어 있다.
MARKER = "labremote-hook.sh"

#: 생성기의 CLAUDE.md 와 운영 문서에 똑같이 들어가야 하는 한 줄.
SHELL_LIMITATION_NOTE = (
    "Claude Code 는 항상 이 프로젝트 폴더 안에서 켜 주세요. "
    "폴더 밖에서 켜면 권한 훅이 뜨지 않아 잠긴 항목이 막히지 않아요."
)

#: `Read|Grep` 은 **비밀 파일만** 보려고 들어 있다 (`classify.SECRET_READ_TOOLS`).
#: 그 밖의 읽기는 판정하지 않는다 — 전면 차단은 소음만 크고 막을 게 없다.
TOOL_MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch|WebSearch|Read|Grep"
HOOK_TIMEOUT = 10

#: (이벤트, matcher, 모듈, onFailure)
ENFORCE_EVENTS = [
    ("PreToolUse", TOOL_MATCHER, "app.hooks.pretooluse", "block"),
    ("PostToolUse", TOOL_MATCHER, "app.hooks.posttooluse", "continue"),
    # 거부로 턴이 끊기면 Stop 이 안 돈다. 새 프롬프트에서 이전 턴 대기 건을
    # 마감하는 게 이 훅의 전부다 (app/hooks/userprompt.py 의 설명).
    ("UserPromptSubmit", None, "app.hooks.userprompt", "continue"),
    ("Stop", None, "app.hooks.stop", "continue"),
    # 서브에이전트는 메인 턴이 끝나도 계속 돈다. 그 대기 건은 이 훅이 닫는다
    # (app/hooks/subagentstop.py 의 설명).
    ("SubagentStop", None, "app.hooks.subagentstop", "continue"),
    ("SessionEnd", None, "app.hooks.sessionend", "continue"),
]

#: 덤프는 무엇도 막지 않는다. 판정 없이 받아 적기만 한다.
DUMP_EVENTS = [
    ("PreToolUse", ".*", "app.hooks.debug", "continue"),
    ("PostToolUse", ".*", "app.hooks.debug", "continue"),
    ("UserPromptSubmit", None, "app.hooks.debug", "continue"),
    ("Stop", None, "app.hooks.debug", "continue"),
    ("SubagentStop", None, "app.hooks.debug", "continue"),
    ("SessionEnd", None, "app.hooks.debug", "continue"),
]

MODES = {"dump": DUMP_EVENTS, "enforce": ENFORCE_EVENTS}


def expected_events(mode: str = "enforce") -> set[str]:
    """그 모드에서 등록돼 있어야 하는 이벤트 이름.

    `doctor` 가 이걸로 "설치는 했는데 그 뒤에 이벤트가 늘어난" 경우를 잡는다.
    UserPromptSubmit 이 그 예다 — 재설치하지 않으면 조용히 빠져 있다.
    """
    return {event for event, *_ in MODES.get(mode, ENFORCE_EVENTS)}

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def server_dir() -> str:
    return _SERVER_DIR


def settings_path() -> str:
    """사용자 설정 파일. 테스트는 `LAB_CLAUDE_SETTINGS` 로 돌린다."""
    override = os.environ.get("LAB_CLAUDE_SETTINGS")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def wrapper_path() -> str:
    """렌더된 래퍼. 머신마다 다른 절대 경로가 박히므로 커밋하지 않는다."""
    return os.path.join(registry.data_dir(), "bin", MARKER)


def template_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "templates",
        "labremote-hook.sh.tmpl",
    )


def state_path() -> str:
    """설치 기록 (모드·백업 경로 등)."""
    return os.path.join(registry.data_dir(), "hooks_install.json")


def render_wrapper(python: str | None = None, roots: str | None = None) -> str:
    """래퍼를 만들고 경로를 돌려준다. 값은 설치 시점에 해소해 박는다."""
    py = paths.real(python or sys.executable)
    root = paths.real(roots) if roots else registry.projects_root()

    with open(template_path(), encoding="utf-8") as fh:
        body = fh.read()
    # string.Template 을 쓰면 셸의 $dir·$PWD 까지 건드리므로 토큰 치환으로 한다.
    for token, value in (("__PY__", py), ("__SERVER_DIR__", server_dir()), ("__ROOTS__", root)):
        if "'" in value:
            raise ValueError(f"경로에 작은따옴표가 있어요: {value!r}")
        body = body.replace(token, value)

    dst = wrapper_path()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = f"{dst}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, dst)
    return dst


# --- settings.json ---------------------------------------------------------


def _load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{settings_path()} 를 읽을 수 없어요 ({exc.lineno}행). 고치고 다시 해 주세요."
        ) from None
    return data if isinstance(data, dict) else {}


def _backup() -> str | None:
    """고치기 전에 원본을 복사해 둔다. 없으면 None."""
    src = settings_path()
    if not os.path.exists(src):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = f"{src}.labremote-{stamp}.bak"
    shutil.copy2(src, dst)
    return dst


def _write_settings(data: dict) -> None:
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _is_ours(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        MARKER in str(h.get("command", ""))
        for h in (entry.get("hooks") or [])
        if isinstance(h, dict)
    )


def _strip_ours(data: dict) -> int:
    """우리 항목만 빼낸다. 사용자가 손으로 넣은 훅은 건드리지 않는다."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not _is_ours(e)]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)
    return removed


def _entry(matcher: str | None, wrapper: str, module: str, on_failure: str) -> dict:
    entry: dict = {}
    if matcher is not None:
        entry["matcher"] = matcher
    entry["hooks"] = [
        {
            "type": "command",
            "command": f'"{wrapper}" {module}',
            "timeout": HOOK_TIMEOUT,
            "onFailure": on_failure,
        }
    ]
    return entry


def install(mode: str = "enforce", python: str | None = None, roots: str | None = None) -> dict:
    """래퍼를 만들고 사용자 설정에 등록한다. 되돌리려면 `uninstall()`."""
    if mode not in MODES:
        raise ValueError(f"모르는 모드예요: {mode!r} · dump 또는 enforce")

    events = MODES[mode]
    if mode == "enforce":
        missing = [
            module
            for _, _, module, _ in events
            if not os.path.exists(
                os.path.join(server_dir(), *module.split(".")) + ".py"
            )
        ]
        if missing:
            raise RuntimeError(
                "아직 없는 판정 모듈이 있어서 enforce 로는 설치하지 않았어요: "
                + ", ".join(missing)
                + " · 먼저 --mode dump 로 필드명을 실측해 주세요."
            )

    wrapper = render_wrapper(python=python, roots=roots)
    backup = _backup()
    data = _load_settings()
    replaced = _strip_ours(data)

    hooks = data.setdefault("hooks", {})
    for event, matcher, module, on_failure in events:
        hooks.setdefault(event, []).append(_entry(matcher, wrapper, module, on_failure))
    _write_settings(data)

    info = {
        "mode": mode,
        "wrapper": wrapper,
        "settings": settings_path(),
        "backup": backup,
        "replaced": replaced,
        "python": paths.real(python or sys.executable),
        "roots": paths.real(roots) if roots else registry.projects_root(),
        "events": [e for e, *_ in events],
        "installedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    registry.write_json(state_path(), info)
    return info


def uninstall() -> dict:
    """우리 항목만 뺀다. 사용자가 손으로 넣은 설정은 그대로 둔다."""
    backup = _backup()
    data = _load_settings()
    removed = _strip_ours(data)
    if removed:
        _write_settings(data)

    previous = None
    try:
        with open(state_path(), encoding="utf-8") as fh:
            previous = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pass
    if os.path.exists(state_path()):
        os.remove(state_path())

    return {
        "removed": removed,
        "settings": settings_path(),
        "backup": backup,
        "previousBackup": (previous or {}).get("backup"),
    }


def status() -> dict:
    data = _load_settings()
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    installed = {
        event: [e for e in entries if _is_ours(e)]
        for event, entries in hooks.items()
        if isinstance(entries, list) and any(_is_ours(e) for e in entries)
    }
    state = None
    try:
        with open(state_path(), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "settings": settings_path(),
        "installed": installed,
        "wrapper": wrapper_path(),
        "wrapperExists": os.path.exists(wrapper_path()),
        "roots": registry.projects_root(),
        "state": state,
    }


def limitations() -> list[str]:
    """`doctor` 와 `hooks status` 가 그대로 찍어 주는 한계 안내."""
    return [
        SHELL_LIMITATION_NOTE,
        f"훅이 도는 범위는 설치할 때 박은 프로젝트 루트 아래뿐이에요: {registry.projects_root()} "
        "· 바꾸려면 labremote hooks install 을 다시 돌려 주세요.",
        "쓰기 가능한 MCP 서버를 붙이면 이 게이트를 지나갈 수 있어요. "
        "설정 파일(~/.claude.json · 프로젝트 .mcp.json)은 이제 항상 막지만, "
        "**이미 붙어 있는** 서버는 그대로 지나가요.",
        "읽기는 비밀 파일(.env · 자격 증명)만 막아요. 대상이 폴더인 재귀 읽기"
        "(grep -r · find -exec cat)는 못 막으니 비밀은 프로젝트 폴더 밖에 두세요.",
    ]


# --- CLI (9단계에서 labremote 로 묶는다) ------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labremote hooks", description="훅 설치·제거·확인")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="래퍼를 만들고 사용자 설정에 등록")
    p_install.add_argument("--mode", choices=sorted(MODES), default="enforce")
    p_install.add_argument("--python", help="훅이 쓸 파이썬 (기본: 지금 이 인터프리터)")
    p_install.add_argument("--roots", help="실험 프로젝트들의 부모 폴더 (기본: LAB_PROJECTS_DIR)")

    sub.add_parser("uninstall", help="우리 항목만 제거")
    sub.add_parser("status", help="지금 등록된 상태 보기")

    args = parser.parse_args(argv)

    if args.cmd == "install":
        info = install(mode=args.mode, python=args.python, roots=args.roots)
        print(f"모드          {info['mode']}")
        print(f"래퍼          {info['wrapper']}")
        print(f"파이썬        {info['python']}")
        print(f"프로젝트 루트 {info['roots']}")
        print(f"설정          {info['settings']}")
        print(f"백업          {info['backup'] or '(원래 설정 파일이 없었어요)'}")
        if info["replaced"]:
            print(f"기존 항목     {info['replaced']}개를 새로 덮었어요")
        print(f"이벤트        {', '.join(info['events'])}")
        print("되돌리기      labremote hooks uninstall")
        print()
        for note in limitations():
            print(f"· {note}")
    elif args.cmd == "uninstall":
        info = uninstall()
        print(f"제거          {info['removed']}개 항목")
        print(f"설정          {info['settings']}")
        print(f"백업          {info['backup'] or '(원래 설정 파일이 없었어요)'}")
        if info["previousBackup"]:
            print(f"설치 전 백업  {info['previousBackup']}")
    else:
        info = status()
        print(f"설정          {info['settings']}")
        print(f"래퍼          {info['wrapper']} {'(있음)' if info['wrapperExists'] else '(없음)'}")
        print(f"프로젝트 루트 {info['roots']}")
        if info["installed"]:
            for event, entries in info["installed"].items():
                for entry in entries:
                    print(f"  {event:<12} {entry['hooks'][0]['command']}")
        else:
            print("  (등록된 labremote 훅이 없어요)")
        print()
        for note in limitations():
            print(f"· {note}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
