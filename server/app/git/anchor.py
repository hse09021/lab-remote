"""📌 git 기록 앵커 — **이전 커밋을 바꿔치기하면 들킨다.**

## 왜 필요한가

T4 는 `.git` 이 **코드를 실행하게 만드는 설정**을 막았습니다. 하지만 `.git` 은
프로젝트 안이고 샌드박스는 작업 디렉터리 쓰기를 못 막으므로(M4), AI 가 쓴
코드는 **기록 자체**도 바꿀 수 있습니다.

    git branch -D exp-003          실험 브랜치를 지운다
    git commit --amend             이전 커밋을 바꿔치기한다
    git reset --hard <옛 커밋>      기록을 되감는다
    .git/refs/heads/main 을 직접 쓴다

학습 bwrap 은 `.git` 을 `--ro-bind` 로 덮지만(T5), **Claude 의 Bash 샌드박스는
못 막습니다** — 작업 폴더는 언제나 쓰기 가능합니다. 훅의 허용 목록은 읽기
전용 git 명령만 통과시키지만, 명령 문자열 분석은 완전할 수 없습니다(0-5 의
래퍼 62종).

그래서 **막는 대신 들키게** 합니다 — 승인 로그와 같은 방식입니다.

## 어떻게

오케스트레이터가 커밋·브랜치 전환을 할 때마다 그 브랜치의 HEAD 해시를
`lab.db` 의 `anchors` 표에 적습니다. `lab.db` 는 `server/data/` 아래라
샌드박스 안에서 쓰기가 실패합니다(M1b) — 그게 기준이 될 수 있는 이유입니다.

다음 git 작업 전과 루프 시작 전에 대조합니다.

| 상태 | 판정 |
|---|---|
| 기록된 해시가 지금 HEAD 와 같다 | ✔ |
| 기록된 해시가 지금 HEAD 의 **조상**이다 | ✔ 앞으로 나아간 것 |
| 기록된 해시가 **없어졌다** | ✘ 커밋이 사라졌어요 (amend·gc) |
| 기록된 해시가 조상이 **아니다** | ✘ 기록이 되감겼어요 (reset·force) |
| 브랜치가 **없어졌다** | ✘ 브랜치가 사라졌어요 |

`git fsck --connectivity-only` 를 가볍게 같이 돌려 객체가 깨졌는지 봅니다.
"""

from __future__ import annotations

import subprocess

from .. import paths
from . import ops

__all__ = [
    "KIND",
    "record",
    "record_all",
    "verify",
    "fsck",
    "describe",
]

#: `anchors.kind`
KIND = "git_head"

#: `fsck` 는 큰 저장소에서 느리다. 연결성만 본다.
FSCK_TIMEOUT_SEC = 30


def _rev(root: str, ref: str) -> str:
    """`ref` 의 커밋 해시. 없으면 빈 문자열."""
    try:
        return ops.run(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"], guarded=False).strip()
    except ops.GitError:
        return ""


def _exists(root: str, sha: str) -> bool:
    """그 객체가 **커밋으로** 아직 있나."""
    if not sha:
        return False
    try:
        out = ops.run(root, ["cat-file", "-t", sha], guarded=False).strip()
    except ops.GitError:
        return False
    return out == "commit"


def _is_ancestor(root: str, old: str, new: str) -> bool:
    try:
        ops.run(root, ["merge-base", "--is-ancestor", old, new], guarded=False)
        return True
    except ops.GitError:
        return False


def record(conn, project: str, root: str, branch: str = "", *, note: str = "") -> dict:
    """지금 HEAD 를 기준값으로 적는다. 커밋·전환 **뒤에** 부른다."""
    from ..store import anchors as A

    name = branch or ops.current_branch(root)
    sha = _rev(root, name)
    if not sha:
        return {"ok": False, "branch": name, "reason": "커밋이 아직 없어요"}
    got = A.put(conn, project, KIND, sha, key=name, note=note)
    return {"ok": True, "branch": name, "sha": sha, "anchor": got}


def record_all(conn, project: str, root: str, *, note: str = "") -> list[dict]:
    """있는 브랜치 전부를 적는다."""
    out = []
    for name in ops.branches(root):
        out.append(record(conn, project, root, name, note=note))
    return out


def verify(conn, project: str, root: str) -> dict:
    """적어 둔 기준값과 지금 `.git` 을 대조한다. **아무것도 고치지 않는다.**

    `{"ok": bool, "problems": [...], "checked": n}`.
    """
    from ..store import anchors as A

    root = paths.real(root)
    problems: list[str] = []
    saved = A.listing(conn, project, KIND)
    live = set(ops.branches(root))

    for item in saved:
        name, sha = item["key"], item["value"]
        if name not in live:
            problems.append(
                f"{name} 브랜치가 사라졌어요 (앵커: {sha[:12]} · {item['at']})"
            )
            continue
        if not _exists(root, sha):
            problems.append(
                f"{name} 의 커밋 {sha[:12]} 가 없어졌어요 — amend 나 되감기예요 "
                f"(앵커: {item['at']})"
            )
            continue
        head = _rev(root, name)
        if head == sha:
            continue
        if not _is_ancestor(root, sha, head):
            problems.append(
                f"{name} 이 되감겼어요 — 앵커 {sha[:12]} 가 지금 HEAD "
                f"{head[:12]} 의 조상이 아니에요 (앵커: {item['at']})"
            )
    return {"ok": not problems, "problems": problems, "checked": len(saved)}


def fsck(root: str) -> dict:
    """`git fsck --connectivity-only` 를 가볍게. 깨진 객체를 본다.

    느릴 수 있어서 **시간 제한**을 두고, 넘으면 "못 봤다" 로 둔다 — 추측하지
    않는다. 던지지 않는다.
    """
    argv = [
        "git", "--no-pager", *ops.safe_config(), "-C", paths.real(root),
        "fsck", "--connectivity-only", "--no-progress", "--no-dangling",
    ]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True,
            timeout=FSCK_TIMEOUT_SEC, env=ops.safe_env(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": True, "ran": False, "reason": "시간이 오래 걸려서 건너뛰었어요"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": True, "ran": False, "reason": f"못 돌렸어요: {exc}"}
    text = ((done.stderr or "") + (done.stdout or "")).strip()
    if done.returncode == 0:
        return {"ok": True, "ran": True, "reason": ""}
    return {"ok": False, "ran": True, "reason": text[:400]}


def check(conn, project: str, root: str, *, with_fsck: bool = True) -> dict:
    """앵커 대조 + (선택) `fsck`. 루프와 `doctor` 가 같은 함수를 쓴다."""
    got = verify(conn, project, root)
    problems = list(got["problems"])
    if with_fsck:
        scanned = fsck(root)
        if not scanned["ok"]:
            problems.append(f"git fsck 가 깨진 객체를 찾았어요: {scanned['reason']}")
        got["fsck"] = scanned
    got["problems"] = problems
    got["ok"] = not problems
    return got


def describe(report: dict) -> str:
    if report.get("ok"):
        return f"git 기록이 앵커와 맞아요 (브랜치 {report.get('checked', 0)}개)."
    lines = ["git 기록이 앵커와 어긋나요 — 이전 기록이 바뀌었을 수 있어요:"]
    lines += [f"  · {p}" for p in report.get("problems") or []]
    lines.append(
        "앵커는 lab.db 에 있고 AI 가 못 씁니다(M1b). 되돌리지 않았어요 — "
        "무엇이 사라졌는지 사람이 봐 주세요."
    )
    return "\n".join(lines)
