"""권한 모델의 기본값.

`web/src/api/mock/permissions.json` 의 `modes`·`actions` 와 **글자 단위로 같아야**
한다. 프런트가 먼저 확정한 계약이고, ③단계 FastAPI 가 가공 없이 내려준다.
tests/test_policy.py 가 그 JSON 을 직접 읽어 대조한다.

표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

from datetime import datetime

from . import loop_layout as L

__all__ = [
    "POLICY_VERSION",
    "MODES",
    "ACTIONS",
    "LABELS",
    "MODE_IDS",
    "ACTION_KEYS",
    "LOCKED_KEYS",
    "PERMISSIONS",
    "DEFAULT_MODE",
    "default_policy",
]

#: 정책 파일 스키마 판. 올라가면 policy.load() 가 거절한다.
POLICY_VERSION = 1

PERMISSIONS = ("allow", "ask", "block")

#: 권한 프리셋 3종 (web permissions.json 과 동일)
MODES: list[dict[str, str]] = [
    {"id": "manual", "name": "수동제어", "desc": "모든 의사결정을 내가 직접 승인해요."},
    {"id": "error", "name": "오류 대응 자동화", "desc": "실험 중 생긴 에러 수정만 AI가 처리해요."},
    {
        "id": "full",
        "name": "연구 전체 자동화",
        "desc": "결과 판단과 다음 실험 결정까지 AI가 하고, 종료 조건에서 멈춰요.",
    },
]

#: 행동 유형 9개. 뒤 3개가 잠긴 항목 (web permissions.json 과 동일)
ACTIONS: list[dict] = [
    {
        "key": "code",
        "name": "코드 수정",
        "desc": "실험 코드·설정 파일 · 수정 전 자동 커밋",
        "defaults": {"manual": "ask", "error": "allow", "full": "allow"},
        "locked": False,
    },
    {
        "key": "hparam",
        "name": "하이퍼파라미터 변경",
        "desc": "config.yaml의 허용된 조작변인만",
        "defaults": {"manual": "ask", "error": "ask", "full": "allow"},
        "locked": False,
    },
    {
        "key": "pkg",
        "name": "패키지 설치",
        "desc": "conda, pip",
        "defaults": {"manual": "ask", "error": "ask", "full": "ask"},
        "locked": False,
    },
    {
        "key": "del",
        "name": "파일 삭제",
        "desc": "프로젝트 폴더 안",
        "defaults": {"manual": "ask", "error": "ask", "full": "ask"},
        "locked": False,
    },
    {
        "key": "newexp",
        "name": "새 실험 시작",
        "desc": "작업 큐에 추가하고 실행",
        "defaults": {"manual": "ask", "error": "ask", "full": "allow"},
        "locked": False,
    },
    {
        "key": "net",
        "name": "외부 네트워크 접근",
        "desc": "데이터셋·모델 다운로드 등",
        "defaults": {"manual": "ask", "error": "ask", "full": "ask"},
        "locked": False,
    },
    {
        "key": "outside",
        "name": "프로젝트 폴더 밖 쓰기·삭제",
        "desc": "잠김 · 항상 차단",
        "defaults": {"manual": "block", "error": "block", "full": "block"},
        "locked": True,
    },
    {
        "key": "stop",
        "name": "종료 조건·Evaluation.md 수정",
        "desc": "잠김 · 실험 진행 중 차단",
        "defaults": {"manual": "block", "error": "block", "full": "block"},
        "locked": True,
    },
    {
        "key": "prev",
        "name": "이전 실험 폴더 덮어쓰기",
        "desc": "잠김 · 항상 차단",
        "defaults": {"manual": "block", "error": "block", "full": "block"},
        "locked": True,
    },
]

#: allow / ask / block 의 화면 글자 (web permissions.json 의 labels)
LABELS = {"allow": "자동 허용", "ask": "승인 필요", "block": "차단"}

MODE_IDS = tuple(m["id"] for m in MODES)
ACTION_KEYS = tuple(a["key"] for a in ACTIONS)
LOCKED_KEYS = tuple(a["key"] for a in ACTIONS if a["locked"])

#: 새 프로젝트의 기본 프리셋. 가장 좁은 쪽에서 시작한다.
DEFAULT_MODE = "manual"

#: 잠금의 성격. `stop` 만 실행 중일 때 차단이고 멈춰 있으면 승인을 거친다 (spec III-4).
LOCKS = {"outside": "always", "prev": "always", "stop": "while-running"}

#: 훅이 내부적으로 쓰는 분류. 행동 유형 9개에는 없다.
INTERNAL_ACTIONS = {
    # 기록은 권한 단계와 상관없이 항상 허용 (spec IV)
    "journal": "allow",
    # 훅 설정·정책·승인 로그 자신을 지키는 잠금
    "selfProtect": "block",
    # 분류되지 않은 것은 Claude Code 기본 권한 흐름에 맡긴다
    "unknown": "defer",
}

BASH_DEFAULTS = {
    "escalateOnSubstitution": True,
    "denyCommands": ["claude", "shred", "mkfs"],
    # git 원격은 ②의 오케스트레이터가 전담한다. net 으로 보면 ask 소음만 늘어난다.
    "gitRemoteAsNet": False,
}

HEADLESS_DEFAULTS = {
    # ①의 기본값. 승인 경로 실측 뒤에 "deny-with-reason" 으로 바꿀 수 있다.
    "onAsk": "ask",
    "notifyDiscord": True,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_policy(name: str = "", root: str = "") -> dict:
    """새 프로젝트의 정책 파일 내용.

    `name`·`root` 를 비우면 템플릿용(값이 빈 문자열)으로 나온다.
    """
    return {
        "version": POLICY_VERSION,
        "project": {"name": name, "root": root},
        "defaultMode": DEFAULT_MODE,
        # 웹 계약: 저장한 적 없으면 null
        "saved": None,
        "modes": [dict(m) for m in MODES],
        "actions": [
            {**a, "defaults": dict(a["defaults"])} for a in ACTIONS
        ],
        "locks": dict(LOCKS),
        "internalActions": dict(INTERNAL_ACTIONS),
        "paths": {
            "stopLockedFiles": L.stop_locked_files(),
            "selfProtectedFiles": L.self_protected_files(),
            "journalFiles": L.journal_files(),
            "hparamFiles": L.hparam_files(),
            "experimentsDir": L.experiments_dir(),
            "experimentIdRe": "^EXP-[0-9]{3}$",
            "prevAppendable": ["analysis.md"],
            # 결과가 나온 실험 폴더만 "이전 실험" 으로 본다. 이 표식이 없는
            # 폴더는 아직 안 돌린 실험이라 자유롭게 준비할 수 있어야 한다.
            "prevMarkers": ["result.csv", "analysis.md"],
            # spec 은 폴더 밖 쓰기·삭제만 막는다. 읽기는 막지 않는다.
            "allowOutsideRead": True,
            # 데이터셋 심볼릭 링크 예외. [데이터셋 링크 경로 — 미확인]
            "extraWritableRoots": [],
        },
        "bash": dict(BASH_DEFAULTS),
        "headless": dict(HEADLESS_DEFAULTS),
        "logPath": L.LOOP_LAYOUT["approval_log"],
        "eventLogPath": L.LOOP_LAYOUT["hook_events"],
        "updatedAt": _now(),
        "updatedBy": "generator",
    }
