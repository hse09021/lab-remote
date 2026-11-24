"""소스 제어의 리포지토리 줄 — 브랜치 · 원격 저장소 · 동기화 (VS Code와 같은 구조).

- 원격 전송(fetch · pull · push)은 **사람이 화면에서 누를 때만** 한다
  (`ops.run(..., net=True)`). 자동으로 가져오거나 보내지 않는다.
- push는 **force 없이** 현재 브랜치만. 원격에 새 커밋이 있으면 거절된 그대로
  알려 준다. pull은 merge 방식이고, 충돌이 나면 바로 `merge --abort`한다.
- 원격 주소는 https · ssh만 받는다. 주소에 자격 증명을 넣지 못하게 하고,
  화면에 보일 때도 사용자 정보를 지운다.
- GitHub 게시는 `gh repo create`로 **빈 저장소만** 만들고, 연결과 push는
  우리 `ops.run()`으로 한다 — gh가 저장소 안에서 git을 돌리면 `.git/hooks`가
  그대로 실행되기 때문이다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from .. import paths
from . import ops, view
from .actions import ActionError

__all__ = [
    "info",
    "fetch",
    "pull",
    "push",
    "sync",
    "checkout",
    "create_branch",
    "set_remote",
    "init",
    "publish_github",
    "stage",
    "unstage",
    "mask_url",
]

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_URL_RE = re.compile(
    r"^(?:https://[A-Za-z0-9.-]+(?::\d+)?/\S+"
    r"|ssh://(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+(?::\d+)?/\S+"
    r"|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^\s/][^\s]*)$"
)


def mask_url(url: str) -> str:
    """`https://user:token@host/…` → `https://host/…`. ssh의 `git@`은 그대로 둔다."""
    return re.sub(r"^(https?://)[^/@\s]+@", r"\1", url or "")


def _ok(base: str) -> dict:
    st = view.status(base)
    if st.get("state") != "ok":
        raise ActionError(st.get("reason") or "git 저장소가 아니에요.")
    return st


def _git(base: str, args: list[str], *, net: bool = False) -> str:
    try:
        return ops.run(base, args, net=net)
    except ops.GitRefused as exc:
        raise ActionError(str(exc)) from None
    except ops.GitError as exc:
        raise ActionError(_friendly(str(exc))) from None


def _friendly(msg: str) -> str:
    """원격 전송 실패를 사람이 할 일로 바꿔요. 모르는 오류는 원문 그대로."""
    low = msg.lower()
    if "could not read username" in low or "terminal prompts disabled" in low or "authentication failed" in low:
        return ("원격 저장소 인증 정보가 없어요. 데스크톱 터미널에서 gh auth login과 gh auth setup-git을 실행하거나 "
                "SSH 키를 등록한 뒤 다시 시도해 주세요.")
    if "host key verification failed" in low:
        return "SSH 호스트를 아직 신뢰하지 않았어요. 데스크톱 터미널에서 한 번 ssh -T git@github.com 명령으로 접속해 호스트를 등록해 주세요."
    if "permission denied (publickey)" in low:
        return "SSH 키 인증에 실패했어요. ssh-agent에 키가 등록되어 있는지 확인해 주세요."
    if "repository not found" in low or "does not appear to be a git repository" in low:
        return "원격 저장소를 찾을 수 없어요. 주소와 접근 권한을 확인해 주세요."
    if "could not resolve host" in low or "unable to access" in low and "resolve" in low:
        return "원격 서버에 연결하지 못했어요. 네트워크를 확인해 주세요."
    if "[rejected]" in low or "non-fast-forward" in low or "fetch first" in low:
        return "원격에 로컬에 없는 커밋이 있어서 push하지 못했어요. 먼저 pull하거나 동기화해 주세요."
    if "transport" in low and "not allowed" in low:
        return "https나 ssh 주소만 사용할 수 있어요."
    return msg


def _remotes(base: str) -> list[dict]:
    out = []
    seen = set()
    for line in _git(base, ["remote", "-v"]).splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)" and parts[0] not in seen:
            seen.add(parts[0])
            out.append({"name": parts[0], "url": mask_url(parts[1])})
    return out


def _refs(base: str, prefix: str) -> list[dict]:
    fmt = "%(refname:short)%00%(upstream:short)%00%(committerdate:unix)%00%(objectname:short)"
    rows = []
    for line in _git(base, ["for-each-ref", f"--format={fmt}", "--sort=-committerdate", prefix]).splitlines():
        name, upstream, at, sha = (line.split("\x00") + ["", "", "", ""])[:4]
        if not name or name.endswith("/HEAD") or name == prefix.rstrip("/").rsplit("/", 1)[-1]:
            continue
        rows.append({"name": name, "upstream": upstream, "at": int(at) if at.isdigit() else 0, "sha": sha})
    return rows


def info(base: str) -> dict:
    """리포지토리 줄 — 이름 · 브랜치 · 원격 · 앞섬/뒤처짐 · 브랜치 목록."""
    st = view.status(base)
    gh = bool(shutil.which("gh"))
    if st.get("state") == "none":
        return {"state": "none", "reason": st.get("reason"), "gh": gh, "repo": os.path.basename(paths.real(base))}
    if st.get("state") != "ok":
        return {"state": st.get("state"), "reason": st.get("reason"), "gh": gh}
    top = _git(base, ["rev-parse", "--show-toplevel"]).strip()
    has_commit = bool(st.get("head"))
    remotes = _remotes(base)
    return {
        "state": "ok",
        "repo": os.path.basename(top) or os.path.basename(paths.real(base)),
        "branch": st["branch"],
        "head": st["head"],
        "hasCommit": has_commit,
        "upstream": st.get("upstream", ""),
        "ahead": st.get("ahead", 0),
        "behind": st.get("behind", 0),
        "remotes": remotes,
        "local": _refs(base, "refs/heads/") if has_commit else [],
        "remote": _refs(base, "refs/remotes/") if has_commit else [],
        "gh": gh,
    }


# ── 원격 전송 (사람이 누를 때만) ────────────────────────────────


def fetch(base: str) -> dict:
    _ok(base)
    if not _remotes(base):
        raise ActionError("연결된 원격 저장소가 없어요.")
    _git(base, ["fetch", "--all", "--prune", "--no-recurse-submodules"], net=True)
    return info(base)


def pull(base: str) -> dict:
    st = _ok(base)
    if not st.get("upstream"):
        raise ActionError("이 브랜치는 아직 원격 브랜치와 연결되지 않았어요. 먼저 브랜치를 게시해 주세요.")
    if any(c["label"] == "충돌" for c in st["changes"]):
        raise ActionError("해결하지 않은 충돌이 있어요. 먼저 충돌을 해결해 주세요.")
    try:
        ops.run(base, ["pull", "--no-rebase", "--no-edit", "--no-recurse-submodules"], net=True)
    except ops.GitRefused as exc:
        raise ActionError(str(exc)) from None
    except ops.GitError as exc:
        text = str(exc)
        # 충돌 안내는 stdout으로 나와서 메시지에 없을 수 있어요 — MERGE_HEAD로 확인해요
        merging = ops.run(base, ["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False).strip()
        if merging or "CONFLICT" in text or "Automatic merge failed" in text:
            ops.run(base, ["merge", "--abort"], check=False)
            raise ActionError("pull하다가 충돌이 발생해서 머지를 취소했어요. 터미널에서 충돌을 해결하며 다시 pull해 주세요.") from None
        if "would be overwritten" in text:
            raise ActionError("커밋하지 않은 변경이 원격의 변경과 겹쳐서 pull하지 못했어요. 먼저 커밋해 주세요.") from None
        raise ActionError(_friendly(text)) from None
    return info(base)


def push(base: str) -> dict:
    """현재 브랜치만, force 없이. 원격 브랜치가 없으면 게시(`-u`)한다."""
    st = _ok(base)
    branch = st.get("branch") or ""
    if not branch:
        raise ActionError("브랜치가 아닌 커밋(분리된 HEAD)에서는 push할 수 없어요.")
    if not st.get("head"):
        raise ActionError("아직 커밋이 없어요. 먼저 커밋해 주세요.")
    if st.get("upstream"):
        _git(base, ["push", "--no-recurse-submodules"], net=True)
    else:
        remotes = _remotes(base)
        if not remotes:
            raise ActionError("연결된 원격 저장소가 없어요. 먼저 원격 저장소를 연결해 주세요.")
        name = "origin" if any(r["name"] == "origin" for r in remotes) else remotes[0]["name"]
        _git(base, ["push", "--no-recurse-submodules", "-u", name, f"refs/heads/{branch}:refs/heads/{branch}"], net=True)
    return info(base)


def sync(base: str) -> dict:
    """VS Code의 "변경 내용 동기화" — pull 뒤 push."""
    st = _ok(base)
    if not st.get("upstream"):
        return push(base)
    pull(base)
    return push(base)


# ── 브랜치 ─────────────────────────────────────────────────────


def _check_branch(base: str, name: str) -> str:
    name = (name or "").strip()
    if not _BRANCH_RE.match(name) or ".." in name or name.endswith((".lock", "/", ".")) or "//" in name:
        raise ActionError("브랜치 이름으로 쓸 수 없어요. 영문, 숫자, - _ . / 만 사용할 수 있어요.")
    done = subprocess.run(["git", "check-ref-format", "--branch", name], capture_output=True, text=True, timeout=10,
                          env=ops.safe_env(), stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise ActionError("브랜치 이름으로 쓸 수 없어요.")
    return name


def checkout(base: str, name: str) -> dict:
    """로컬 브랜치로 전환. `origin/x` 같은 원격 브랜치면 추적하는 로컬 브랜치를 만든다."""
    _ok(base)
    name = (name or "").strip()
    local = {r["name"] for r in _refs(base, "refs/heads/")}
    remote = {r["name"] for r in _refs(base, "refs/remotes/")}
    if name in local:
        _git(base, ["switch", name])
    elif name in remote:
        short = name.split("/", 1)[1] if "/" in name else name
        if short in local:
            _git(base, ["switch", short])
        else:
            _git(base, ["switch", "--track", name])
    else:
        raise ActionError(f"없는 브랜치예요: {name}")
    return info(base)


def create_branch(base: str, name: str, start: str = "") -> dict:
    st = _ok(base)
    name = _check_branch(base, name)
    if not st.get("head"):
        # 커밋이 아직 없으면 이름만 바꿔요 (unborn 브랜치)
        _git(base, ["symbolic-ref", "HEAD", f"refs/heads/{name}"])
        return info(base)
    if name in {r["name"] for r in _refs(base, "refs/heads/")}:
        raise ActionError(f"이미 있는 브랜치예요: {name}")
    args = ["switch", "-c", name]
    if start:
        known = {r["name"] for r in _refs(base, "refs/heads/")} | {r["name"] for r in _refs(base, "refs/remotes/")}
        if start not in known:
            raise ActionError(f"없는 브랜치예요: {start}")
        args += ["--no-track", start]
    _git(base, args)
    return info(base)


# ── 원격 저장소 연결 · 초기화 · GitHub 게시 ─────────────────────


def set_remote(base: str, url: str, name: str = "origin") -> dict:
    """원격 저장소를 연결하거나 주소를 바꾼다. https · ssh만."""
    _ok(base)
    url = (url or "").strip()
    name = (name or "origin").strip()
    if not _REMOTE_NAME_RE.match(name):
        raise ActionError("원격 이름으로 쓸 수 없어요.")
    if re.match(r"^https?://[^/@\s]+@", url):
        raise ActionError("주소에 사용자 이름이나 토큰을 넣지 말아 주세요. 인증은 gh auth setup-git이나 SSH 키로 설정해요.")
    if not _URL_RE.match(url) or url.startswith("-"):
        raise ActionError("https:// 또는 git@호스트:경로 형식의 주소를 입력해 주세요.")
    if any(r["name"] == name for r in _remotes(base)):
        _git(base, ["remote", "set-url", name, url])
    else:
        _git(base, ["remote", "add", name, url])
    return info(base)


def init(base: str) -> dict:
    """git 저장소가 아닌 프로젝트 폴더에 `git init -b main`."""
    st = view.status(base)
    if st.get("state") == "ok":
        raise ActionError("이미 git 저장소예요.")
    if st.get("state") != "none":
        raise ActionError(st.get("reason") or "git을 사용할 수 없어요.")
    try:
        ops.run(base, ["init", "-b", "main"], guarded=False)
    except ops.GitError as exc:
        raise ActionError(str(exc)) from None
    return info(base)


def publish_github(base: str, name: str, private: bool = True, *, runner=None) -> dict:
    """gh로 GitHub에 빈 저장소를 만들고 origin으로 연결한 뒤 현재 브랜치를 push한다."""
    st = _ok(base)
    name = (name or "").strip()
    if not _REPO_NAME_RE.match(name):
        raise ActionError("저장소 이름은 영문, 숫자, - _ . 만 사용할 수 있어요.")
    if _remotes(base):
        raise ActionError("이미 원격 저장소가 연결되어 있어요.")
    if not st.get("head"):
        raise ActionError("아직 커밋이 없어요. 먼저 커밋한 뒤 게시해 주세요.")
    gh = shutil.which("gh")
    if not gh and runner is None:
        raise ActionError("gh(GitHub CLI)가 설치되어 있지 않아요. 설치하고 gh auth login으로 로그인하면 게시할 수 있어요.")
    cmd = [gh or "gh", "repo", "create", name, "--private" if private else "--public"]
    # 저장소 밖에서 실행해요 — gh가 이 저장소의 git 설정 · 훅을 건드리지 않게
    run = runner or (lambda c: subprocess.run(c, cwd=os.path.expanduser("~"), capture_output=True, text=True,
                                              timeout=60, stdin=subprocess.DEVNULL))
    try:
        done = run(cmd)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ActionError(f"gh를 실행하지 못했어요: {exc}") from None
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        raise ActionError(f"GitHub 저장소를 만들지 못했어요: {(lines[-1] if lines else '알 수 없는 오류')[:300]}")
    url = next((x.strip() for x in (done.stdout or "").splitlines() if x.strip().startswith("https://")), "")
    if not url:
        raise ActionError("GitHub 저장소는 만들었지만 주소를 확인하지 못했어요. 원격 저장소 연결에서 직접 입력해 주세요.")
    set_remote(base, url.rstrip("/") + ".git")
    got = push(base)
    got["published"] = url
    return got


# ── 스테이징 ───────────────────────────────────────────────────


def _rels(base: str, rels: list[str]) -> list[str]:
    root = paths.real(base)
    out = []
    for rel in rels or []:
        rel = (rel or "").strip().lstrip("/")
        if not rel or "/.git/" in f"/{rel}/" or not paths.is_inside(root, paths.real(os.path.join(root, rel))):
            raise ActionError("스테이징할 파일을 선택해 주세요.")
        out.append(rel)
    if not out:
        raise ActionError("스테이징할 파일을 선택해 주세요.")
    return out


def stage(base: str, rels: list[str]) -> dict:
    _ok(base)
    _git(base, ["add", "-A", "--", *_rels(base, rels)])
    return {"ok": True}


def unstage(base: str, rels: list[str]) -> dict:
    st = _ok(base)
    files = _rels(base, rels)
    if st.get("head"):
        _git(base, ["restore", "--staged", "--", *files])
    else:
        _git(base, ["rm", "--cached", "-q", "-r", "--ignore-unmatch", "--", *files])
    return {"ok": True}
