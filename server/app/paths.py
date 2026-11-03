"""경로 정규화와 안전 비교.

훅이 "프로젝트 폴더 밖" 을 판정하는 유일한 근거다. 이 모듈이 틀리면
잠긴 항목 ①이 그대로 뚫리므로, 모든 함수는 tests/test_paths.py 가 지킨다.

규칙 셋:
1. 비교 전에 **양쪽 다** `os.path.realpath` 로 해소한다. 프로젝트 루트가
   심볼릭 링크면 해소하지 않은 비교는 전부 "밖" 으로 오판한다.
2. 안쪽 판정은 `startswith(root + os.sep)` 로 한다. `os.sep` 을 빼면
   형제 폴더 `<root>-old` 가 안쪽으로 보인다.
3. 아직 없는 파일에도 동작한다 (`realpath` 는 중간 디렉터리의 링크만 해소).

리눅스 전용이라 대소문자는 구분한 채 둔다 (`normcase` 를 쓰지 않는다).
표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

import os
import re

__all__ = [
    "real",
    "safe_resolve",
    "is_inside",
    "is_inside_any",
    "rel_or_none",
    "match_glob",
    "match_globs",
]


def real(path: str) -> str:
    """심볼릭 링크와 `..`, `~` 를 모두 해소한 절대 경로. 멱등하다."""
    return os.path.realpath(os.path.expanduser(path))


def safe_resolve(raw: str, cwd: str) -> str:
    """도구가 준 경로를 `cwd` 기준으로 해소한다.

    `raw` 가 비면 `cwd` 자신을 가리킨다.
    """
    p = os.path.expanduser(raw)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def is_inside(root_real: str, target_real: str) -> bool:
    """`target_real` 이 `root_real` 안(또는 루트 자신)인가.

    둘 다 이미 `real()` 로 해소된 절대 경로여야 한다.
    """
    if not root_real or not target_real:
        return False
    root = root_real.rstrip(os.sep) or os.sep
    if root == os.sep:  # 루트가 '/' 면 모든 절대 경로가 안쪽
        return target_real.startswith(os.sep)
    if target_real == root:
        return True
    return target_real.startswith(root + os.sep)


def is_inside_any(roots: list[str] | tuple[str, ...], target_real: str) -> bool:
    """예외 허용 경로(`extraWritableRoots`) 판정용."""
    return any(is_inside(real(r), target_real) for r in roots if r)


def rel_or_none(root: str, target_real: str) -> str | None:
    """프로젝트 루트 기준 상대 경로. 밖이면 `None`.

    루트 자신은 `"."` 로 돌려준다. 구분자는 항상 `/` 다 (glob 과 맞추려고).
    `root` 는 해소되지 않은 값을 줘도 된다 — 안에서 `real()` 한다.
    """
    root_real = real(root)
    if not is_inside(root_real, target_real):
        return None
    base = root_real.rstrip(os.sep) or os.sep
    if target_real == base:
        return "."
    return os.path.relpath(target_real, base).replace(os.sep, "/")


# --- glob 매칭 -------------------------------------------------------------
# fnmatch 의 '*' 는 '/' 까지 삼켜서 `experiments/*/config.yaml` 이
# `experiments/a/b/config.yaml` 에도 걸린다. 그래서 직접 번역한다.

_cache: dict[str, re.Pattern[str]] = {}


def _compile(pattern: str) -> re.Pattern[str]:
    cached = _cache.get(pattern)
    if cached is not None:
        return cached

    out = ["(?s)\\A"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    i += 1
                    out.append("(?:[^/]+/)*")  # '**/' = 0개 이상의 폴더
                else:
                    out.append(".*")  # '**' = 구분자 포함 아무거나
            else:
                i += 1
                out.append("[^/]*")  # '*' = 한 칸 안에서만
        elif c == "?":
            i += 1
            out.append("[^/]")
        else:
            i += 1
            out.append(re.escape(c))
    out.append("\\Z")

    compiled = re.compile("".join(out))
    _cache[pattern] = compiled
    return compiled


def match_glob(rel: str, pattern: str) -> bool:
    """`rel`(프로젝트 루트 기준 상대 경로)이 `pattern` 에 맞는가."""
    if not rel or not pattern:
        return False
    rel = rel.strip("/")
    if _compile(pattern).match(rel) is not None:
        return True
    # `.claude/**` 는 폴더 자신(`.claude`)도 대상으로 본다.
    if pattern.endswith("/**"):
        return _compile(pattern[:-3]).match(rel) is not None
    return False


def match_globs(rel: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(match_glob(rel, p) for p in patterns)
