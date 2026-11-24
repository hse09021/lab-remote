"""`.git`이 **코드를 실행하게 만드는 설정**을 가졌나. — 보안 경계다.

## 왜 필요한가

lab.remote의 git은 사람이 화면에서 누를 때 **사용자 권한으로** 돈다. 그런데
에이전트 세션이 쓴 코드는 프로젝트 안 `.git/`에도 쓸 수 있다. `.git/config`
에 필터 드라이버를 심어 두면, 사람이 Files 탭을 여는 순간의 `git status`가
그 명령을 실행한다.

그래서 **두 겹**이다.

1. `ops.safe_config()` — 명령줄 `-c`로 덮는다. `-c`는 저장소 설정을 **이긴다.**
   훅 폴더는 빈 폴더를 가리키고, fsmonitor·pager·editor·askpass는 끈다.
2. 이 모듈 — `-c`로 **못 덮는 것**(`filter.X.clean`처럼 이름 가운데가 바뀌는
   드라이버, 다른 파일을 끌어오는 `include.path`, `protocol.<이름>.allow` …)을
   찾아 **git을 아예 안 돌린다.**

## 거절하지 않고 알리기만 하는 것 (v3)

`-c`가 이미 무력화하는 것은 막지 않는다. 사람의 연구 저장소에는 흔하다.

| 있는 것 | 왜 괜찮나 |
|---|---|
| `.git/hooks/*` 실행 파일 (pre-commit·husky) | `core.hooksPath`를 빈 폴더로 덮는다 |
| `core.hooksPath`·`core.fsmonitor`·`core.pager` 등 | `-c`로 덮는다 |
| `.gitattributes`의 `filter=lfs` 등 | 드라이버(`filter.X.*`)가 없으면 아무것도 안 돈다. 드라이버는 위에서 막고, 전역·시스템 설정은 끊는다 |
| 서브모듈 · `alias.*` | 우리가 부르는 읽기 명령은 이것들을 실행하지 않는다 |

이것들은 `notes`로 돌려준다.

## 설정은 git으로 읽는다

`.git/config`를 손으로 파싱하면 `include.path`가 끌어온 값을 놓친다. 그래서
`git config --list --local`로 **효과 있는 값**을 읽는다.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess

from .. import paths

__all__ = [
    "GitRefused",
    "FORBIDDEN_KEYS",
    "FORBIDDEN_PATTERNS",
    "NOTED_KEYS",
    "NOTED_PATTERNS",
    "ATTR_FILES",
    "noted_config",
    "config_entries",
    "bad_config",
    "bad_hooks",
    "bad_attributes",
    "check",
    "describe",
]


class GitRefused(RuntimeError):
    """`.git`이 코드를 실행하게 만드는 설정을 가졌다. **git을 안 돌린다.**"""


#: 이름이 정확히 이것이면 거부 — `ops.safe_config()`가 **덮지 않는** 것.
FORBIDDEN_KEYS = frozenset(
    {
        "core.alternaterefscommand",
        "core.alternaterefsprefixes",
        "uploadpack.packobjectshook",
        "ssh.variant",
    }
)

#: 있으면 **알리기만** 하는 키 — `ops.safe_config()`의 `-c`가 이긴다.
NOTED_KEYS = frozenset(
    {
        "core.hookspath",
        "core.fsmonitor",
        "core.fsmonitorhookversion",
        "core.sshcommand",
        "core.askpass",
        "core.gitproxy",
        "core.editor",
        "core.pager",
        "core.attributesfile",
        "diff.external",
        "sequence.editor",
        "credential.helper",
        "gpg.program",
    }
)

#: 하위 이름이 붙는 것. 와일드카드라 `-c`로 덮을 수 없다.
FORBIDDEN_PATTERNS = (
    # add·checkout 할 때 실행된다. `.gitattributes`의 `filter=X`와 짝이다.
    re.compile(r"^filter\..*\.(clean|smudge|process)$"),
    # `diff=X` 속성이 붙은 파일을 볼 때 실행된다
    re.compile(r"^diff\..*\.(command|textconv|external)$"),
    # 병합할 때 실행된다
    re.compile(r"^merge\..*\.driver$"),
    # 다른 파일에서 위 전부를 끌어온다 — 파싱 시점에 끼어든다
    re.compile(r"^include\.path$"),
    re.compile(r"^includeif\..*\.path$"),
    # 원격 주소를 바꿔치기한다
    re.compile(r"^url\..*\.(insteadof|pushinsteadof)$"),
    re.compile(r"^http\..*\.proxy$"),
    re.compile(r"^credential\..*\.helper$"),
    # `protocol.<이름>.allow`는 `protocol.allow=never`보다 우선한다
    re.compile(r"^protocol\..+\.allow$"),
)

#: 있으면 알리기만 하는 패턴 — 별칭은 빌트인을 못 가린다
NOTED_PATTERNS = (re.compile(r"^alias\..+$"),)

#: 필터·textconv를 **어느 파일에 걸지** 정하는 곳
ATTR_FILES = (".gitattributes", ".git/info/attributes")

#: 속성 파일에서 거부할 것
_ATTR_RE = re.compile(r"(^|\s)(filter|diff|merge)=(?!$)\S+")

#: `.git/hooks`에서 봐주는 것 — git이 기본으로 깔아 두는 예시다
_HOOK_SAMPLE = ".sample"


def _git_dir(root: str) -> str:
    return os.path.join(paths.real(root), ".git")


def config_entries(root: str, *, git: str = "git", config_args=(), env=None) -> dict:
    """`git config --list --local`의 결과. `{소문자 키: 값}`.

    `include.path`가 끌어온 값까지 **효과 있는 그대로** 본다. 못 읽으면 빈
    dict가 아니라 **예외**다 — "못 읽었으니 괜찮다"로 넘어가면 안 된다.
    """
    local = os.path.join(_git_dir(root), "config")
    if not os.path.exists(local):
        return {}
    argv = [git, *config_args, "-C", paths.real(root), "config", "--list", "--local", "-z"]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, env=env or {}
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitRefused(f"git config를 읽지 못했어요: {exc}") from None
    if done.returncode != 0:
        raise GitRefused(
            "git config를 읽지 못했어요: "
            + (done.stderr or done.stdout or "").strip()[:200]
        )
    out: dict[str, str] = {}
    for chunk in done.stdout.split("\0"):
        if not chunk:
            continue
        key, _, value = chunk.partition("\n")
        out[key.strip().lower()] = value
    return out


def bad_config(entries: dict) -> list[str]:
    """위험한 설정 키를 사람이 읽을 사유로."""
    out = []
    for key, value in sorted(entries.items()):
        if key in FORBIDDEN_KEYS or any(p.match(key) for p in FORBIDDEN_PATTERNS):
            shown = (value or "")[:80]
            out.append(f".git/config · {key} = {shown!r} — git이 이걸 실행해요")
    return out


def noted_config(entries: dict) -> list[str]:
    """있지만 `-c`가 이기는 설정. 알리기만 한다."""
    out = []
    for key, value in sorted(entries.items()):
        if key in NOTED_KEYS or any(p.match(key) for p in NOTED_PATTERNS):
            out.append(f".git/config · {key} — lab.remote의 git에서는 꺼져요")
    return out


def bad_hooks(root: str) -> list[str]:
    """`.git/hooks`에 **실행 권한이 있는** 파일. `*.sample`은 봐준다."""
    folder = os.path.join(_git_dir(root), "hooks")
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if name.endswith(_HOOK_SAMPLE):
            continue
        path = os.path.join(folder, name)
        try:
            mode = os.stat(path).st_mode
        except OSError:
            continue
        if stat.S_ISREG(mode) and mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            out.append(f".git/hooks/{name} — lab.remote의 git에서는 안 돌아요")
    return out


def bad_attributes(root: str) -> list[str]:
    """`filter=`·`diff=`·`merge=` 속성. **알리기만** 한다.

    드라이버 정의(`filter.X.*`)가 없으면 아무것도 안 돈다 — 드라이버는
    `bad_config`가 막는다. 저장소 전체를 걷지 않는다(큰 연구 저장소에서
    git을 부를 때마다 걸으면 느리다). 맨 위 `.gitattributes`와
    `.git/info/attributes`만 본다.
    """
    out = []
    base = paths.real(root)
    for rel in ATTR_FILES:
        path = os.path.join(base, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            text = line.strip()
            if text and not text.startswith("#") and _ATTR_RE.search(text):
                out.append(f"{rel}:{number} · {text[:80]}")
    return out


def bad_submodules(root: str) -> list[str]:
    """서브모듈 흔적. 알리기만 한다."""
    out = []
    base = paths.real(root)
    if os.path.exists(os.path.join(base, ".gitmodules")):
        out.append(".gitmodules — 서브모듈이 있어요")
    if os.path.isdir(os.path.join(_git_dir(root), "modules")):
        out.append(".git/modules — 서브모듈 흔적이 있어요")
    return out


def check(root: str, *, git: str = "git", config_args=(), env=None) -> dict:
    """`{"ok", "problems", "notes"}`. **git을 돌리기 전에** 부른다.

    `problems`가 있으면 git을 안 돌린다. `notes`는 알리기만 한다.
    """
    entries = config_entries(root, git=git, config_args=config_args, env=env)
    problems = bad_config(entries)
    notes = noted_config(entries) + bad_hooks(root) + bad_attributes(root) + bad_submodules(root)
    return {"ok": not problems, "root": paths.real(root), "problems": problems, "notes": notes}


def describe(report: dict) -> str:
    if report.get("ok"):
        return ".git이 깨끗해요."
    lines = [".git에 코드를 실행하게 하는 설정이 들어 있어요 — git을 돌리지 않았어요:"]
    lines += [f"  · {p}" for p in report.get("problems") or []]
    lines.append("에이전트 세션이 쓴 코드가 심었을 수 있어요. 무엇이 들어갔는지 먼저 확인해 주세요.")
    return "\n".join(lines)
