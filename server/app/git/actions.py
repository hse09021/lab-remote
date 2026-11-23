"""git 쓰기 — 커밋 · main 에 합치기 (IDE · ADE 의 소스 제어).

모든 호출이 `ops.run()` 을 지난다(안전 옵션 + `.git` 검사, 훅 안 돎).
**push · force · reset 은 만들지 않는다.** 합치기는 main worktree 가 깨끗할 때만,
충돌이 나면 바로 되돌린다(`merge --abort`) — 반쯤 합쳐진 채로 두지 않는다.
PR 은 `gh` 가 있을 때만(지금 이 컴퓨터엔 없다 — 화면에서 버튼을 숨긴다).
"""

from __future__ import annotations

import shutil

from .. import paths
from . import ops, view

__all__ = ["ActionError", "commit", "merge_to_main", "gh_available"]


class ActionError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def gh_available() -> bool:
    return bool(shutil.which("gh"))


def commit(base: str, message: str, paths_list: list[str] | None = None) -> dict:
    """이 worktree 의 변경을 커밋한다. `paths_list` 가 없으면 바뀐 것 전부(gitignore 제외)."""
    message = (message or "").strip()
    if not message:
        raise ActionError("커밋 메시지를 적어 주세요.")
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
    """`branch` 를 main 에 합친다(--no-ff). main worktree 에서 한다."""
    trees = view.worktrees(root)
    if trees.get("state") != "ok":
        raise ActionError(trees.get("reason") or "git 저장소가 아니에요.")
    main = trees["main"]
    if not branch or branch == main:
        raise ActionError("합칠 브랜치를 골라 주세요.")
    host = next((w for w in trees["worktrees"] if w["branch"] == main), None)
    if host is None:
        raise ActionError(f"{main} 이 체크아웃된 worktree 가 없어요. 프로젝트 루트를 {main} 으로 바꿔 주세요.")
    path = paths.real(host["path"])
    status = view.status(path)
    if status.get("state") != "ok" or status["changes"]:
        raise ActionError(f"{main} 쪽에 커밋 안 한 변경이 있어서 합치지 않았어요. 먼저 커밋하거나 정리해 주세요.")
    if branch not in ops.branches(root):
        raise ActionError(f"없는 브랜치예요: {branch}")
    try:
        ops.run(path, ["merge", "--no-ff", "--no-edit", branch])
    except ops.GitError as exc:
        ops.run(path, ["merge", "--abort"], check=False)
        raise ActionError(f"충돌이 나서 합치지 않고 되돌렸어요. 세션이나 IDE 에서 충돌을 풀고 다시 해 주세요. ({str(exc)[:200]})") from None
    return {"main": main, "branch": branch, "sha": ops.head_sha(path)}
