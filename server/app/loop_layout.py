"""Loop Engineering 폴더 구조의 단일 출처.

프로젝트 생성기·정책 기본값·훅 판정이 **모두 이 모듈만** 참조한다.
갈라지면 생성기가 만든 파일과 훅이 지키는 파일이 달라져 바로 사고가 된다.

근거: `docs/Loop Engineering을 활용한 실험 설계.pdf` (9쪽)
  - 3쪽 "환경 세팅" — File_directory.md, Config.yaml
  - 4쪽 "프로세스 세팅" — Background.md, Process.md, Evaluation.md,
        Stop_and_recovery.md, Experiment_spec.md
  - 5쪽 "공용 기록" — State.yaml(매 실험마다 덮어쓰기), Experiment_log.csv,
        Decision_log.md, Failures.md
  - 6쪽 "개별 기록" — <expNN>/Config.yaml, Results_example.md,
        result_example.csv, Results.md/Results.csv, Analysis.md
  - **7쪽 "파일 구조 예시"** — 실제 트리. 폴더 배치는 이 쪽이 기준이다.
  - 9쪽 "AGENTS.md 예시" — 기록 갱신 순서(원본 출력 → result.csv →
        analysis.md → Experiment_log.csv → Decision_log.md → Failures.md →
        State.yaml)와 "기존 실험 폴더를 덮어쓰지 않는다" 규칙

7쪽 트리 원문:
    experiment-project/
    ├── README.md
    ├── docs/            Background.md Process.md Evaluation.md
    │                    Stop_and_recovery.md File_directory.md
    ├── specifications/  Experiment_spec.md Config.yaml
    ├── state/           State.yaml
    ├── logs/            Experiment_log.csv Decision_log.md Failures.md
    ├── templates/       output_example/ Results_example.md result_example.csv
    ├── data/            <dataset>
    └── experiments/     EXP-001/{config.yaml, <output>, result.csv, analysis.md}

6쪽과 7쪽이 어긋나는 곳이 있다 — 6쪽은 `<expNN>/Config.yaml`·`Results.md`·
`Analysis.md` 처럼 대문자로 적었지만 7쪽 트리는 `config.yaml`·`result.csv`·
`analysis.md` 다. 실제 파일 이름은 **7쪽 트리**를 따른다. `web/src/api/mock/
file-tree.json`(목업 화면)도 소문자이고, 리눅스는 대소문자를 구분하므로
한쪽으로 못박아야 한다.

`src/` 와 `specifications/environment.yml` 은 PDF 트리에 없다 —
`docs/spec.md` III-6(코드 추적)과 `file-tree.json` 에서 온 lab.remote 쪽
추가분이다. 아래 주석에 출처를 따로 적었다.

표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

__all__ = [
    "PENDING",
    "LOOP_LAYOUT",
    "LayoutPending",
    "path",
    "pending_keys",
    "assert_complete",
    "stop_locked_files",
    "journal_files",
    "self_protected_files",
    "hparam_files",
    "experiments_dir",
]

#: 아직 확인하지 못한 값. `CLAUDE.md` 의 "[대괄호 자리표시]" 규칙을 따른다.
PENDING = "[PDF 확인]"

#: 프로젝트 루트 기준 상대 경로. 값이 PENDING 이면 아직 확인 못 한 것.
LOOP_LAYOUT: dict[str, str] = {
    # 루트 (PDF 7쪽 · 8쪽 "실행방법" 방안 2)
    "claude_md": "CLAUDE.md",
    "readme": "README.md",
    # docs/ — 사람이 읽는 기준 문서 (PDF 4쪽, 7쪽)
    "background": "docs/Background.md",
    "process": "docs/Process.md",
    "evaluation": "docs/Evaluation.md",
    "stop_recovery": "docs/Stop_and_recovery.md",
    "file_directory": "docs/File_directory.md",
    # specifications/ — 실험 목표와 실행 환경 (PDF 3쪽, 4쪽, 7쪽)
    "experiment_spec": "specifications/Experiment_spec.md",
    "config": "specifications/Config.yaml",
    # conda 환경. PDF 에는 없고 docs/spec.md III-1 과 file-tree.json 에서 왔다.
    "environment": "specifications/environment.yml",
    # state/ — 현재 루프 상태. 매 실험마다 갱신해 덮어쓴다 (PDF 5쪽, 7쪽)
    "state": "state/State.yaml",
    # "지금 어느 실험이 도는지" 의 유일한 근거. PDF 에는 없고 ②가 넣었다 —
    # 실측에서 Claude 가 잠금의 이유를 설명하지 못했다(`app/loopstate.py`).
    # **오케스트레이터만 쓴다.** selfProtect 목록에 넣는 건 2단계다
    # (정책 판이 2 -> 3 으로 올라가므로 policy migrate 와 같이 간다).
    "current": "state/Current.yaml",
    # logs/ — 누적 기록 (PDF 5쪽, 7쪽)
    "experiment_log": "logs/Experiment_log.csv",
    "decision_log": "logs/Decision_log.md",
    "failures": "logs/Failures.md",
    # 승인 기록. PDF 에는 없고 docs/spec.md III-4 에서 왔다. 훅이 소유한다.
    "approval_log": "logs/Approval_log.csv",
    "hook_events": "logs/hook_events.jsonl",
    # templates/ — 결과 기록 양식 (PDF 6쪽, 7쪽)
    "results_example": "templates/Results_example.md",
    "result_example": "templates/result_example.csv",
    "output_example_dir": "templates/output_example",
    # 디렉터리 (PDF 7쪽)
    "experiments_dir": "experiments",
    "data_dir": "data",
    "docs_dir": "docs",
    "logs_dir": "logs",
    "state_dir": "state",
    "templates_dir": "templates",
    # 실험 코드. PDF 트리에는 없고 spec.md III-6 과 file-tree.json 에서 왔다.
    "src_dir": "src",
}

#: 실험 폴더 하나의 구성 (PDF 7쪽 트리의 EXP-001/)
EXPERIMENT_FILES = {
    "config": "config.yaml",
    "result": "result.csv",
    "analysis": "analysis.md",
    "output_dir": "output",
}

#: 종료 조건 잠금 대상. `docs/Stop_and_recovery.md` 는 사람이 읽는 설명이라 넣지 않는다.
#: PDF 9쪽 "결과를 확인한 뒤 평가 기준을 변경하지 않는다" 가 근거다.
STOP_LOCKED_KEYS = ("config", "evaluation")

#: 권한 단계와 상관없이 항상 허용하는 기록 파일.
#: docs/spec.md IV + PDF 9쪽 "Update Order" 의 갱신 대상이다.
JOURNAL_KEYS = ("state", "experiment_log", "decision_log", "failures", "readme")


class LayoutPending(RuntimeError):
    """아직 확인 못 한 경로를 실제로 쓰려고 했을 때."""


def path(key: str) -> str:
    """확정된 상대 경로. 자리표시가 남아 있으면 예외를 던진다."""
    try:
        value = LOOP_LAYOUT[key]
    except KeyError:  # pragma: no cover - 호출부 오타
        raise KeyError(f"LOOP_LAYOUT 에 없는 키: {key!r}") from None
    if value == PENDING:
        raise LayoutPending(
            f"{key!r} 의 위치는 docs/Loop*.pdf 를 읽어야 확정돼요. "
            "app/loop_layout.py 의 LOOP_LAYOUT 을 채워 주세요."
        )
    return value


def pending_keys() -> list[str]:
    """아직 확인 못 한 키 목록 (정렬)."""
    return sorted(k for k, v in LOOP_LAYOUT.items() if v == PENDING)


def assert_complete() -> None:
    """자리표시가 하나라도 남아 있으면 예외. 다음 단계로 넘어가는 문턱."""
    left = pending_keys()
    if left:
        raise LayoutPending(
            "docs/Loop*.pdf 를 읽어 LOOP_LAYOUT 을 채워 주세요. 남은 키: "
            + ", ".join(left)
        )


def _values(keys: tuple[str, ...]) -> list[str]:
    """자리표시는 그대로 내보낸다.

    정책 파일에 `[PDF 확인]` 이 그대로 보이는 쪽이 낫다. 실제 상대 경로와는
    절대 매치되지 않아서 조용히 허용되는 일이 없고, 눈으로 바로 보인다.
    """
    return [LOOP_LAYOUT[k] for k in keys]


def stop_locked_files() -> list[str]:
    """잠긴 항목 "종료 조건·Evaluation.md 수정" 의 대상 파일."""
    return _values(STOP_LOCKED_KEYS)


def journal_files() -> list[str]:
    """기록 의무 파일. 실험 폴더별 결과·분석까지 포함 (PDF 9쪽 Update Order)."""
    exp = experiments_dir()
    return _values(JOURNAL_KEYS) + [
        f"{exp}/*/{EXPERIMENT_FILES['result']}",
        f"{exp}/*/{EXPERIMENT_FILES['analysis']}",
    ]


def self_protected_files() -> list[str]:
    """훅 자신을 지키는 목록. 잠긴 3개와 같은 무게로 항상 차단한다."""
    return [
        ".claude/**",
        ".mcp.json",
        LOOP_LAYOUT["approval_log"],
        LOOP_LAYOUT["hook_events"],
    ]


def hparam_files() -> list[str]:
    """행동 유형 "하이퍼파라미터 변경" 의 대상 (PDF 6쪽 <expNN>/config.yaml)."""
    return [f"{experiments_dir()}/*/{EXPERIMENT_FILES['config']}"]


def experiments_dir() -> str:
    return LOOP_LAYOUT["experiments_dir"]
