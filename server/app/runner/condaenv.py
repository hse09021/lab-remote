"""🧪 실험용 conda 환경이 **우리 환경이 아닌지** — 보안 경계다.

## 왜 이 파일이 있나

`.pth` 파일은 **인터프리터가 뜰 때 실행된다.** `site-packages` 에 한 줄
`import os; os.system(...)` 이 든 `.pth` 가 있으면, 그 환경의 파이썬이 뜨는
순간 돈다 — `import` 를 안 해도 된다.

훅은 래퍼에 박힌 파이썬으로 **도구 호출마다** 뜬다. 오케스트레이터도 그
환경에서 돈다. 둘 다 **샌드박스 밖, 사용자 권한**이다.

그래서 실험용 환경이 우리 환경(`labremote`)이거나 `base` 면, **사람이 승인한
패키지 하나가** 다음 도구 호출에서 훅 프로세스 안의 임의 코드 실행이 된다.
지금까지의 방어가 **전부 우회된다** — 샌드박스·훅·앵커·`projectguard` 가
그 아래에서 돌기 때문이다.

## 어떻게 막나

| | |
|---|---|
| 비교 기준 | **이름이 아니라 실제 경로(`realpath`)** — `labremote` 를 `../labremote` 나 심볼릭 링크로 가리킬 수 있다 |
| 막는 것 | 우리 프로세스의 환경 · 훅 래퍼에 박힌 파이썬의 환경 · `base`(conda 설치 폴더 자신) · 시스템 파이썬(`/usr`·`/usr/local`) |
| 어디서 | **설치기와 학습 실행기 둘 다.** 한쪽만 막으면 다른 쪽으로 들어온다 |

## 환경 이름을 **실행 없이** 푼다

`conda run -n <이름> python -c "print(sys.prefix)"` 로 풀면 **그 파이썬이
뜨면서 `.pth` 가 이미 돈다.** 그래서 쓰지 않는다. 대신 conda 설치 폴더에서
경로를 계산한다 — `<root>/envs/<이름>` 과 `<root>`(= `base`).
"""

from __future__ import annotations

import os
import re
import sys

from .. import paths
from . import sandbox

__all__ = [
    "EnvRefused",
    "NAME_RE",
    "SYSTEM_PREFIXES",
    "BASE_NAMES",
    "candidates",
    "protected_prefixes",
    "resolve",
    "check",
    "require",
    "require_made",
]


class EnvRefused(RuntimeError):
    """실험용으로 쓸 수 없는 환경. **설치도 학습도 하지 않는다.**"""


#: 시스템 파이썬. 여기 깔면 기계 전체에 영향이 간다.
SYSTEM_PREFIXES = ("/usr", "/usr/local", "/opt", "/bin", "/sbin", "/lib", "/etc")

#: `conda run -n` 에 넘길 수 있는 이름. **경로는 받지 않는다** —
#: `../labremote` 처럼 올라가는 이름으로 우리 환경을 가리키는 길을 막는다.
#: 경로로 환경을 지정하려면 `conda run -p` 인데 우리는 쓰지 않는다.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: `base` 를 가리키는 이름들. conda 설치 폴더 자신이고, `conda` 명령이
#: 그 환경의 파이썬으로 돈다 — 거기 `.pth` 를 넣으면 `conda` 가 실행한다.
BASE_NAMES = frozenset({"base", "root", ""})


def candidates(name: str) -> list[str]:
    """이름이 가리킬 수 있는 환경 경로들. **아무것도 실행하지 않는다.**

    이름만 받는다 — 경로는 `check()` 가 먼저 거부한다.
    """
    text = str(name or "").strip()
    out: list[str] = []
    if not text:
        return out
    for root in sandbox.conda_roots():
        if text.lower() in BASE_NAMES:
            out.append(paths.real(root))
        else:
            out.append(paths.real(os.path.join(root, "envs", text)))
    # `CONDA_ENVS_PATH` 로 다른 자리를 쓸 수 있다
    for folder in (os.environ.get("CONDA_ENVS_PATH") or "").split(os.pathsep):
        if folder.strip():
            out.append(paths.real(os.path.join(folder.strip(), text)))
    return list(dict.fromkeys(p for p in out if p))


