"""git 쓰기 — 커밋 · main에 합치기 (IDE · ADE의 소스 제어).

모든 호출이 `ops.run()`을 지난다(안전 옵션 + `.git` 검사, 훅 안 돎).
**push · force · reset은 만들지 않는다.** 합치기는 main worktree가 깨끗할 때만,
충돌이 나면 바로 되돌린다(`merge --abort`) — 반쯤 합쳐진 채로 두지 않는다.
PR은 `gh`가 있을 때만(없으면 화면에서 버튼을 숨긴다). lab.remote는 push하지 않으므로
**브랜치가 이미 원격에 올라가 있고 앞선 커밋이 없을 때만** `gh pr create`를 부른다.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .. import paths
from . import ops, view

__all__ = ["ActionError", "commit", "merge_to_main", "gh_available", "create_pr", "discard"]


class ActionError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def gh_available() -> bool:
    return bool(shutil.which("gh"))


def commit(base: str, message: str, paths_list: list[str] | None = None) -> dict:
    """이 worktree의 변경을 커밋한다. `paths_list`가 없으면 바뀐 것 전부(gitignore 제외)."""
    message = (message or "").strip()
    if not message:
        raise ActionError("커밋 메시지를 입력해 주세요.")
    info = view.status(base)
    if info.get("state") != "ok":
        raise ActionError(info.get("reason") or "git 저장소가 아니에요.")
    if not info["changes"]:
        raise ActionError("커밋할 변경이 없어요.")
    try:
        if paths_list:
            ops.run(base, ["add", "-A", "--", *paths_list])
        else:
            ops.run(base, ["add", "-A", "--", "."])
        staged = [l for l in ops.run(base, ["diff", "--cached", "--name-only"]).splitlines() if l.strip()]
        if not staged:
            raise ActionError("커밋할 변경이 없어요.")
        ops.run(base, ["commit", "-m", message])
    except ops.GitError as exc:
        raise ActionError(str(exc)) from None
    return {"sha": ops.head_sha(base), "files": staged}


def merge_to_main(root: str, branch: str) -> dict:
    """`branch`를 main에 합친다(--no-ff). main worktree에서 한다."""
    trees = view.worktrees(root)
    if trees.get("state") != "ok":
        raise ActionError(trees.get("reason") or "git 저장소가 아니에요.")
    main = trees["main"]
    if not branch or branch == main:
        raise ActionError("머지할 브랜치를 선택해 주세요.")
    host = next((w for w in trees["worktrees"] if w["branch"] == main), None)
    if host is None:
        raise ActionError(f"{main} 브랜치가 체크아웃된 worktree가 없어요. 프로젝트 루트를 {main} 브랜치로 전환해 주세요.")
    path = paths.real(host["path"])
    status = view.status(path)
    if status.get("state") != "ok" or status["changes"]:
        raise ActionError(f"{main} 브랜치에 커밋하지 않은 변경이 있어서 머지하지 않았어요. 먼저 커밋하거나 정리해 주세요.")
    if branch not in ops.branches(root):
        raise ActionError(f"없는 브랜치예요: {branch}")
    try:
        ops.run(path, ["merge", "--no-ff", "--no-edit", branch])
    except ops.GitError as exc:
        ops.run(path, ["merge", "--abort"], check=False)
        raise ActionError(f"충돌이 발생해서 머지를 취소했어요. 세션이나 IDE에서 충돌을 해결하고 다시 시도해 주세요. ({str(exc)[:200]})") from None
    return {"main": main, "branch": branch, "sha": ops.head_sha(path)}


def create_pr(base: str, title: str, body: str = "", *, runner=None) -> dict:
    """이 worktree의 브랜치로 PR을 연다 (`gh pr create`). push는 하지 않는다."""
    title = (title or "").strip()
    if not title:
        raise ActionError("PR 제목을 입력해 주세요.")
    gh = shutil.which("gh")
    if not gh and runner is None:
        raise ActionError("gh(GitHub CLI)가 없어요 — 설치하고 gh auth login으로 로그인하면 PR을 열 수 있어요.")
    info = view.status(base)
    if info.get("state") != "ok":
        raise ActionError(info.get("reason") or "git 저장소가 아니에요.")
    branch = info.get("branch") or ""
    if not branch or branch in ("main", "master"):
        raise ActionError("main이 아닌 브랜치에서 열어 주세요.")
    upstream = ops.run(base, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False).strip()
    if not upstream or "fatal" in upstream or upstream.startswith("@"):
        raise ActionError(f"{branch} 브랜치가 아직 원격에 없어요. 터미널에서 git push -u origin {branch} 명령을 실행한 뒤 다시 눌러 주세요 (lab.remote는 push하지 않아요).")
    ahead = ops.run(base, ["rev-list", "--count", "@{u}..HEAD"], check=False).strip()
    if ahead.isdigit() and int(ahead) > 0:
        raise ActionError(f"원격보다 커밋이 {ahead}개 앞서 있어요. 터미널에서 git push를 실행한 뒤 다시 눌러 주세요 (lab.remote는 push하지 않아요).")
    cmd = [gh or "gh", "pr", "create", "--head", branch, "--title", title[:200], "--body", (body or "")[:20000]]
    run = runner or (lambda c: subprocess.run(c, cwd=base, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL))
    try:
        done = run(cmd)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ActionError(f"gh를 실행하지 못했어요: {exc}") from None
    if done.returncode != 0:
        msg = (done.stderr or done.stdout or "").strip().splitlines()
        raise ActionError(f"PR을 열지 못했어요: {(msg[-1] if msg else '알 수 없는 오류')[:300]}")
    url = next((line.strip() for line in (done.stdout or "").splitlines() if line.strip().startswith("https://")), "")
    number = url.rstrip("/").rsplit("/", 1)[-1] if "/pull/" in url else ""
    return {"url": url, "number": number, "branch": branch}


def discard(base: str, rel: str) -> dict:
    """한 파일의 커밋 안 한 변경을 되돌린다 — 추적 중이면 HEAD로, 새 파일이면 지운다. 화면에서 한 번 더 묻고 부른다."""
    rel = (rel or "").strip().lstrip("/")
    full = paths.real(os.path.join(base, rel))
    if not rel or not paths.is_inside(paths.real(base), full) or "/.git/" in f"/{rel}/":
        raise ActionError("되돌릴 파일을 선택해 주세요.")
    info = view.status(base)
    if info.get("state") != "ok":
        raise ActionError(info.get("reason") or "git 저장소가 아니에요.")
    change = next((c for c in info["changes"] if c["path"] == rel), None)
    if change is None:
        raise ActionError("커밋하지 않은 변경이 없는 파일이에요.")
    try:
        tracked = bool(ops.run(base, ["ls-files", "--", rel]).strip())
        if tracked:
            ops.run(base, ["restore", "--staged", "--worktree", "--source=HEAD", "--", rel])
        else:
            ops.run(base, ["rm", "--cached", "-q", "--ignore-unmatch", "--", rel], check=False)
            if os.path.isfile(full):
                os.remove(full)
    except ops.GitError as exc:
        raise ActionError(str(exc)) from None
    return {"path": rel, "removed": not tracked}
