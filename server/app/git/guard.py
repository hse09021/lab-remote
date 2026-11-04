"""`.git` 이 **코드를 실행하게 만드는 설정**을 가졌나. — 보안 경계다.

## 왜 필요한가

오케스트레이터의 git 은 **샌드박스 밖에서 사용자 권한으로** 돈다(의도된
비대칭 — 커밋·브랜치는 훅을 거치지 않는다). 그런데 샌드박스는 작업 디렉터리
쓰기를 못 막으므로(M4) AI 가 쓴 코드가 `.git/` 에 쓸 수 있다.

    .git/hooks/post-commit          커밋할 때 실행된다
    .git/config  core.hooksPath     훅 폴더를 바꾼다
                 filter.X.process   add·checkout 할 때 실행된다
                 core.fsmonitor     status 할 때 실행된다
                 core.sshCommand    fetch·push 할 때 실행된다
                 include.path       다른 파일에서 위 전부를 끌어온다
    .gitattributes  * filter=X      어느 파일에 필터를 걸지 정한다

그래서 **두 겹**이다.

1. `ops.SAFE_CONFIG` — 명령줄 `-c` 로 덮는다. `-c` 는 저장소 설정을 **이긴다.**
2. 이 모듈 — `-c` 로 **못 덮는 것**(`filter.*`·`include.path`·`url.*.insteadOf`
   처럼 와일드카드가 없거나 파싱 시점에 끼어드는 것)을 찾아 **git 을 아예 안
   돌린다.** 열려 있는 구멍을 들고 커밋하는 것보다 멈추는 게 낫다.

## 설정은 git 으로 읽는다

`.git/config` 를 손으로 파싱하면 `include.path` 가 끌어온 값을 놓친다. 그래서
`git config --list --local` 로 **효과 있는 값**을 읽는다. 설정을 읽는 것은
훅·필터를 돌리지 않으므로 그 자체는 안전하다. 물론 그때도 `SAFE_CONFIG` 와
화이트리스트 환경을 쓴다.
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
    "ATTR_FILES",
    "config_entries",
    "bad_config",
    "bad_hooks",
    "bad_attributes",
    "check",
    "describe",
]


class GitRefused(RuntimeError):
    """`.git` 이 코드를 실행하게 만드는 설정을 가졌다. **git 을 안 돌린다.**"""


#: 이름이 정확히 이것이면 거부. `-c` 로 덮을 수 있는 것도 넣는다 — 덮을 수
#: **있다**는 것과 **누가 심어 뒀다**는 것은 다른 문제다. 심겼으면 알려야 한다.
FORBIDDEN_KEYS = frozenset(
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
        "core.alternaterefscommand",
        "core.alternaterefsprefixes",
        "diff.external",
        "sequence.editor",
        "uploadpack.packobjectshook",
        "credential.helper",
        "protocol.ext.allow",
        "gpg.program",
        "ssh.variant",
    }
)

#: 하위 이름이 붙는 것. 와일드카드라 `-c` 로 덮을 수 없다.
FORBIDDEN_PATTERNS = (
    # add·checkout 할 때 실행된다. `.gitattributes` 의 `filter=X` 와 짝이다.
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
    # 별칭은 빌트인을 못 가리지만, 심겼으면 손댄 흔적이다
    re.compile(r"^alias\..+$"),
)

#: 필터·textconv 를 **어느 파일에 걸지** 정하는 곳
ATTR_FILES = (".gitattributes", ".git/info/attributes")

#: 속성 파일에서 거부할 것
_ATTR_RE = re.compile(r"(^|\s)(filter|diff|merge)=(?!$)\S+")

#: `.git/hooks` 에서 봐주는 것 — git 이 기본으로 깔아 두는 예시다
_HOOK_SAMPLE = ".sample"


def _git_dir(root: str) -> str:
    return os.path.join(paths.real(root), ".git")


def config_entries(root: str, *, git: str = "git", config_args=(), env=None) -> dict:
    """`git config --list --local` 의 결과. `{소문자 키: 값}`.

    `include.path` 가 끌어온 값까지 **효과 있는 그대로** 본다. 못 읽으면 빈
    dict 가 아니라 **예외**다 — "못 읽었으니 괜찮다" 로 넘어가면 안 된다.
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
        raise GitRefused(f"git config 를 읽지 못했어요: {exc}") from None
    if done.returncode != 0:
        raise GitRefused(
            "git config 를 읽지 못했어요: "
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
            out.append(f".git/config · {key} = {shown!r} — git 이 이걸 실행해요")
    return out


def bad_hooks(root: str) -> list[str]:
    """`.git/hooks` 에 **실행 권한이 있는** 파일. `*.sample` 은 봐준다."""
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
            out.append(f".git/hooks/{name} — 실행 권한이 있어요. git 이 이걸 실행해요")
    return out


def bad_attributes(root: str) -> list[str]:
    """`filter=`·`diff=`·`merge=` 속성. 필터를 **어느 파일에 걸지** 정하는 곳."""
    out = []
    base = paths.real(root)
    found = [os.path.join(base, rel) for rel in ATTR_FILES]
    # 하위 폴더의 `.gitattributes` 도 먹는다
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        if ".gitattributes" in files:
            found.append(os.path.join(folder, ".gitattributes"))
    for path in sorted(set(found)):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(path, base)
        for number, line in enumerate(lines, 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if _ATTR_RE.search(text):
                out.append(f"{rel}:{number} · {text[:80]} — 필터·textconv 가 걸려 있어요")
    return out


def bad_submodules(root: str) -> list[str]:
    """서브모듈은 쓰지 않는다 — `.gitmodules` 로 다른 저장소를 끌어온다."""
    out = []
    base = paths.real(root)
    if os.path.exists(os.path.join(base, ".gitmodules")):
        out.append(".gitmodules — 서브모듈은 쓰지 않아요")
    if os.path.isdir(os.path.join(_git_dir(root), "modules")):
        out.append(".git/modules — 서브모듈 흔적이 있어요")
    return out


def check(root: str, *, git: str = "git", config_args=(), env=None) -> dict:
    """`{"ok": bool, "problems": [...]}`. **git 을 돌리기 전에** 부른다."""
    problems: list[str] = []
    problems += bad_hooks(root)
    problems += bad_attributes(root)
    problems += bad_submodules(root)
    problems += bad_config(
        config_entries(root, git=git, config_args=config_args, env=env)
    )
    return {"ok": not problems, "root": paths.real(root), "problems": problems}


def describe(report: dict) -> str:
    if report.get("ok"):
        return ".git 이 깨끗해요."
    lines = [".git 이 코드를 실행하게 만드는 설정을 가졌어요 — git 을 돌리지 않았어요:"]
    lines += [f"  · {p}" for p in report.get("problems") or []]
    lines.append("AI 가 쓴 코드가 심었을 수 있어요. 무엇이 들어갔는지 먼저 보세요.")
    return "\n".join(lines)
