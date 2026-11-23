"""🧪 실행·설치에 쓸 conda 환경이 **lab.remote 자신의 환경이 아닌지.**

## 왜 이 파일이 있나

`.pth` 파일은 **인터프리터가 뜰 때 실행된다.** `site-packages`에 한 줄
`import os; os.system(...)`이 든 `.pth`가 있으면, 그 환경의 파이썬이 뜨는
순간 돈다 — `import`를 안 해도 된다.

lab.remote 서버는 `labremote` 환경에서 돈다. `conda` 명령은 `base`의
파이썬으로 돈다. 그래서 실험용 패키지를 그 둘에 깔면 **서버나 conda가 뜰 때
임의 코드가 돈다.** v3의 Conda 화면은 `base`·`labremote`를 보호한다
(docs/v3/PLAN.md 4.1 conda).

## 어떻게 막나

| | |
|---|---|
| 비교 기준 | **이름이 아니라 실제 경로(`realpath`)** — 심볼릭 링크나 `../`로 가리킬 수 있다 |
| 막는 것 | 지금 이 프로세스의 환경 · `base`(conda 설치 폴더 자신) · 시스템 파이썬 |

## 환경 이름을 **실행 없이** 푼다

`conda run -n <이름> python -c "print(sys.prefix)"`로 풀면 **그 파이썬이
뜨면서 `.pth`가 이미 돈다.** 그래서 conda 설치 폴더에서 경로를 계산한다 —
`<root>/envs/<이름>`과 `<root>`(= `base`).
"""

from __future__ import annotations

import os
import re
import sys

from .. import paths

__all__ = [
    "EnvRefused",
    "NAME_RE",
    "SYSTEM_PREFIXES",
    "BASE_NAMES",
    "CONDA_GUESSES",
    "conda_roots",
    "candidates",
    "protected_prefixes",
    "resolve",
    "check",
    "require",
    "require_made",
]


class EnvRefused(RuntimeError):
    """쓸 수 없는 환경. **설치도 실행도 하지 않는다.**"""


#: 시스템 파이썬. 여기 깔면 기계 전체에 영향이 간다.
SYSTEM_PREFIXES = ("/usr", "/usr/local", "/opt", "/bin", "/sbin", "/lib", "/etc")

#: `conda run -n`에 넘길 수 있는 이름. **경로는 받지 않는다** —
#: `../labremote`처럼 올라가는 이름으로 우리 환경을 가리키는 길을 막는다.
#: 경로로 환경을 지정하려면 `conda run -p` 인데 우리는 쓰지 않는다.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: `base`를 가리키는 이름들. conda 설치 폴더 자신이고, `conda` 명령이
#: 그 환경의 파이썬으로 돈다 — 거기 `.pth`를 넣으면 `conda`가 실행한다.
BASE_NAMES = frozenset({"base", "root", ""})


#: 환경 변수로 conda를 못 찾았을 때 볼 흔한 자리
CONDA_GUESSES = (
    "~/miniconda3",
    "~/anaconda3",
    "~/miniforge3",
    "~/mambaforge",
    "~/micromamba",
    "/opt/conda",
)


def conda_roots() -> list[str]:
    """conda·mamba 설치 폴더. 환경 변수로 찾고, 없으면 흔한 자리를 본다."""
    out: list[str] = []
    exe = os.environ.get("CONDA_EXE") or ""
    if exe:
        out.append(os.path.dirname(os.path.dirname(paths.real(exe))))
    prefix = os.environ.get("CONDA_PREFIX") or ""
    if prefix:
        real = paths.real(prefix)
        parent = os.path.dirname(os.path.dirname(real))
        out.append(parent if os.path.basename(os.path.dirname(real)) == "envs" else real)
    for name in ("MAMBA_ROOT_PREFIX", "CONDA_ROOT"):
        value = os.environ.get(name) or ""
        if value:
            out.append(paths.real(value))
    if not out:
        for guess in CONDA_GUESSES:
            target = paths.real(guess)
            if os.path.isdir(target):
                out.append(target)
    return sorted({p for p in out if p and p != os.sep and os.path.isdir(p)})


def candidates(name: str) -> list[str]:
    """이름이 가리킬 수 있는 환경 경로들. **아무것도 실행하지 않는다.**

    이름만 받는다 — 경로는 `check()`가 먼저 거부한다.
    """
    text = str(name or "").strip()
    out: list[str] = []
    if not text:
        return out
    for root in conda_roots():
        if text.lower() in BASE_NAMES:
            out.append(paths.real(root))
        else:
            out.append(paths.real(os.path.join(root, "envs", text)))
    # `CONDA_ENVS_PATH`로 다른 자리를 쓸 수 있다
    for folder in (os.environ.get("CONDA_ENVS_PATH") or "").split(os.pathsep):
        if folder.strip():
            out.append(paths.real(os.path.join(folder.strip(), text)))
    return list(dict.fromkeys(p for p in out if p))



