"""브랜치와 기록 커밋 — **로컬만.**

```
루프 시작 전   git switch -c exp-NNN      ← 실험이 돌기 전에만
  (코드 변경 · 실험 실행 · 기록 작성 전부 이 브랜치에서)
루프 끝난 뒤   git switch main
              git checkout exp-NNN -- logs/ state/ experiments/EXP-NNN/
              git commit -m "exp: EXP-NNN 기록"    ← 기록은 항상 main (spec III-6)
```

**실험이 도는 동안에는 브랜치를 절대 바꾸지 않는다.** 전환은 루프의 앞뒤에서만,
그리고 Claude 세션이 떠 있지 않을 때만 한다 — 세션이 없으면 훅도 안 뜨므로
`Approval_log.csv` 를 쓰는 경쟁이 거의 사라진다.

훅이 계속 쓰는 파일 셋을 따로 다룬다.

| 파일 | 처리 |
|---|---|
| `logs/hook_events.jsonl` | 이미 gitignore |
| `state/Current.yaml` | gitignore (오케스트레이터가 쓰는 런타임 상태) |
| `logs/Approval_log.csv` | 추적 유지 (spec III-6). **전환 전에 커밋한다** |
"""

from __future__ import annotations

from .. import loop_layout as L
from ..git import ops

__all__ = ["BRANCH_PREFIX", "RECORD_PATHS", "branch_name", "start_experiment", "record_and_return"]

BRANCH_PREFIX = "exp-"

#: main 에 남기는 기록. **자유 `add -A` 는 쓰지 않는다.**
RECORD_PATHS = ("logs", "state")


def branch_name(exp_id: str) -> str:
    """`EXP-007` -> `exp-007`."""
    tail = str(exp_id or "").strip().lower()
    if tail.startswith("exp-"):
        return BRANCH_PREFIX + tail[4:]
    return BRANCH_PREFIX + tail


def _dirty(root: str) -> list[str]:
    return ops.status_porcelain(root, [*RECORD_PATHS, L.experiments_dir()])


def start_experiment(root: str, exp_id: str, *, running: bool = False) -> dict:
    """실험 브랜치로 옮긴다. **실험이 도는 중이면 아무것도 안 한다.**"""
    if running:
        return {"ok": False, "reason": "실험이 도는 중에는 브랜치를 바꾸지 않아요", "branch": ops.current_branch(root)}
    if not ops.inside_worktree(root):
        return {"ok": False, "reason": "git 저장소가 아니에요", "branch": ""}

    before = ops.current_branch(root)
    committed = None
    if _dirty(root):
        # 훅이 쓴 기록이 남아 있으면 먼저 커밋한다 (전환이 실패하지 않게)
        committed = ops.commit(root, f"chore: {before} 기록 정리", list(RECORD_PATHS))
    name = branch_name(exp_id)
    if name in ops.branches(root):
        moved = ops.switch(root, name)
    else:
        ops.create_branch(root, name)
        moved = {"ok": True, "branch": name}
    return {
        "ok": bool(moved.get("ok")),
        "branch": ops.current_branch(root),
        "from": before,
        "committed": committed,
        "reason": moved.get("error", ""),
    }


def record_and_return(root: str, exp_id: str, *, main: str = "main", running: bool = False) -> dict:
    """기록을 `main` 에 남기고 돌아온다 (spec III-6).

    실험 폴더와 `logs/`·`state/` 만 가져온다. 코드는 실험 브랜치에 둔다.
    """
    if running:
        return {"ok": False, "reason": "실험이 도는 중에는 브랜치를 바꾸지 않아요"}
    if not ops.inside_worktree(root):
        return {"ok": False, "reason": "git 저장소가 아니에요"}

    branch = ops.current_branch(root)
    exp_dir = f"{L.experiments_dir()}/{exp_id}"
    out = {"ok": False, "branch": branch, "main": main, "committed": None}

    if _dirty(root):
        ops.commit(root, f"exp: {exp_id} 작업 기록", [*RECORD_PATHS, exp_dir])

    if main not in ops.branches(root):
        out["reason"] = f"{main} 브랜치가 없어요"
        return out
    moved = ops.switch(root, main)
    if not moved.get("ok"):
        out["reason"] = moved.get("error", "브랜치를 못 옮겼어요")
        return out

    if branch != main:
        # **경로를 하나씩** 가져온다. git 은 pathspec 하나가 안 맞으면 통째로
        # 실패해서(빈 `state/` 등) 나머지까지 안 가져온다.
        for item in [*RECORD_PATHS, exp_dir]:
            ops.run(root, ["checkout", branch, "--", item], check=False)
    out["committed"] = ops.commit(root, f"exp: {exp_id} 기록", [*RECORD_PATHS, exp_dir])
    out["ok"] = True
    out["branch"] = ops.current_branch(root)
    return out
