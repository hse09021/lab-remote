"""git 저수준 — 모든 git 호출이 `run()`을 지난다.

기본은 **원격 전송 없음**(`protocol.allow=never`). fetch · pull · push는 사람이
소스 제어에서 누를 때만 `run(..., net=True)`로 부르고, 그때만 https · ssh와
사용자의 전역 자격 증명 도우미를 연다(`net_config()`, 2026-11-24 결정).

> ⚠ **git 명령은 오케스트레이터가 직접 실행하므로 훅을 거치지 않는다.**
> 그래서 `commit`의 대상 경로를 코드가 화이트리스트로 지정한다 — 자유
> `git add -A`는 만들지 않는다. 이 비대칭은 의도된 것이다.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .. import paths, registry
from .guard import GitRefused
from . import guard as guard_mod

__all__ = [
    "GitError",
    "GitRefused",
    "SAFE_ENV",
    "ENV_KEEP",
    "nohooks_dir",
    "safe_config",
    "commit_config",
    "identity",
    "safe_env",
    "net_config",
    "user_credential_config",
    "run",
    "inside_worktree",
    "current_branch",
    "branches",
    "create_branch",
    "switch",
    "commit",
    "status_porcelain",
    "diff_name_only",
    "log",
    "head_sha",
]

TIMEOUT_SEC = 60

#: 빈 훅 폴더. `core.hooksPath`를 여기로 돌려 `.git/hooks/*`를 무력화한다.
#: `server/data/` 아래라 샌드박스 안 코드가 **여기엔 못 쓴다**(M1b).
NOHOOKS_NAME = "nohooks"

#: git에 물려주는 환경. **화이트리스트다** — 오케스트레이터의 환경이 그대로
#: 새면 `LAB_*`로 우리 폴더 위치까지 알려 주는 셈이고, `GIT_*`가 섞이면
#: 아래 고정값을 덮어쓴다.
ENV_KEEP = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ")

#: 무조건 넣는 값. 저장소 **밖**의 설정과 대화형 입력을 끊는다.
SAFE_ENV = {
    # 전역·시스템 설정을 안 읽는다. 저장소 설정만 남는다(그건 guard가 본다).
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    # 시스템 gitattributes를 안 읽는다
    "GIT_ATTR_NOSYSTEM": "1",
    # 자격 증명·암호를 물어보지 않는다. 물어보면 루프가 멈춘다.
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    # 편집기·페이저를 띄우지 않는다
    "GIT_EDITOR": "false",
    "GIT_SEQUENCE_EDITOR": "false",
    "GIT_PAGER": "cat",
    # 외부 diff·머지 도구를 쓰지 않는다
    "GIT_EXTERNAL_DIFF": "",
}

#: 전역 설정도 안 읽으므로 커밋 신원이 사라진다. 사람의 신원을 **따로 읽어**
#: `-c`로 넘긴다 (설정을 읽는 것은 아무것도 실행하지 않는다). 못 찾으면
#: 이 값으로 커밋한다 — 루프가 신원 때문에 멈추면 안 된다.
FALLBACK_IDENTITY = ("lab.remote", "labremote@localhost")


#: 커밋 신원이 필요한 하위명령
NEEDS_IDENTITY = frozenset({"commit", "merge", "revert", "cherry-pick", "tag", "am", "pull"})

#: 원격 전송(`net=True`)에서만 여는 프로토콜. 시험은 여기에 "file"을 더한다.
NET_PROTOCOLS = ("https", "ssh")

#: 원격 전송에서만 더 물려주는 환경 — ssh-agent 소켓
ENV_NET_KEEP = ("SSH_AUTH_SOCK",)

NET_TIMEOUT_SEC = 180


def nohooks_dir() -> str:
    """빈 훅 폴더를 만들고 경로를 돌려준다."""
    folder = os.path.join(registry.data_dir(), "agent", NOHOOKS_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder


def identity(base: dict | None = None) -> tuple[str, str]:
    """커밋에 쓸 `(이름, 메일)`.

    `SAFE_ENV`가 전역·시스템 설정을 끊으므로 신원도 같이 사라진다. 그래서
    **신원만** 전역 설정에서 읽어 `-c user.*`로 넘긴다. 설정을 읽는 것은
    훅·필터를 돌리지 않는다.

    왜 전역 설정을 실행에는 안 쓰나: `~/.gitconfig`는 AI가 쓴 코드가 못
    고치지만(홈 쓰기가 버려진다 · bwrap은 읽기 전용), 거기 `core.hooksPath`
    같은 게 있으면 우리 의도와 다르게 돈다. 신원만 가져오는 게 가장 좁다.
    """
    source = os.environ if base is None else base
    env = {k: source[k] for k in ENV_KEEP if k in source}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    got = []
    for key in ("user.name", "user.email"):
        value = ""
        try:
            done = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True, text=True, timeout=10, env=env,
            )
            if done.returncode == 0:
                value = done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            value = ""
        got.append(value)
    name = got[0] or FALLBACK_IDENTITY[0]
    mail = got[1] or FALLBACK_IDENTITY[1]
    return name, mail


def safe_config() -> list[str]:
    """명령줄 `-c`로 덮는 값. **`-c`는 저장소 설정을 이긴다.**

    `.git/config`는 AI가 쓴 코드가 고칠 수 있다(M4) — 샌드박스는 작업
    디렉터리 쓰기를 못 막는다. 그리고 오케스트레이터의 git은 **샌드박스
    밖에서 사용자 권한으로** 돈다. 그래서 git이 무엇을 실행할 수 있는지를
    우리가 정한다.

    와일드카드가 있는 것(`filter.*`·`diff.*.textconv`)과 파싱 시점에 끼어드는
    것(`include.path`)은 `-c`로 덮을 수 없다 — `git/guard.py`가 찾아서
    **git을 아예 안 돌린다.**
    """
    return [
        # `.git/hooks/*`를 무력화한다 (빈 폴더를 가리킨다)
        "-c", f"core.hooksPath={nohooks_dir()}",
        # status 할 때 실행되는 감시 프로그램
        "-c", "core.fsmonitor=false",
        # fetch·push 할 때 실행된다
        "-c", "core.sshCommand=",
        "-c", "core.gitProxy=",
        # 대화형으로 뭔가 띄우는 것
        "-c", "core.editor=false",
        "-c", "sequence.editor=false",
        "-c", "core.askPass=",
        # 빈 값은 helper 목록을 **초기화**한다 (git 문서)
        "-c", "credential.helper=",
        # 저장소 밖 속성 파일
        "-c", "core.attributesFile=" + os.devnull,
        # 외부 diff 프로그램
        "-c", "diff.external=",
        "-c", "gpg.program=false",
        # 기본은 원격 전송 없음 — 사람이 누른 fetch · pull · push만 net_config()가 연다
        "-c", "protocol.allow=never",
    ]


def commit_config() -> list[str]:
    """`safe_config()` + 커밋 신원. 커밋하는 명령에만 붙인다."""
    name, mail = identity()
    return [*safe_config(), "-c", f"user.name={name}", "-c", f"user.email={mail}"]


def safe_env(base: dict | None = None, *, net: bool = False) -> dict[str, str]:
    """git이 받을 환경. 화이트리스트 + 고정값."""
    source = os.environ if base is None else base
    keep = ENV_KEEP + (ENV_NET_KEEP if net else ())
    out = {k: source[k] for k in keep if k in source}
    out.update(SAFE_ENV)
    return out


def user_credential_config(base: dict | None = None) -> list[str]:
    """사용자 **전역** 설정의 자격 증명 도우미를 `-c` 인자로.

    `SAFE_ENV`가 전역 설정을 끊으므로 `gh auth setup-git`이 넣은 도우미도
    사라진다. 그래서 신원(`identity()`)처럼 **도우미 줄만** 따로 읽는다.
    저장소 설정의 도우미는 `guard`가 막거나 `credential.helper=`로 비운다 —
    여기서는 사용자가 직접 설정한 전역 값만 쓴다. 전역에 하나도 없고 `gh`가
    있으면 github.com에 한해 `gh auth git-credential`을 쓴다.
    """
    source = os.environ if base is None else base
    env = {k: source[k] for k in ENV_KEEP if k in source}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    out: list[str] = []
    try:
        done = subprocess.run(
            ["git", "config", "--global", "--get-regexp", r"^credential\..*"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        lines = done.stdout.splitlines() if done.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        lines = []
    has_helper = False
    for line in lines:
        key, _, value = line.partition(" ")
        low = key.lower()
        if low.endswith(".helper") or low.endswith(".username") or low.endswith(".usehttppath"):
            out += ["-c", f"{key}={value}"]
            has_helper = has_helper or (low.endswith(".helper") and bool(value.strip()))
    if not has_helper:
        gh = shutil.which("gh", path=source.get("PATH"))
        if gh:
            out += [
                "-c", "credential.https://github.com.helper=",
                "-c", f"credential.https://github.com.helper=!'{gh}' auth git-credential",
            ]
    return out


def net_config(config: list[str]) -> list[str]:
    """원격 전송용 — `safe_config()`에서 프로토콜 · ssh · 자격 증명만 연다.

    훅 · 필터 · 편집기를 끄는 나머지 값은 그대로다. ssh는 `BatchMode`라
    암호나 호스트 확인을 묻지 않고 실패한다(서버에는 터미널이 없다).
    """
    out = list(config)
    for i, value in enumerate(out):
        if value == "core.sshCommand=":
            out[i] = "core.sshCommand=ssh -o BatchMode=yes"
    for proto in NET_PROTOCOLS:
        out += ["-c", f"protocol.{proto}.allow=always"]
    return out + user_credential_config()


class GitError(RuntimeError):
    """git이 실패했을 때. 메시지에 stderr를 그대로 싣는다."""


def guard(root: str) -> dict:
    """`.git`이 코드를 실행하게 만드는 설정을 가졌나. 가졌으면 `GitRefused`.

    `run()`이 매번 부른다. 한 번 보고 캐시하지 않는다 — 세션 사이에 바뀔 수
    있다. (git 호출은 Claude 세션이 떠 있지 않을 때만 하지만, 학습 프로세스도
    프로젝트 안에 쓸 수 있다.)
    """
    report = guard_mod.check(
        root, config_args=safe_config(), env=safe_env()
    )
    if not report["ok"]:
        raise GitRefused(guard_mod.describe(report))
    return report


def run(root: str, args: list[str], *, check: bool = True, guarded: bool = True, net: bool = False) -> str:
    """`git -C <root> <args>`. 실패하면 `GitError`.

    `guarded=False`는 `guard()` 자신이 쓰는 내부 경로용이다 — 밖에서는 쓰지
    않는다. 모든 호출이 `.git` 검사를 지나간다. `net=True`는 사람이 누른
    fetch · pull · push에만 쓴다.
    """
    if guarded:
        guard(root)
    # 커밋하는 명령에는 신원을 붙인다 — `SAFE_ENV`가 전역 설정을 끊어서
    # 그대로면 "who are you"로 실패한다.
    config = commit_config() if args and args[0] in NEEDS_IDENTITY else safe_config()
    if net:
        config = net_config(config)
    try:
        done = subprocess.run(
            ["git", "--no-pager", *config, "-C", paths.real(root), *args],
            capture_output=True,
            text=True,
            timeout=NET_TIMEOUT_SEC if net else TIMEOUT_SEC,
            env=safe_env(net=net),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git을 실행하지 못했어요: {exc}") from None
    if check and done.returncode != 0:
        raise GitError(
            f"git 명령이 실패했어요 (git {' '.join(args[:2])} · 종료 코드 {done.returncode}): "
            + (done.stderr or done.stdout or "").strip()[:400]
        )
    return done.stdout


def inside_worktree(root: str) -> bool:
    try:
        return run(root, ["rev-parse", "--is-inside-work-tree"]).strip() == "true"
    except GitError:
        return False


def current_branch(root: str) -> str:
    return run(root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def head_sha(root: str, short: bool = True) -> str:
    args = ["rev-parse", "--short" if short else "--verify", "HEAD"]
    try:
        return run(root, args).strip()
    except GitError:
        return ""


def branches(root: str) -> list[str]:
    out = run(root, ["branch", "--format=%(refname:short)"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def create_branch(root: str, name: str, *, switch_to: bool = True) -> str:
    """브랜치를 만든다. 이미 있으면 그대로 두고 (요청하면) 옮겨 간다."""
    if name in branches(root):
        if switch_to:
            switch(root, name)
        return name
    run(root, ["switch", "-c", name] if switch_to else ["branch", name])
    return name


def status_porcelain(root: str, paths_only: list[str] | None = None) -> list[str]:
    args = ["status", "--porcelain"]
    if paths_only:
        args += ["--", *paths_only]
    return [line for line in run(root, args).splitlines() if line.strip()]


def switch(root: str, name: str, *, retries: int = 1) -> dict:
    """브랜치를 옮긴다. **강제 전환(`-f`)은 하지 않는다.**

    훅이 계속 쓰는 파일(`Approval_log.csv` 등) 때문에 실패할 수 있다. 한 번만
    다시 해 보고, 그래도 안 되면 그대로 둔다 — 강제로 밀면 그 기록이 사라진다.
    """
    last = ""
    for attempt in range(max(1, retries + 1)):
        try:
            run(root, ["switch", name])
            return {"ok": True, "branch": name, "attempts": attempt + 1}
        except GitError as exc:
            last = str(exc)
    return {"ok": False, "branch": current_branch(root), "error": last}


def commit(root: str, message: str, paths_list: list[str]) -> dict:
    """**지정한 경로만** 담아 커밋한다. 자유 `add -A`는 만들지 않는다.

    바뀐 게 없으면 커밋하지 않고 `{"committed": False}`를 돌려준다.
    """
    if not paths_list:
        raise GitError("커밋할 경로를 지정해 주세요 (경로 없이 전체를 add하지 않아요).")
    existing = [p for p in paths_list if os.path.exists(os.path.join(paths.real(root), p))]
    if not existing:
        return {"committed": False, "reason": "그 경로가 아직 없어요", "paths": []}
    run(root, ["add", "--", *existing])
    staged = [
        line
        for line in run(root, ["diff", "--cached", "--name-only", "--", *existing]).splitlines()
        if line.strip()
    ]
    if not staged:
        return {"committed": False, "reason": "변경 사항이 없어요", "paths": []}
    # **담긴 파일만** 넘긴다. 빈 폴더를 pathspec으로 주면 git이 거절한다.
    run(root, ["commit", "-m", message, "--", *staged])
    return {"committed": True, "sha": head_sha(root), "paths": staged}


def diff_name_only(root: str, ref: str = "HEAD") -> list[str]:
    return [line for line in run(root, ["diff", "--name-only", ref]).splitlines() if line]


def log(root: str, count: int = 10) -> list[dict]:
    out = run(root, ["log", f"-{int(count)}", "--format=%h%x1f%an%x1f%ad%x1f%s", "--date=iso"])
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append({"sha": parts[0], "author": parts[1], "at": parts[2], "subject": parts[3]})
    return rows