def _hook_python() -> str:
    """훅 래퍼에 박힌 파이썬. 설치 기록에서 읽는다 (없으면 빈 문자열).

    훅은 **도구 호출마다** 이 파이썬으로 뜬다. 그 환경에 `.pth` 가 들어가면
    잠금 판정 코드 안에서 임의 코드가 돈다.
    """
    import json

    from ..hooks import install as install_mod

    try:
        with open(install_mod.state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    return paths.real(str(data.get("python") or "")) if isinstance(data, dict) else ""


def protected_prefixes() -> dict[str, list[str]]:
    """실험용으로 쓸 수 없는 환경 경로들. 전부 `realpath` 다.

    **종류마다 비교 규칙이 다르다.** 모든 환경이 conda 루트 **안**에 있으니
    루트를 "포함" 으로 비교하면 정상 환경까지 전부 거부된다.

    | 종류 | 거부하는 경우 |
    |---|---|
    | `envs` (우리 환경·훅 환경) | 같거나 · 안이거나 · 그걸 포함 |
    | `roots` (`base`) | **같거나 · 그걸 포함** (안은 정상 — 실험 환경이 거기 산다) |
    | `system` | 같거나 · 안이거나 · 그걸 포함 |
    """
    envs: list[str] = []

    # 1. 지금 이 프로세스의 환경 — 오케스트레이터·CLI 가 여기서 돈다
    envs.append(paths.real(sys.prefix))
    if sys.base_prefix != sys.prefix:
        envs.append(paths.real(sys.base_prefix))

    # 2. 훅 래퍼에 박힌 파이썬의 환경 — 도구 호출마다 뜬다
    hook_py = _hook_python()
    if hook_py:
        # `<prefix>/bin/python` → `<prefix>`
        envs.append(paths.real(os.path.dirname(os.path.dirname(hook_py))))

    # 3. `base` — conda 설치 폴더 자신. `conda` 명령이 그 파이썬으로 돈다.
    roots = [paths.real(r) for r in sandbox.conda_roots()]

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

    **던지지 않는다** — `doctor` 와 실행기가 같은 함수를 쓴다.
    환경이 아직 없으면(만들기 전) `ok` 다 — 이름이 보호 대상과 겹칠 때만 막는다.
    """
    text = str(name or "").strip()
    out = {"ok": False, "name": text, "prefix": "", "reason": ""}
    if not text:
        out["reason"] = "conda 환경 이름이 비어 있어요 (specifications/Config.yaml 의 env.conda)"
        return out
    if text.startswith("["):
        out["reason"] = f"환경 이름이 아직 자리표시예요: {text}"
        return out
    if not NAME_RE.match(text):
        out["reason"] = (
            f"환경 이름 규칙에 안 맞아요: {text!r} · 영문·숫자로 시작하고 "
            "`.`·`_`·`-` 만 쓸 수 있어요. 경로는 받지 않아요 — `../labremote` "
            "처럼 올라가는 이름으로 우리 환경을 가리키는 길을 막아요."
        )
        return out
    if text.lower() in BASE_NAMES:
        out["reason"] = (
            "base 환경에는 설치하지 않아요 — conda 명령이 그 환경의 파이썬으로 "
            "돌아서, .pth 한 줄이 샌드박스 밖에서 실행돼요"
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
                    f"{text} 는 우리 코드가 도는 환경이에요 ({path}) — 거기 설치하면 "
                    ".pth 같은 자동 실행 코드가 훅·오케스트레이터 프로세스 안, "
                    "샌드박스 **밖**에서 돌아요. 실험용 환경을 따로 만들어 주세요: "
                    f"conda create -n {text}-exp python=3.11"
                )
                return out

    out["prefix"] = resolve(text)
    out["ok"] = True
    return out


def require_made(name: str) -> str:
    """환경이 **실제로 있어야** 한다. 없으면 `EnvRefused` (사람이 읽을 문구).

    `check()` 는 아직 없는 환경도 통과시킨다 — `Config.yaml` 에 만들기 전에
    이름을 적을 수 있어야 하기 때문이다. 하지만 **설치**는 환경이 있어야
    한다. 없는 환경에 승인하면 `pkg` 와 같은 함정이 된다 — 사람이 승인했고
    기록에 남고 아무 일도 안 일어난다.
    """
    got = check(name)
    if not got["ok"]:
        raise EnvRefused(got["reason"])
    if not got["prefix"]:
        raise EnvRefused(
            f"실험 환경 {name} 이 없어요 → docs/SETUP.md 의 "
            f'"프로젝트마다 별도 conda 환경" 을 먼저 해 주세요: '
            f"conda create -n {name} python=3.11 -y"
        )
    return got["prefix"]


def require(name: str) -> str:
    """검사하고 환경 경로를 돌려준다. 안 되면 `EnvRefused`."""
    got = check(name)
    if not got["ok"]:
        raise EnvRefused(got["reason"])
    return got["prefix"]
