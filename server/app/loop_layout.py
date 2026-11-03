"""Loop Engineering 폴더 구조의 단일 출처.

프로젝트 생성기·정책 기본값·훅 판정이 **모두 이 모듈만** 참조한다.
갈라지면 생성기가 만든 파일과 훅이 지키는 파일이 달라져 바로 사고가 된다.

기록 파일 4개(State.yaml·Experiment_log.csv·Decision_log.md·Failures.md)의
위치는 `docs/Loop*.pdf` 를 읽어야 확정된다. 그때까지 `PENDING` 자리표시로 둔다.
`assert_complete()` 와 tests/test_loop_layout.py 가 자리표시를 남긴 채
다음 단계로 넘어가지 못하게 막는다.

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
    # 고정 지침과 사람이 읽는 문서
    "claude_md": "CLAUDE.md",
    "readme": "README.md",
    "evaluation": "docs/Evaluation.md",
    "stop_recovery": "docs/Stop_and_recovery.md",
    "file_directory": "docs/File_directory.md",
    "experiment_design": "docs/Experiment_design.md",
    # 기계가 읽는 설정
    "config": "specifications/Config.yaml",
    "environment": "specifications/environment.yml",
    # 이어받기용 기록 — 위치 미확정
    "state": PENDING,  # State.yaml
    "experiment_log": PENDING,  # Experiment_log.csv
    "decision_log": PENDING,  # Decision_log.md
    "failures": PENDING,  # Failures.md
    # 추가 전용 로그
    "approval_log": "logs/Approval_log.csv",
    "hook_events": "logs/hook_events.jsonl",
    # 디렉터리
    "experiments_dir": "experiments",
    "src_dir": "src",
    "data_dir": "data",
    "logs_dir": "logs",
}

#: 종료 조건 잠금 대상. `docs/Stop_and_recovery.md` 는 사람이 읽는 설명이라 넣지 않는다.
STOP_LOCKED_KEYS = ("config", "evaluation")

#: 권한 단계와 상관없이 항상 허용하는 기록 파일 (spec IV).
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
    """기록 의무 파일. 실험 폴더별 분석 노트까지 포함."""
    return _values(JOURNAL_KEYS) + [f"{experiments_dir()}/*/analysis.md"]


def self_protected_files() -> list[str]:
    """훅 자신을 지키는 목록. 잠긴 3개와 같은 무게로 항상 차단한다."""
    return [
        ".claude/**",
        ".mcp.json",
        LOOP_LAYOUT["approval_log"],
        LOOP_LAYOUT["hook_events"],
    ]


def hparam_files() -> list[str]:
    """행동 유형 "하이퍼파라미터 변경" 의 대상."""
    return [f"{experiments_dir()}/*/config.yaml"]


def experiments_dir() -> str:
    return LOOP_LAYOUT["experiments_dir"]