def protected_prefixes() -> dict[str, list[str]]:
    """실험용으로 쓸 수 없는 환경 경로들. 전부 `realpath` 다.

    **종류마다 비교 규칙이 다르다.** 모든 환경이 conda 루트 **안**에 있으니
    루트를 "포함"으로 비교하면 정상 환경까지 전부 거부된다.

    | 종류 | 거부하는 경우 |
    |---|---|
    | `envs` (lab.remote 환경) | 같거나 · 안이거나 · 그걸 포함 |
    | `roots` (`base`) | **같거나 · 그걸 포함** (안은 정상 — 실험 환경이 거기 산다) |
    | `system` | 같거나 · 안이거나 · 그걸 포함 |
    """
    envs: list[str] = []

    # 1. 지금 이 프로세스의 환경 — lab.remote 서버·CLI가 여기서 돈다
    envs.append(paths.real(sys.prefix))
    if sys.base_prefix != sys.prefix:
        envs.append(paths.real(sys.base_prefix))

    # 2. `base` — conda 설치 폴더 자신. `conda` 명령이 그 파이썬으로 돈다.
    roots = [paths.real(r) for r in conda_roots()]

    return {
        "envs": list(dict.fromkeys(p for p in envs if p)),
        "roots": list(dict.fromkeys(p for p in roots if p)),
        "system": [paths.real(p) for p in SYSTEM_PREFIXES],
    }


def resolve(name: str) -> str:
    """이름이 가리키는 **실제로 있는** 환경 경로. 없으면 빈 문자열."""
    for path in candidates(name):
        if os.path.isdir(path):
            return path
    return ""


def check(name: str) -> dict:
    """실험용으로 써도 되나. `{"ok", "name", "prefix", "reason"}`.

    **던지지 않는다** — `doctor`·실행·Conda 화면이 같은 함수를 쓴다.
    환경이 아직 없으면(만들기 전) `ok` 다 — 이름이 보호 대상과 겹칠 때만 막는다.
    """
    text = str(name or "").strip()
    out = {"ok": False, "name": text, "prefix": "", "reason": ""}
    if not text:
        out["reason"] = "conda 환경 이름이 비어 있어요"
        return out
    if text.startswith("["):
        out["reason"] = f"환경 이름이 아직 자리표시예요: {text}"
        return out
    if not NAME_RE.match(text):
        out["reason"] = (
            f"환경 이름 규칙에 안 맞아요: {text!r} · 영문·숫자로 시작하고 "
            "`.`·`_`·`-`만 쓸 수 있어요. 경로는 받지 않아요."
        )
        return out
    if text.lower() in BASE_NAMES:
        out["reason"] = (
            "base 환경은 보호돼요 — conda 명령이 그 환경의 파이썬으로 돌아요"
        )
        return out

    bad = protected_prefixes()
    # 이름으로 풀 수 있는 **모든** 후보를 본다. 하나라도 보호 대상과 겹치면
    # 거부한다 — 환경이 아직 없어도 나중에 그 자리에 생길 수 있다.
    pairs = (
        [(g, True) for g in bad["envs"]]
        + [(g, False) for g in bad["roots"]]
        + [(g, True) for g in bad["system"]]
    )
    for path in candidates(text) or []:
        for guard, inside_too in pairs:
            hit = path == guard or paths.is_inside(path, guard)
            if inside_too and paths.is_inside(guard, path):
                hit = True
            if hit:
                out["prefix"] = path
                out["reason"] = (
                    f"{text}는 lab.remote가 도는 환경이라 보호돼요 ({path}). "
                    "실험용 환경을 따로 만들어 주세요: "
                    f"conda create -n {text}-exp python=3.11"
                )
                return out

    out["prefix"] = resolve(text)
    out["ok"] = True
    return out


def require_made(name: str) -> str:
    """환경이 **실제로 있어야** 한다. 없으면 `EnvRefused` (사람이 읽을 문구).

    `check()`는 아직 없는 환경도 통과시킨다. 하지만 설치·실행은 환경이
    있어야 한다 — 없는 환경에 설치를 누르면 아무 일도 안 일어난다.
    """
    got = check(name)
    if not got["ok"]:
        raise EnvRefused(got["reason"])
    if not got["prefix"]:
        raise EnvRefused(
            f"conda 환경 {name}이 없어요: conda create -n {name} python=3.11 -y"
        )
    return got["prefix"]


def require(name: str) -> str:
    """검사하고 환경 경로를 돌려준다. 안 되면 `EnvRefused`."""
    got = check(name)
    if not got["ok"]:
        raise EnvRefused(got["reason"])
    return got["prefix"]
