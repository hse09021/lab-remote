"""공용 캐시 폴더 — 샌드박스 안에서 **쓸 수 있는 유일한 바깥**.

왜 필요한가. 샌드박스는 프로젝트 폴더 하나만 쓸 수 있게 두는데, 진짜 학습은
프로젝트 밖에 쓰려 든다.

| 쓰려는 곳 | 기본 위치 | 막히면 |
|---|---|---|
| HuggingFace 모델·데이터셋 | `~/.cache/huggingface` | 매 실험마다 모델을 다시 내려받는다 |
| torch hub | `~/.cache/torch` | 같은 문제 |
| pip | `~/.cache/pip` | 설치가 느려지고 네트워크를 또 탄다 |
| W&B | `./wandb` 또는 `~/.cache/wandb` | 기록이 조용히 사라진다 |
| 임시 파일 | `/tmp` | 샌드박스의 `/tmp` 는 **tmpfs = 메모리**다. 큰 임시 파일이면 메모리가 터진다 |

마지막 줄이 특히 고약하다. `--tmpfs /tmp` 라 쓰기가 **성공한 것처럼 보이면서**
RAM 을 먹는다. 그래서 `TMPDIR` 을 캐시 폴더 아래 **진짜 디스크**로 돌린다.

그래서 캐시 폴더 하나를 열고, 그 아래로 전부 모은다. 프로젝트들이 **공용**으로
쓴다 — 실험마다 모델을 다시 내려받지 않게.

**값은 실행기가 정한다.** `run.json` 으로는 못 바꾼다(`spec.ENV_MANAGED`) —
AI 가 `HF_HOME=/home/사용자/.claude` 같은 값을 넣는 길을 없앤다.
"""

from __future__ import annotations

import os

from .. import paths, registry

__all__ = [
    "DEFAULT_DIR",
    "SUBDIRS",
    "ENV_MAP",
    "CacheError",
    "cache_dir",
    "check",
    "ensure",
    "env_for",
    "describe",
]

#: 기본 위치. `~/.cache` 아래가 아니라 따로 두는 이유 — `~/.cache` 를 통째로
#: 바인드하면 거기 있는 다른 프로그램의 자료까지 학습 코드에 열린다.
DEFAULT_DIR = "~/lab-cache"

#: 캐시 폴더 아래 구조. 프로그램마다 따로 둬서 뭐가 얼마나 쓰는지 보이게.
SUBDIRS = {
    "huggingface": "huggingface",
    "torch": "torch",
    "xdg": "xdg",
    "pip": "pip",
    "wandb": "wandb",
    "tmp": "tmp",
}

#: 환경 변수 -> 하위 폴더. **실행기가 넣는 고정값이다.**
#: `HF_HOME` 하나로 `HF_HUB_CACHE`·`HF_DATASETS_CACHE`·`TRANSFORMERS_CACHE` 가
#: 같이 따라온다 (HuggingFace 가 HF_HOME 아래로 계산한다).
ENV_MAP = {
    "HF_HOME": "huggingface",
    "TORCH_HOME": "torch",
    "XDG_CACHE_HOME": "xdg",
    "PIP_CACHE_DIR": "pip",
    "WANDB_DIR": "wandb",
    # 샌드박스의 `/tmp` 는 tmpfs(메모리)다. 큰 임시 파일을 디스크로 보낸다.
    "TMPDIR": "tmp",
}


class CacheError(RuntimeError):
    """캐시 폴더를 쓸 수 없을 때. **학습을 띄우지 않는다.**"""


def cache_dir(policy=None) -> str:
    """쓸 캐시 폴더. 환경 변수 -> 정책 -> 기본값 순서다."""
    override = os.environ.get("LAB_CACHE_DIR")
    if override and override.strip():
        return paths.real(override.strip())
    if policy is not None:
        configured = (getattr(policy, "paths", {}) or {}).get("cacheDir")
        if isinstance(configured, str) and configured.strip():
            value = configured.strip()
            # `[자리표시]` 는 설정 안 한 것으로 본다
            if not value.startswith("["):
                return paths.real(value)
    return paths.real(DEFAULT_DIR)


