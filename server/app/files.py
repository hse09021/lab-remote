"""등록한 프로젝트 폴더 안의 파일 — 목록·읽기·쓰기·업로드·내려받기·이동·삭제.

🔑 **경로 탈출을 막는 곳이 여기 하나다.** 모든 함수가 `resolve()`를 지난다.

- 화면이 주는 경로는 항상 **기준 폴더(프로젝트 루트나 그 안의 worktree)
  기준 상대 경로**다. 절대 경로·`..` 조각·NUL은 거절한다.
- 심볼릭 링크는 **해소한 결과**가 기준 폴더 안일 때만 따라간다. 밖을 가리키는
  링크는 목록에는 보이되 열거나 쓸 수 없다. 지우기·이름 바꾸기는 링크 **자신**만
  다룬다(따라가지 않는다).
- 루트 자신·`.git`은 지우거나 옮기지 않는다. 실행 중인 학습이 쓰는 폴더도
  지우지 않는다(`busy_paths` — 2단계에서 실행 기록과 이어진다).
"""

from __future__ import annotations

import os
import posixpath
import shutil
import stat as statmod
import tempfile

from . import paths

__all__ = [
    "FileRefused",
    "resolve",
    "base_of",
    "list_dir",
    "read_text",
    "write_text",
    "make",
    "upload",
    "upload_target",
    "download_path",
    "rel_of",
    "move",
    "delete",
    "busy_paths",
    "MAX_TEXT_BYTES",
]

#: 편집기로 여는 글 파일 상한
MAX_TEXT_BYTES = 2 * 1024 * 1024
#: 한 폴더에서 보여 줄 항목 상한 (큰 데이터 폴더에서 화면이 멈추지 않게)
MAX_ENTRIES = 2000
#: 지우거나 옮길 수 없는 이름 (기준 폴더 맨 위)
PROTECTED_TOP = (".git",)


