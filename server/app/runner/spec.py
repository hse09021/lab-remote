"""`run.json` 검증 — **보안 경계다.**

AI 가 `run.json` 에 임의 명령을 적고 오케스트레이터가 그걸 실행하면 훅을
**완전히 우회**한다. 훅은 Claude 의 도구 호출만 보기 때문이다. 그래서

* `command` 같은 **자유 문자열을 받지 않는다.**
* `entrypoint` 는 `specifications/Config.yaml` 의 `run.entrypoints` 목록에
  **있어야만** 한다. 그 파일은 `stop` 잠금 대상이라 실험이 도는 중에는 AI 가
  못 고친다.
* `args` 는 `shell=False` 로 그대로 넘긴다. `&&`·`;`·백틱이 있어도 그냥
  인자 문자열이다.
* `env` 는 `run.envAllow` 에 **이름이 적힌 것만**. `LD_PRELOAD`·`PYTHONPATH`·
  `PATH` 는 목록에 있어도 거부한다 — 그 셋은 "환경 변수" 가 아니라 "다른
  코드를 끼워 넣는 길" 이다.
* 모르는 키가 있으면 거부한다(fail-closed). 조용히 무시하면 다음 판에서
  의미가 생겼을 때 그게 그대로 구멍이 된다.

검증은 **이 파일 한 곳에서만** 한다. 두 곳에서 하면 한 곳이 느슨해진다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .. import loop_layout as L
from .. import paths

__all__ = [
    "SpecError",
    "RunSpec",
    "ENV_NEVER",
    "DEFAULT_TIMEOUT_SEC",
    "DEFAULT_GRACE_SEC",
    "read_config",
    "load",
    "validate",
    "entrypoints_of",
    "check_experiment_id",
]

#: **실행기가 정하는** 환경 변수. `run.json` 으로는 못 바꾼다.
#: 공용 캐시 폴더 아래로 고정한다 (`runner/cache.py`) — AI 가
#: `HF_HOME=~/.claude` 같은 값을 넣는 길을 없애고, `TMPDIR` 이 샌드박스의
#: tmpfs(메모리)로 가지 않게 한다.
ENV_MANAGED = frozenset(
    {"HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "WANDB_DIR", "TMPDIR"}
)

#: 환경 변수처럼 보이지만 **다른 코드를 끼워 넣는 길**. 목록에 있어도 거부한다.
ENV_NEVER = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PATH",
        "BASH_ENV",
        "ENV",
        "IFS",
        "ANTHROPIC_API_KEY",  # 구독으로만 돌린다 (추가 결제 금지)
    }
)

#: `run.json` 에 쓸 수 있는 키. 이 밖은 거부한다.
ALLOWED_KEYS = frozenset(
    {"entrypoint", "args", "env", "timeout_sec", "resume_from", "note", "experiment_id"}
)

#: `Config.yaml` 에 값이 없을 때. 계획의 확정값이다.
DEFAULT_TIMEOUT_SEC = 6 * 60 * 60
DEFAULT_GRACE_SEC = 120

#: 한 번에 넘길 수 있는 인자 개수·길이 상한. 터무니없는 입력으로 터지지 않게.
MAX_ARGS = 200
MAX_ARG_LEN = 4096

#: 실험 ID 는 **폴더 이름이 된다.** `../../etc` 같은 값이 들어오면 경로가
#: 프로젝트 밖으로 나간다. 정책의 `experimentIdRe` 보다 느슨하게 두되
#: (EXP-001 이 아닌 이름을 쓸 수도 있다) 경로 조각은 못 들어오게 한다.
EXP_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class SpecError(ValueError):
    """`run.json` 을 믿을 수 없을 때. 실행하지 않고 `blocked` 로 둔다."""


@dataclass
class RunSpec:
    """검증이 끝난 실행 명세. 여기 있는 값만 실제로 돌린다."""

    project: str
    root: str
    experiment_id: str
    #: 프로젝트 루트 기준 상대 경로 (`Config.yaml` 의 목록에 있던 그대로)
    entrypoint: str
    #: 절대 경로로 해소한 것
    entrypoint_abs: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    grace_sec: int = DEFAULT_GRACE_SEC
    conda_env: str = ""
    #: 샌드박스 안에서 **읽기 전용**으로 다시 열 경로 (`Config.yaml` 의
    #: `run.dataPaths`). 루트 전체가 이미 읽기 전용이라, 가려진 경로 안에 있는
    #: 데이터셋을 쓸 때만 필요하다.
    data_paths: list[str] = field(default_factory=list)
    resume_from: str = ""
    note: str = ""
    #: 검증은 통과했지만 사람이 알아야 할 것 (샌드박스에서 조용히 버려질 쓰기 등)
    warnings: list[str] = field(default_factory=list)

    @property
    def exp_dir(self) -> str:
        return os.path.join(self.root, L.experiments_dir(), self.experiment_id)

    @property
    def output_dir(self) -> str:
        return os.path.join(self.exp_dir, "output")

    @property
    def log_path(self) -> str:
        return os.path.join(self.output_dir, "train.log")

    @property
    def exit_code_path(self) -> str:
        return os.path.join(self.output_dir, "exit_code")

    @property
    def run_json_path(self) -> str:
        return os.path.join(self.exp_dir, "run.json")


def read_config(root: str) -> dict:
    """`specifications/Config.yaml` 을 읽는다. 없거나 깨졌으면 `SpecError`.

    훅 경로가 아니라서 pyyaml 을 쓴다.
    """
    import yaml

    path = os.path.join(root, L.LOOP_LAYOUT["config"])
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        raise SpecError(f"{L.LOOP_LAYOUT['config']} 가 없어요: {path}") from None
    except (OSError, yaml.YAMLError) as exc:
        raise SpecError(f"{L.LOOP_LAYOUT['config']} 를 읽을 수 없어요: {exc}") from None
    if not isinstance(data, dict):
        raise SpecError(f"{L.LOOP_LAYOUT['config']} 가 YAML 사전이 아니에요")
    return data


def _run_section(config: dict) -> dict:
    section = config.get("run")
    return section if isinstance(section, dict) else {}


def entrypoints_of(config: dict) -> list[str]:
    """돌릴 수 있는 스크립트 목록. 자리표시(`[...]`)는 걸러낸다."""
    listed = _run_section(config).get("entrypoints")
    if not isinstance(listed, list):
        return []
    out: list[str] = []
    for item in listed:
        value = str(item).strip()
        # `[학습 스크립트 — 미정]` 같은 자리표시는 실행 대상이 아니다.
        if not value or value.startswith("["):
            continue
        out.append(value)
    return out


def _positive_int(value, default: int, label: str) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SpecError(f"{label} 가 숫자가 아니에요: {value!r}") from None
    if number <= 0:
        raise SpecError(f"{label} 는 0보다 커야 해요: {number}")
    return number


def check_experiment_id(experiment_id: str) -> str:
    """폴더 이름으로 쓸 수 있는 값인가. 경로 조각은 거절한다."""
    value = str(experiment_id or "").strip()
    if not EXP_ID_RE.match(value) or value in (".", ".."):
        raise SpecError(
            f"실험 ID 로 쓸 수 없는 값이에요: {experiment_id!r} · "
            "영숫자로 시작하고 . _ - 만 섞을 수 있어요 (경로 조각은 안 돼요)"
        )
    return value


def load(project: str, root: str, experiment_id: str) -> RunSpec:
    """`experiments/<실험>/run.json` 을 읽고 검증한다."""
    experiment_id = check_experiment_id(experiment_id)
    path = os.path.join(root, L.experiments_dir(), experiment_id, "run.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise SpecError(f"run.json 이 없어요: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"run.json 을 읽을 수 없어요: {exc}") from None
    return validate(raw, project=project, root=root, experiment_id=experiment_id)


def validate(raw, *, project: str, root: str, experiment_id: str) -> RunSpec:
    """명세 하나를 검증해 `RunSpec` 으로. 못 믿으면 `SpecError`."""
    if not isinstance(raw, dict):
        raise SpecError("run.json 이 JSON 객체가 아니에요")
    experiment_id = check_experiment_id(experiment_id)

    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        raise SpecError(
            "run.json 에 모르는 키가 있어요: "
            + ", ".join(unknown)
            + " · 쓸 수 있는 키: "
            + ", ".join(sorted(ALLOWED_KEYS))
        )

    said = str(raw.get("experiment_id") or "").strip()
    if said and said != experiment_id:
        raise SpecError(
            f"run.json 의 experiment_id 가 폴더와 달라요: {said!r} vs {experiment_id!r}"
        )

    config = read_config(root)
    run_cfg = _run_section(config)
    allowed = entrypoints_of(config)
    if not allowed:
        raise SpecError(
            f"{L.LOOP_LAYOUT['config']} 의 run.entrypoints 가 비어 있어요. "
            "돌릴 수 있는 스크립트를 먼저 적어 주세요 (그 파일은 실험이 멈춰 "
            "있을 때만 바꿀 수 있어요)."
        )

    entrypoint = str(raw.get("entrypoint") or "").strip()
    if not entrypoint:
        raise SpecError("run.json 에 entrypoint 가 없어요")
    if entrypoint not in allowed:
        raise SpecError(
            f"허락된 entrypoint 가 아니에요: {entrypoint!r} · "
            f"{L.LOOP_LAYOUT['config']} 의 run.entrypoints: {', '.join(allowed)}"
        )

    entrypoint_abs = paths.safe_resolve(entrypoint, root)
    if not paths.is_inside(root, entrypoint_abs):
        raise SpecError(f"entrypoint 가 프로젝트 폴더 밖이에요: {entrypoint_abs}")
    if not os.path.isfile(entrypoint_abs):
        raise SpecError(f"entrypoint 파일이 없어요: {entrypoint_abs}")

    args = _clean_args(raw.get("args"))
    env = _clean_env(raw.get("env"), run_cfg.get("envAllow"))

    timeout_sec = _positive_int(
        raw.get("timeout_sec"),
        _positive_int(run_cfg.get("timeoutSec"), DEFAULT_TIMEOUT_SEC, "Config.yaml 의 run.timeoutSec"),
        "run.json 의 timeout_sec",
    )
    grace_sec = _positive_int(
        run_cfg.get("graceSec"), DEFAULT_GRACE_SEC, "Config.yaml 의 run.graceSec"
    )

    resume_from = str(raw.get("resume_from") or "").strip()
    warnings: list[str] = []
    if resume_from:
        resume_abs = paths.safe_resolve(resume_from, root)
        if not paths.is_inside(root, resume_abs):
            raise SpecError(f"이어 돌릴 체크포인트가 프로젝트 폴더 밖이에요: {resume_abs}")
        if not os.path.exists(resume_abs):
            raise SpecError(f"이어 돌릴 체크포인트가 없어요: {resume_abs}")
        resume_arg = str(run_cfg.get("resumeArg") or "--resume-from")
        args = [*args, resume_arg, resume_abs]

    conda_env = str(((config.get("env") or {}) if isinstance(config.get("env"), dict) else {}).get("conda") or "").strip()
    if conda_env.startswith("["):  # 자리표시
        conda_env = ""

    data_paths, data_warnings = _clean_data_paths(run_cfg.get("dataPaths"), root)

    # 샌드박스 안에서 보호 경로 쓰기는 **성공한 것처럼 보이지만** 실제 파일에는
    # 안 남는다(`--tmpfs`). 학습이 "저장했다" 고 믿고 조용히 오동작하지 않게
    # 미리 알린다.
    for name, value in env.items():
        if value.startswith("/") and not paths.is_inside(root, paths.real(value)):
            warnings.append(
                f"{name} 이 프로젝트 폴더 밖을 가리켜요: {value} · "
                "샌드박스 안에서는 그 경로에 쓴 내용이 남지 않아요."
            )

    warnings.extend(data_warnings)
    return RunSpec(
        project=project,
        root=root,
        experiment_id=experiment_id,
        entrypoint=entrypoint,
        entrypoint_abs=entrypoint_abs,
        args=args,
        env=env,
        timeout_sec=timeout_sec,
        grace_sec=grace_sec,
        conda_env=conda_env,
        data_paths=data_paths,
        resume_from=resume_from,
        note=str(raw.get("note") or "")[:500],
        warnings=warnings,
    )


def _clean_data_paths(value, root: str) -> tuple[list[str], list[str]]:
    """`Config.yaml` 의 `run.dataPaths` — 샌드박스에서 **읽기 전용**으로 열 경로.

    보호 경로와 겹치면 거절한다. 그걸 허용하면 "데이터셋" 이라는 이름으로
    정책·자격 증명을 읽을 수 있게 된다.
    """
    if value is None:
        return [], []
    if not isinstance(value, list):
        raise SpecError(f"run.dataPaths 가 배열이 아니에요: {type(value).__name__}")

    from .sandbox import secret_paths

    # **비밀만** 막는다. 다른 실험 프로젝트는 사람이 명시하면 읽기로 열어 준다
    # — 데이터셋을 공유하는 게 정상이고, 열어 주는 건 읽기뿐이다.
    guards = secret_paths(root)
    out: list[str] = []
    warnings: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text.startswith("["):  # 자리표시
            continue
        target = paths.real(text)
        for guard in guards:
            if paths.is_inside(guard, target) or paths.is_inside(target, guard):
                raise SpecError(
                    f"데이터셋 경로가 보호 경로와 겹쳐요: {target} · {guard} · "
                    "정책·자격 증명이 있는 곳이라 열 수 없어요."
                )
        if not os.path.exists(target):
            warnings.append(f"데이터셋 경로가 없어요(건너뛰어요): {target}")
            continue
        out.append(target)
    return out, warnings


def _clean_args(value) -> list[str]:
    """인자는 **문자열 배열**만. 자유 문자열을 받지 않는다."""
    if value is None:
        return []
    if isinstance(value, str):
        raise SpecError(
            "args 는 배열이어야 해요 (문자열 하나로 주면 셸이 해석할 수 있어요). "
            '예: ["--lr", "1e-4"]'
        )
    if not isinstance(value, list):
        raise SpecError(f"args 가 배열이 아니에요: {type(value).__name__}")
    if len(value) > MAX_ARGS:
        raise SpecError(f"args 가 너무 많아요: {len(value)}개 (최대 {MAX_ARGS})")
    out: list[str] = []
    for item in value:
        if isinstance(item, bool) or item is None:
            raise SpecError(f"args 에 쓸 수 없는 값이에요: {item!r}")
        if isinstance(item, (int, float)):
            item = str(item)
        if not isinstance(item, str):
            raise SpecError(f"args 는 문자열이어야 해요: {item!r}")
        if len(item) > MAX_ARG_LEN:
            raise SpecError(f"인자가 너무 길어요 ({len(item)}자)")
        if "\0" in item:
            raise SpecError("인자에 널 문자가 있어요")
        out.append(item)
    return out


def _clean_env(value, allow) -> dict[str, str]:
    """`envAllow` 에 **이름이 적힌 것만**. 끼워 넣는 변수는 목록에 있어도 거부."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SpecError(f"env 가 사전이 아니에요: {type(value).__name__}")
    allowed = {str(x).strip() for x in (allow or []) if str(x).strip()}
    out: dict[str, str] = {}
    for name, item in value.items():
        key = str(name)
        if key in ENV_NEVER:
            raise SpecError(
                f"{key} 는 환경 변수로 넘길 수 없어요 — 다른 코드를 끼워 넣는 길이에요."
            )
        if key in ENV_MANAGED:
            raise SpecError(
                f"{key} 는 실행기가 공용 캐시 폴더로 정해요 — run.json 으로는 "
                "바꿀 수 없어요. 캐시 위치를 옮기려면 정책의 paths.cacheDir 을 "
                "고쳐 주세요."
            )
        if key not in allowed:
            raise SpecError(
                f"허락된 환경 변수가 아니에요: {key} · "
                f"{L.LOOP_LAYOUT['config']} 의 run.envAllow 에 이름을 먼저 적어 주세요"
                + (f" (지금 허락된 것: {', '.join(sorted(allowed))})" if allowed else "")
            )
        if isinstance(item, bool) or item is None or isinstance(item, (list, dict)):
            raise SpecError(f"{key} 의 값이 문자열이 아니에요: {item!r}")
        text = str(item)
        if "\0" in text:
            raise SpecError(f"{key} 의 값에 널 문자가 있어요")
        out[key] = text
    return out
