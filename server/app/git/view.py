"""git 읽기 — 화면용 상태·diff·브랜치·worktree.

모든 호출이 `ops.run()` 을 지난다(안전 옵션 + `.git` 검사). 여기서는 **읽기만**
한다 — 커밋·합치기·worktree 만들기/정리는 뒤 단계에서 붙는다.

git 저장소가 아니거나 `.git` 검사에 걸리면 예외 대신 `{"state": ...}` 로
알려 준다. 화면은 그 상태를 그대로 보여 준다.
"""

from __future__ import annotations

import os

from .. import paths
from . import ops
from .guard import GitRefused

__all__ = [
    "summary",
    "status",
    "marks_for",
    "diff",
    "worktrees",
    "main_branch",
    "MAX_DIFF_BYTES",
]

MAX_DIFF_BYTES = 512 * 1024

#: porcelain XY → 화면 이름
_LABELS = {
    "M": "수정",
    "T": "수정",
    "A": "새 파일",
    "D": "삭제",
    "R": "이름 바뀜",
    "C": "복사",
    "U": "충돌",
}


def _label(xy: str) -> str:
    if xy == "??":
        return "새 파일"
    if xy == "!!":
        return "gitignore"
    if "U" in xy or xy in ("AA", "DD"):
        return "충돌"
    for ch in (xy[0], xy[1]):
        if ch in _LABELS:
            return _LABELS[ch]
    return "수정"


def _state_of(root: str) -> dict | None:
    """git 을 못 쓰는 사유. 쓸 수 있으면 `None`."""
    if not os.path.isdir(root):
        return {"state": "missing", "reason": "폴더가 없어요"}
    try:
        if not ops.inside_worktree(root):
            return {"state": "none", "reason": "git 저장소가 아니에요"}
    except GitRefused as exc:
        return {"state": "refused", "reason": str(exc)}
    return None


def _parse_v2(out: str) -> dict:
    """`status --porcelain=v2 --branch -z`."""
    info = {"branch": "", "head": "", "upstream": "", "ahead": 0, "behind": 0, "changes": []}
    items = out.split("\x00")
    i = 0
    while i < len(items):
        line = items[i]
        i += 1
        if not line:
            continue
        if line.startswith("# branch.oid "):
            oid = line.split(" ", 2)[2]
            info["head"] = "" if oid == "(initial)" else oid[:7]
        elif line.startswith("# branch.head "):
            head = line.split(" ", 2)[2]
            info["branch"] = "" if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            parts = line.split(" ")
            info["ahead"] = abs(int(parts[2]))
            info["behind"] = abs(int(parts[3]))
        elif line[0] == "1":
            parts = line.split(" ", 8)
            info["changes"].append({"path": parts[8], "xy": parts[1].replace(".", " ")})
        elif line[0] == "2":
            parts = line.split(" ", 9)
            orig = items[i] if i < len(items) else ""
            i += 1
            info["changes"].append({"path": parts[9], "from": orig, "xy": parts[1].replace(".", " ")})
        elif line[0] == "u":
            parts = line.split(" ", 10)
            info["changes"].append({"path": parts[10], "xy": "UU"})
        elif line[0] == "?":
            info["changes"].append({"path": line[2:], "xy": "??"})
        elif line[0] == "!":
            info["changes"].append({"path": line[2:], "xy": "!!"})
    for change in info["changes"]:
        change["label"] = _label(change["xy"])
    return info


def status(root: str, *, ignored: bool = False, pathspec: str = "") -> dict:
    """브랜치·커밋·앞섬/뒤처짐·바뀐 파일. 경로는 **`root` 기준**이다."""
    bad = _state_of(root)
    if bad:
        return bad
    args = ["status", "--porcelain=v2", "--branch", "-z", "--no-renames"]
    if ignored:
        args.append("--ignored=matching")
    args += ["--", pathspec or "."]
    try:
        info = _parse_v2(ops.run(root, args))
        prefix = ops.run(root, ["rev-parse", "--show-prefix"]).strip()
    except (GitRefused, ops.GitError) as exc:
        return {"state": "error", "reason": str(exc)}
    if prefix:
        # porcelain 경로는 저장소 맨 위 기준이다 — 프로젝트가 하위 폴더면 잘라 낸다
        for change in info["changes"]:
            p = change["path"]
            change["path"] = p[len(prefix):] if p.startswith(prefix) else "../" + p
    info["state"] = "ok"
    info["changed"] = sum(1 for c in info["changes"] if c["xy"] != "!!")
    if not ignored:
        info["changes"] = [c for c in info["changes"] if c["xy"] != "!!"]
    return info


def summary(root: str) -> dict:
    """목록·헤더용 한 줄."""
    info = status(root)
    if info.get("state") != "ok":
        return info
    return {
        "state": "ok",
        "branch": info["branch"],
        "head": info["head"],
        "changed": info["changed"],
        "ahead": info["ahead"],
        "behind": info["behind"],
    }