def _protected(project_root: str) -> list[str]:
    """겹치면 안 되는 곳. 샌드박스가 가리는 목록과 **같은 출처**를 쓴다."""
    from . import sandbox

    return sandbox.hidden_paths(project_root)


def check(cache: str, project_root: str = "") -> list[str]:
    """겹치는지 본다. 겹치면 `CacheError`. 통과하면 경고 목록을 돌려준다.

    **양쪽으로 본다.** 캐시가 보호 경로 안에 있는 것도, 캐시가 보호 경로를
    품는 것(`cacheDir: ~`)도 둘 다 막는다 — 후자는 학습 코드에 `~/.claude` 를
    쓰기로 열어 주는 셈이다.
    """
    target = paths.real(cache)
    if not target or target == os.sep:
        raise CacheError(f"캐시 폴더로 쓸 수 없는 경로예요: {cache!r}")
    if not os.path.isabs(target):  # pragma: no cover - real() 이 절대경로를 준다
        raise CacheError(f"캐시 폴더는 절대 경로여야 해요: {target}")

    home = paths.real("~")
    if target == home:
        raise CacheError(
            f"홈 폴더를 캐시로 쓸 수 없어요: {target} · "
            "홈 전체가 학습 코드에 쓰기로 열려요."
        )
    for guard in _protected(project_root):
        if paths.is_inside(guard, target):
            raise CacheError(
                f"캐시 폴더가 보호 경로 안이에요: {target} ⊂ {guard} · "
                "정책·자격 증명·허가 키가 있는 곳이라 학습이 쓸 수 있으면 안 돼요."
            )
        if paths.is_inside(target, guard):
            raise CacheError(
                f"캐시 폴더가 보호 경로를 품고 있어요: {target} ⊃ {guard} · "
                "그러면 학습 코드에 그 경로를 쓰기로 열어 주는 셈이에요."
            )

    warnings: list[str] = []
    if project_root and paths.is_inside(paths.real(project_root), target):
        warnings.append(
            f"캐시 폴더가 프로젝트 안이에요: {target} · 실험마다 다시 내려받게 되고 "
            "저장소가 커져요. 프로젝트 밖(예: {}) 을 권해요.".format(DEFAULT_DIR)
        )
    for other_root in registry.load():
        other = paths.real(other_root)
        if other and other != paths.real(project_root) and paths.is_inside(other, target):
            raise CacheError(
                f"캐시 폴더가 다른 실험 프로젝트 안이에요: {target} ⊂ {other}"
            )
    return warnings


def ensure(cache: str, project_root: str = "") -> dict:
    """검사하고 하위 폴더까지 만든다. 만든 경로와 경고를 돌려준다."""
    warnings = check(cache, project_root)
    target = paths.real(cache)
    try:
        os.makedirs(target, exist_ok=True)
        for sub in SUBDIRS.values():
            os.makedirs(os.path.join(target, sub), exist_ok=True)
    except OSError as exc:
        raise CacheError(f"캐시 폴더를 만들 수 없어요: {target} · {exc}") from None
    return {"dir": target, "warnings": warnings}


def env_for(cache: str) -> dict[str, str]:
    """학습에 넣어 줄 환경 변수. **실행기가 정하는 고정값이다.**"""
    target = paths.real(cache)
    return {name: os.path.join(target, sub) for name, sub in ENV_MAP.items()}


def describe(project_root: str = "", policy=None) -> dict:
    """`doctor` 가 보여 줄 요약. 던지지 않는다."""
    target = cache_dir(policy)
    out = {"dir": target, "ok": False, "reason": "", "warnings": [], "exists": False}
    try:
        out["warnings"] = check(target, project_root)
    except CacheError as exc:
        out["reason"] = str(exc)
        return out
    out["exists"] = os.path.isdir(target)
    out["ok"] = True
    if out["exists"]:
        from .artifacts import disk_usage

        usage = disk_usage(target)
        if usage.get("ok"):
            out["freeGb"] = usage["freeGb"]
    return out
