"""📦 패키지 설치 — **오케스트레이터가 샌드박스 밖에서** 돌린다.

## 왜 오케스트레이터가 하나

S1 의 M3 실측: Claude 의 Bash 로 `pip install` 을 돌리면 conda 환경이
프로젝트 밖이라 샌드박스가 쓰기를 **버린다.** 프로그램에는 성공으로 보이고
실제로는 아무 일도 안 일어난다. 사람이 승인해도 그렇다.

그래서 승인 뒤 **오케스트레이터가** 돌린다. 샌드박스 밖이므로 들어가는
값은 `runner/pkgspec.py` 가 전부 검증한 것뿐이다.

## 🔑 공용 캐시를 **쓰지 않는다**

`~/lab-cache` 는 **모든 프로젝트가 쓰기로 공유**한다(샌드박스 `allowWrite` 의
유일한 바깥). 그래서 한 프로젝트의 AI 코드가 캐시를 오염시킬 수 있다 —
`pip` 휠 캐시에 든 것은 **다음에 설치될 코드**다.

| 누가 | 캐시를 쓰나 | 가둬지나 |
|---|---|---|
| 학습 프로세스 | 네 | **네** (bwrap 안) |
| Claude 의 Bash | `TMPDIR` 만 | **네** (Bash 샌드박스 안) |
| **이 모듈** | **아니요** | 아니요 (샌드박스 밖, 사용자 권한) |

그래서 `--no-cache-dir` 를 **반드시** 붙이고, 넘기는 환경에서 캐시 변수를
**전부 뺀다**(`PIP_CACHE_DIR`·`HF_HOME`·`XDG_CACHE_HOME` …). 테스트로 고정한다.

## 왜 휠만 받나

소스 배포는 설치할 때 `setup.py` 를 **실행**한다. 샌드박스 밖 임의 코드
실행이다. `--only-binary=:all:` 이 기본이고, 풀려면 요청(`allowSource`)과
사람의 승인(`--allow-source`)이 **둘 다** 맞아야 한다.
"""

from __future__ import annotations

import os
import subprocess

from .. import paths
from . import pkgspec

__all__ = [
    "InstallError",
    "ENV_KEEP",
    "CACHE_ENV_NAMES",
    "TIMEOUT_SEC",
    "build_argv",
    "build_env",
    "install",
]


class InstallError(RuntimeError):
    """설치를 띄우지 못했을 때. 결과는 예외가 아니라 dict 로 돌려준다."""


#: 10분. 큰 휠(torch 류)은 내려받는 데 오래 걸린다.
TIMEOUT_SEC = 600

#: pip 에 물려주는 환경. **화이트리스트다.**
#:
#: 캐시 변수가 여기 **없는 것이 요점**이다. `ENV_KEEP` 에 없으면 물려받지
#: 않으므로, 오케스트레이터의 환경에 `PIP_CACHE_DIR` 이 섞여 있어도 안 간다.
ENV_KEEP = (
    "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TZ",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "CONDA_EXE", "MAMBA_EXE", "MAMBA_ROOT_PREFIX",
)

#: 혹시라도 새면 안 되는 이름. `ENV_KEEP` 화이트리스트가 1차 방어이고,
#: 이 목록은 **테스트가 보는 명세**다 (공용 캐시를 안 쓴다는 약속).
CACHE_ENV_NAMES = (
    "PIP_CACHE_DIR", "HF_HOME", "HF_HUB_CACHE", "TORCH_HOME",
    "XDG_CACHE_HOME", "WANDB_DIR", "TMPDIR", "TEMP", "TMP",
)

#: 추가 결제 금지 — 환경에서 반드시 지운다
ENV_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def build_argv(parsed: dict, env_name: str, *, allow_source: bool = False) -> list[str]:
    """`conda run -n <환경> python -m pip install …` 전체.

    `shell=False` 로 넘긴다 — 인자에 `;` 가 있어도 셸이 해석하지 않는다.
    (애초에 `pkgspec` 이 그런 글자를 거부한다. 두 겹이다.)
    """
    name = str(env_name or "").strip()
    if not name or not pkgspec.NAME_RE.match(name):
        raise InstallError(
            f"conda 환경 이름이 이상해요: {env_name!r} · "
            "specifications/Config.yaml 의 env.conda 를 봐 주세요"
        )
    items = pkgspec.requirements(parsed)
    if not items:
        raise InstallError("설치할 게 없어요")

    argv = [
        "conda", "run", "-n", name, "--no-capture-output",
        "python", "-m", "pip", "install",
        # 사람에게 묻지 않는다 — 루프가 멈춘다
        "--no-input",
        # 🔑 공용 캐시를 쓰지 않는다. 오염된 휠을 읽으면 그게 곧 코드 실행이다.
        "--no-cache-dir",
        # pip 자신을 올리지 않는다
        "--disable-pip-version-check",
    ]
    if not (allow_source and parsed.get("allowSource")):
        # 소스 배포는 setup.py 를 **실행**한다. 휠만 받는다.
        argv.append("--only-binary=:all:")
    argv += items
    return argv


def build_env(base: dict | None = None) -> dict[str, str]:
    """pip 가 받을 환경. 화이트리스트 + 캐시 변수 제거 + API 키 제거."""
    source = os.environ if base is None else base
    out = {k: source[k] for k in ENV_KEEP if k in source}
    for name in ENV_STRIP:
        out.pop(name, None)
    for name in CACHE_ENV_NAMES:
        # 화이트리스트에 없어서 애초에 안 들어오지만, 명세를 코드로도 적어 둔다.
        out.pop(name, None)
    # pip 가 전역 설정 파일을 읽지 않게 — 거기 index-url 이 있으면 우리가 모르는
    # 곳에서 받는다.
    out["PIP_CONFIG_FILE"] = os.devnull
    return out


def install(
    parsed: dict,
    env_name: str,
    *,
    allow_source: bool = False,
    cwd: str = "",
    timeout_sec: int = TIMEOUT_SEC,
    runner=None,
) -> dict:
    """실제로 설치한다. **던지지 않는다** — 결과를 dict 로 돌려준다.

    실패해도 `blocked` 로 가지 않는다. Claude 에게 결과를 그대로 알려 주고
    다른 방법을 찾게 한다 (의존성 하나가 루프를 끝내면 안 된다).
    """
    try:
        argv = build_argv(parsed, env_name, allow_source=allow_source)
    except InstallError as exc:
        # 던지지 않는다 — 부르는 쪽이 결과를 사람과 AI 에게 알려 줘야 한다.
        return {"ok": False, "argv": [], "exitCode": None, "output": "", "reason": str(exc)}
    env = build_env()
    where = paths.real(cwd) if cwd else None

    call = runner or subprocess.run
    try:
        done = call(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
            cwd=where,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "argv": argv,
            "exitCode": None,
            "output": "",
            "reason": f"{timeout_sec}초 안에 못 끝냈어요",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False, "argv": argv, "exitCode": None, "output": "",
            "reason": f"설치를 띄우지 못했어요: {exc}",
        }

    text = ((done.stdout or "") + (done.stderr or "")).strip()
    return {
        "ok": done.returncode == 0,
        "argv": argv,
        "exitCode": done.returncode,
        # 전문을 보관한다 — 나중에 왜 실패했는지 사람이 봐야 한다.
        "output": text,
        "reason": "" if done.returncode == 0 else text[-1200:],
    }