class FileRefused(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


class NotFound(FileRefused):
    """없는 경로."""


def _clean_rel(rel: str) -> str:
    """`a/b/c` 꼴로 정리한다. 루트는 `""`."""
    if rel is None:
        rel = ""
    if not isinstance(rel, str) or "\x00" in rel or "\\" in rel:
        raise FileRefused("경로에 사용할 수 없는 문자가 있어요.")
    if rel.startswith("/") or rel.startswith("~"):
        raise FileRefused("프로젝트 안의 상대 경로만 사용할 수 있어요.")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise FileRefused("`..`는 사용할 수 없어요.")
    return "/".join(parts)


def base_of(root: str, tree: str = "") -> str:
    """기준 폴더. `tree`는 worktree처럼 **프로젝트 안**의 하위 폴더다."""
    root_real = paths.real(root)
    rel = _clean_rel(tree)
    if not rel:
        return root_real
    target = paths.real(os.path.join(root_real, rel))
    if not paths.is_inside(root_real, target) or not os.path.isdir(target):
        raise FileRefused("그 worktree 폴더를 찾을 수 없어요.")
    return target


def resolve(base: str, rel: str, *, follow: bool = True, must_exist: bool = True) -> str:
    """기준 폴더 안의 절대 경로. 밖이면 `FileRefused`.

    `follow=False` 면 마지막 조각의 링크를 해소하지 않는다(지우기·이동용).
    부모 폴더 쪽 링크는 언제나 해소해서 검사한다.
    """
    base_real = paths.real(base)
    clean = _clean_rel(rel)
    joined = os.path.join(base_real, clean) if clean else base_real
    if follow or not clean:
        target = os.path.realpath(joined)
    else:
        parent = os.path.realpath(os.path.dirname(joined))
        target = os.path.join(parent, os.path.basename(joined))
        if not paths.is_inside(base_real, parent):
            raise FileRefused("프로젝트 폴더 외부 경로예요.")
    if not paths.is_inside(base_real, target):
        raise FileRefused("프로젝트 폴더 외부를 가리켜요.")
    if must_exist and not os.path.lexists(target):
        raise NotFound(f"없는 경로예요: {clean or '.'}")
    return target


def _rel_of(base: str, target: str) -> str:
    rel = os.path.relpath(target, paths.real(base)).replace(os.sep, "/")
    return "" if rel == "." else rel


def busy_paths(root: str) -> list[str]:
    """실행 중인 학습이 쓰는 폴더(절대 경로) — 실행 위치와 그 실행의 기록 폴더."""
    from . import runs  # runs가 files를 쓰므로 여기서 부른다

    return runs.busy_dirs(root)


# --- 읽기 --------------------------------------------------------------------


def list_dir(base: str, rel: str = "", *, git_marks: dict[str, str] | None = None) -> dict:
    """폴더 한 칸. 폴더 크기는 재지 않는다(큰 데이터 폴더를 걷지 않으려고).

    `git_marks`는 `{상대경로: "수정"|"새 파일"|"gitignore"|...}`.
    """
    folder = resolve(base, rel)
    if not os.path.isdir(folder):
        raise FileRefused("폴더가 아니에요.")
    base_real = paths.real(base)
    marks = git_marks or {}
    entries = []
    truncated = False
    with os.scandir(folder) as it:
        for i, entry in enumerate(sorted(it, key=lambda e: e.name)):
            if i >= MAX_ENTRIES:
                truncated = True
                break
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            is_link = statmod.S_ISLNK(st.st_mode)
            kind = "dir" if statmod.S_ISDIR(st.st_mode) else "file"
            outside = False
            if is_link:
                target = os.path.realpath(entry.path)
                outside = not paths.is_inside(base_real, target)
                kind = "dir" if (not outside and os.path.isdir(target)) else "file"
            rel_path = _rel_of(base, entry.path)
            entries.append(
                {
                    "name": entry.name,
                    "path": rel_path,
                    "kind": kind,
                    "link": is_link,
                    "outside": outside,
                    "size": st.st_size if kind == "file" and not is_link else None,
                    "mtime": st.st_mtime,
                    "git": marks.get(rel_path + ("/" if kind == "dir" else ""))
                    or marks.get(rel_path)
                    or "",
                }
            )
    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return {"path": _rel_of(base, folder), "entries": entries, "truncated": truncated}


def read_text(base: str, rel: str) -> dict:
    """글 파일 내용. 크거나 글이 아니면 내용 없이 알려 준다."""
    target = resolve(base, rel)
    if not os.path.isfile(target):
        raise FileRefused("파일이 아니에요.")
    size = os.path.getsize(target)
    if size > MAX_TEXT_BYTES:
        return {"path": _rel_of(base, target), "size": size, "text": None, "reason": "too-large"}
    with open(target, "rb") as fh:
        data = fh.read()
    if b"\x00" in data[:8192]:
        return {"path": _rel_of(base, target), "size": size, "text": None, "reason": "binary"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": _rel_of(base, target), "size": size, "text": None, "reason": "binary"}
    return {"path": _rel_of(base, target), "size": size, "text": text, "mtime": os.path.getmtime(target)}


def download_path(base: str, rel: str) -> str:
    target = resolve(base, rel)
    if not os.path.isfile(target):
        raise FileRefused("파일만 다운로드할 수 있어요.")
    return target


# --- 쓰기 --------------------------------------------------------------------


def _check_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\x00" in name or len(name) > 255:
        raise FileRefused("이름이 올바르지 않아요.")


def _atomic_write(target: str, chunks) -> int:
    folder = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(prefix=".labremote-up-", dir=folder)
    total = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
                total += len(chunk)
        if os.path.exists(target):
            shutil.copymode(target, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return total


def write_text(base: str, rel: str, text: str, *, create: bool = False) -> dict:
    """글 파일을 쓴다. `create` 면 새로 만들고, 이미 있으면 거절한다."""
    if not isinstance(text, str):
        raise FileRefused("내용은 텍스트여야 해요.")
    data = text.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise FileRefused("파일이 너무 커요 (편집기에서는 2MB까지).")
    if create:
        target = _new_target(base, rel)
    else:
        target = resolve(base, rel)
        if not os.path.isfile(target):
            raise FileRefused("파일이 아니에요.")
    _atomic_write(target, [data])
    return {"path": _rel_of(base, target), "size": len(data)}


def _new_target(base: str, rel: str) -> str:
    clean = _clean_rel(rel)
    if not clean:
        raise FileRefused("이름을 입력해 주세요.")
    parent_rel, name = posixpath.split(clean)
    _check_name(name)
    parent = resolve(base, parent_rel)
    if not os.path.isdir(parent):
        raise FileRefused("대상 폴더가 없어요.")
    target = os.path.join(parent, name)
    if os.path.lexists(target):
        raise FileRefused(f"이미 있어요: {name}")
    return target


def make(base: str, rel: str, kind: str) -> dict:
    """새 파일(빈 파일) 또는 새 폴더."""
    target = _new_target(base, rel)
    if kind == "dir":
        os.mkdir(target)
    elif kind == "file":
        _atomic_write(target, [b""])
    else:
        raise FileRefused("file이나 dir만 만들 수 있어요.")
    return {"path": _rel_of(base, target), "kind": kind}


def upload_target(base: str, rel: str, *, overwrite: bool = False) -> str:
    """올릴 파일의 절대 경로. 덮어쓰기는 `overwrite` 일 때만."""
    if overwrite:
        try:
            target = resolve(base, rel)
        except NotFound:
            return _new_target(base, rel)
        if os.path.isdir(target) or os.path.islink(target):
            raise FileRefused("폴더나 링크는 덮어쓸 수 없어요.")
        return target
    return _new_target(base, rel)


def upload(base: str, rel: str, chunks, *, overwrite: bool = False) -> dict:
    """올린 파일을 쓴다(동기). 서버는 `upload_target` + `_atomic_write`를 나눠 쓴다."""
    target = upload_target(base, rel, overwrite=overwrite)
    size = _atomic_write(target, chunks)
    return {"path": _rel_of(base, target), "size": size}


def rel_of(base: str, target: str) -> str:
    return _rel_of(base, target)


def _guard_mutation(root: str, base: str, target: str) -> None:
    base_real = paths.real(base)
    if target == base_real:
        raise FileRefused("기준 폴더 자체는 옮기거나 지울 수 없어요.")
    rel = _rel_of(base, target)
    top = rel.split("/", 1)[0]
    if top in PROTECTED_TOP:
        raise FileRefused(f"옮기거나 지울 수 없는 경로예요: {top}")
    # 실행 위치 **자신이나 그걸 품은 폴더**를 막는다. 그 안의 파일 하나를
    # 지우는 건 막지 않는다 — 실행 위치가 프로젝트 루트면 학습 내내 아무것도
    # 못 지우게 된다.
    for busy in busy_paths(root):
        if paths.is_inside(target, busy):
            raise FileRefused("실행 중인 학습이 쓰는 폴더라 지금은 옮기거나 지울 수 없어요.")


def move(root: str, base: str, src: str, dst: str) -> dict:
    """이름 바꾸기·이동. 대상이 있으면 거절한다(덮어쓰지 않는다)."""
    source = resolve(base, src, follow=False)
    _guard_mutation(root, base, source)
    target = _new_target(base, dst)
    if os.path.isdir(source) and not os.path.islink(source) and paths.is_inside(source, target):
        raise FileRefused("폴더를 자기 자신 안으로 옮길 수 없어요.")
    os.rename(source, target)
    return {"from": _rel_of(base, source), "to": _rel_of(base, target)}


def delete(root: str, base: str, rel: str, *, confirm: str) -> dict:
    """지우기. 화면이 한 번 더 물은 뒤 **이름을 그대로** `confirm`으로 보낸다.

    링크는 링크 자신만 지운다.
    """
    target = resolve(base, rel, follow=False)
    _guard_mutation(root, base, target)
    name = os.path.basename(target)
    if confirm != name:
        raise FileRefused("확인용 이름이 일치하지 않아요.")
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
        kind = "dir"
    else:
        os.unlink(target)
        kind = "file"
    return {"path": _rel_of(base, target), "kind": kind}