def marks_for(base: str, rel_dir: str) -> dict[str, str]:
    """파일 표의 git 칸. `{폴더 기준 상대경로(폴더는 끝에 /): 이름}`."""
    info = status(base, ignored=True, pathspec=rel_dir or ".")
    if info.get("state") != "ok":
        return {}
    marks: dict[str, str] = {}
    prefix = (rel_dir.strip("/") + "/") if rel_dir.strip("/") else ""
    for change in info["changes"]:
        path = change["path"]
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        head, sep, tail = rest.partition("/")
        # 하위 폴더 안의 변경은 그 폴더 칸에 "수정" 으로 모은다
        if sep and tail:
            key = prefix + head + "/"
            label = "gitignore" if change["label"] == "gitignore" else "수정"
            if key not in marks or (marks[key] == "gitignore" and label != "gitignore"):
                marks[key] = label
        else:
            marks[prefix + rest] = change["label"]
    return marks


def diff(root: str, path: str = "", *, staged: bool = False) -> dict:
    """unified diff. 외부 diff·textconv 를 끈다. 너무 길면 자른다."""
    bad = _state_of(root)
    if bad:
        return bad
    args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv"]
    if staged:
        args.append("--cached")
    args += ["--", path or "."]
    try:
        out = ops.run(root, args)
    except (GitRefused, ops.GitError) as exc:
        return {"state": "error", "reason": str(exc)}
    truncated = len(out.encode("utf-8")) > MAX_DIFF_BYTES
    if truncated:
        out = out.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", "ignore")
    return {"state": "ok", "diff": out, "truncated": truncated}


def main_branch(root: str) -> str:
    """"main 대비" 의 main. `main` → `master` → 첫 worktree 의 브랜치."""
    names = ops.branches(root)
    for candidate in ("main", "master"):
        if candidate in names:
            return candidate
    return names[0] if names else ""


def _parse_worktrees(out: str) -> list[dict]:
    rows, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                rows.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            cur = {"path": value}
        elif key == "HEAD":
            cur["head"] = value[:7]
        elif key == "branch":
            cur["branch"] = value.removeprefix("refs/heads/")
        elif key in ("detached", "bare", "locked", "prunable"):
            cur[key] = True
    if cur:
        rows.append(cur)
    return rows


def worktrees(root: str) -> dict:
    """worktree 목록. `main` 에 합쳐진 것은 `merged` 로 **표시만** 한다."""
    bad = _state_of(root)
    if bad:
        return bad
    root_real = paths.real(root)
    try:
        rows = _parse_worktrees(ops.run(root, ["worktree", "list", "--porcelain"]))
        main = main_branch(root)
        merged = set()
        if main:
            out = ops.run(root, ["branch", "--merged", main, "--format=%(refname:short)"])
            merged = {line.strip() for line in out.splitlines() if line.strip()}
    except (GitRefused, ops.GitError) as exc:
        return {"state": "error", "reason": str(exc)}

    def worked_on(branch: str) -> bool:
        """만든 뒤 커밋이 있었나 — 막 만든 브랜치는 main 과 같은 커밋이라 `--merged` 에 걸린다.

        reflog 가 "만들었음" 한 줄뿐이면 아직 아무 일도 안 한 것이다. reflog 가 없으면 판단하지 않는다(합쳐짐으로 둔다).
        """
        try:
            out = ops.run(root, ["reflog", "show", "--format=%H", f"refs/heads/{branch}", "--"])
        except (GitRefused, ops.GitError):
            return True
        n = len([line for line in out.splitlines() if line.strip()])
        return n != 1

    out_rows = []
    for i, row in enumerate(rows):
        path = paths.real(row.get("path", ""))
        rel = paths.rel_or_none(root_real, path)
        branch = row.get("branch", "")
        item = {
            "path": path,
            "rel": rel,  # 프로젝트 밖이면 None — 파일 표로 열 수 없다
            "branch": branch,
            "head": row.get("head", ""),
            "primary": i == 0,
            "detached": bool(row.get("detached")),
            "prunable": bool(row.get("prunable")),
            "merged": bool(branch) and branch != main and branch in merged and worked_on(branch),
            "ahead": None,
            "changed": None,
        }
        if branch and main and branch != main:
            try:
                item["ahead"] = int(ops.run(root, ["rev-list", "--count", f"{main}..{branch}"]).strip() or 0)
            except (GitRefused, ops.GitError, ValueError):
                pass
        if rel is not None and os.path.isdir(path):
            info = status(path)
            if info.get("state") == "ok":
                item["changed"] = info["changed"]
        out_rows.append(item)
    return {"state": "ok", "main": main, "worktrees": out_rows}
