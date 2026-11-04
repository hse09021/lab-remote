"""권한 모델의 기본값.

`web/src/api/mock/permissions.json` 의 `modes`·`actions` 와 **글자 단위로 같아야**
한다. 프런트가 먼저 확정한 계약이고, ③단계 FastAPI 가 가공 없이 내려준다.
tests/test_policy.py 가 그 JSON 을 직접 읽어 대조한다.

표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

import os
from datetime import datetime

from . import loop_layout as L

__all__ = [
    "POLICY_VERSION",
    "hard_protected_roots",
    "MODES",
    "ACTIONS",
    "LABELS",
    "MODE_IDS",
    "ACTION_KEYS",
    "LOCKED_KEYS",
    "PERMISSIONS",
    "DEFAULT_MODE",
    "DEFAULT_PERMISSION_MODE",
    "HARD_PROTECTED",
    "SECRET_FILES",
    "SECRET_EXEMPT",
    "DENY_COMMANDS",
    "RUNNER_DEFAULTS",
    "default_policy",
]

#: 정책 파일 스키마 판. 올라가면 policy.load() 가 거절한다.
#:   1 -> 2  보호 목록·비밀 파일·산출물 보존이 생기고 headless 기본값이
#:           deny-with-reason 으로 바뀌었다 (2026-11-04 승인 경로 실측).
#:   2 -> 3  ②가 들어왔다. state/Current.yaml 이 selfProtect 에 들어가고,
#:           denyCommands 에 **자기 승인 차단**(labremote·sqlite3·systemctl·
#:           kill 류)과 격리를 깨는 명령이 들어갔다. bash.allowExtra 가 생겼다.
#:           `labremote policy migrate <이름>` 으로 올린다.
POLICY_VERSION = 3

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
#  9개는 web/src/api/mock/permissions.json 과 글자 단위로 같아야 하는 계약이라
#  늘리지 않는다. 새 잠금은 전부 이쪽으로 들어온다.
INTERNAL_ACTIONS = {
    # 기록은 권한 단계와 상관없이 항상 허용 (spec IV)
    "journal": "allow",
    # 훅 설정·정책·승인 로그 자신을 지키는 잠금
    "selfProtect": "block",
    # 서버 쪽 보호 목록. 정책으로도 못 연다 (아래 HARD_PROTECTED)
    "hardProtect": "block",
    # 비밀 값이 든 파일. 읽기까지 막는 유일한 분류
    "secret": "block",
    # 돌고 있거나 끝난 실험의 원본 출력 보존
    "outputProtect": "block",
    # 분류되지 않은 것은 Claude Code 기본 권한 흐름에 맡긴다
    "unknown": "defer",
}

#: 이 파일(app/policy_defaults.py)에서 두 번 올라가면 `server/` 다.
_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Claude Code 를 켤 때 쓸 권한 모드. 생성기가 프로젝트
#: `.claude/settings.json` 에 박아 둔다. 2.1.317 은 **사용자 설정에
#: defaultMode 가 없으면 auto** 로 떠서, 새로 띄운 세션이 권한 우회 모드로
#: 시작한다(실측 2026-11-04 00:46:55). 프로젝트 설정이 사용자 설정보다
#: 우선하고 `.claude/**` 는 selfProtect 라 AI 가 되돌릴 수 없다.
DEFAULT_PERMISSION_MODE = "default"


def hard_protected_roots() -> list[str]:
    """보호 목록의 **실제 경로** (glob 이 아니라 비교용).

    `extraWritableRoots` 와 겹치는지 볼 때 쓴다. 겹쳐도 판정은 보호 목록이
    먼저라 안 뚫리지만, 설정한 사람이 "열었다" 고 오해하지 않게 알려야 한다.
    """
    from . import registry

    return [
        _SERVER_DIR,
        registry.data_dir(),
        os.path.expanduser("~/.claude"),
        os.path.expanduser("~/.claude.json"),
    ]


def HARD_PROTECTED() -> list[str]:
    """권한 설정과 **무관하게** 항상 쓰기·삭제를 막는 절대 경로 glob.

    정책 파일이 아니라 코드에 둔다 — 정책으로 뺄 수 있으면 보호가 아니다.
    `extraWritableRoots` 보다 **앞에서** 판정하므로 예외 경로로도 못 연다.

    왜 이것들인가
      server/**        훅 코드 자신과 정책·실행 상태·래퍼·레지스트리.
                       판정 코드를 고칠 수 있으면 정책을 지키는 의미가 없다.
      LAB_DATA_DIR     런타임 폴더를 옮겨 놨어도 따라가게.
      ~/.claude/**     훅 등록(settings.json)·자격 증명·사용자 훅 스크립트.
      ~/.claude.json*  **사용자 MCP 서버 설정.** 쓰기 가능한 MCP 를 붙이면 이
                       게이트를 그냥 지나간다 — 한계 안내로만 적어 두던 구멍을
                       설정 변경 쪽에서 막는다. (이미 붙어 있는 서버는 여전히
                       지나간다. docs/operations.md 의 한계 참고)
    """
    return [f"{root.rstrip('/')}/**" for root in hard_protected_roots()] + [
        "~/.claude.json*"  # .claude.json 은 폴더가 아니라 파일이다 (+ .backup)
    ]


#: 비밀 값이 든 파일. **읽기까지** 막는다 (그 밖의 프로젝트 밖 읽기는 허용).
#: 실제 비밀은 프로젝트 폴더 **밖** `~/.config/labremote/<프로젝트>.env` 에 둔다
#: — 재귀 읽기(`grep -r`)는 훅이 못 막으므로 위치 규칙이 1차 방어다.
#:
#: 홈의 자격 증명을 전부 넣었다. 네트워크가 열려 있으니 **읽히면 곧 나간다** —
#: SSH 키 하나로 저장소가, AWS 자격 증명 하나로 계정이 열린다. 학습 샌드박스는
#: 홈을 통째로 가리지만(`runner/sandbox.home_dirs`), 훅은 Claude 의 **도구
#: 호출**을 막는 자리라 따로 적어야 한다.
SECRET_FILES = [
    "~/.claude/.credentials.json",
    "~/.config/labremote/**",
    "**/.env",
    "**/.env.*",
    # SSH·GPG — 키 하나로 저장소와 서버가 열린다
    "~/.ssh/**",
    "~/.gnupg/**",
    # 자격 증명 파일
    "~/.git-credentials",
    "~/.netrc",
    "~/.pypirc",
    "~/.npmrc",
    "~/.aws/**",
    "~/.azure/**",
    "~/.config/gcloud/**",
    "~/.kube/config",
    "~/.docker/config.json",
    "~/.kaggle/**",
    "~/.config/gh/**",
    "~/.config/hub",
    "~/.huggingface/**",
    "~/.cache/huggingface/token",
    "~/.netrc.gpg",
    # 브라우저·편집기 프로필 — 저장된 비밀번호와 세션 쿠키가 있다
    "~/.mozilla/**",
    "~/.config/google-chrome/**",
    "~/.config/chromium/**",
    "~/.config/BraveSoftware/**",
    "~/.config/Code/**",
    "~/.config/Code - OSS/**",
    "~/.vscode/**",
    # 셸 기록 — 붙여 넣은 토큰이 그대로 남아 있다
    "~/.bash_history",
    "~/.zsh_history",
    "~/.python_history",
    "~/.psql_history",
    "~/.mysql_history",
]

#: 비밀이 아닌 것. 변수 **이름**만 적어 커밋하는 파일이라 읽을 수 있어야 한다.
#: SSH 공개키와 `known_hosts` 는 비밀이 아니다 — git 원격을 쓰려면 봐야 한다.
SECRET_EXEMPT = [
    "**/.env.example",
    "**/.env.sample",
    "**/.env.template",
    "~/.ssh/*.pub",
    "~/.ssh/known_hosts",
    "~/.ssh/known_hosts.old",
    "~/.ssh/config",
]

#: 이름만으로 막는 명령. **AI 가 ②를 되돌리지 못하게 하는 1차 자물쇠다.**
#:
#: ②가 `labremote approve` 같은 명령을 만드는 순간, Claude 의 Bash 가 그걸
#: 불러 **자기 요청을 스스로 승인**할 수 있다. 그러면 1회용 허가 설계 전체가
#: 무의미해진다. 그래서 승인·큐·서비스를 건드릴 수 있는 길을 이름부터 막는다.
#:
#: 이름만으로는 부족하다 — `python -m app.cli approve` 처럼 돌아가는 길은
#: `hooks/bashparse.py` 가 따로 본다.
DENY_COMMANDS = [
    # ① 에서부터 막던 것
    "claude",
    "shred",
    "mkfs",
    # 자기 승인·자기 조작 (②)
    "labremote",
    "sqlite3",
    "systemctl",
    "systemd-run",
    "loginctl",
    "kill",
    "pkill",
    "killall",
    # 격리를 깨는 것 — 학습 샌드박스가 이것들로 풀린다
    "bwrap",
    "unshare",
    "nsenter",
    "chroot",
    "setarch",
    # 프로세스에 붙어 들여다보거나 주입하는 것
    "strace",
    "ltrace",
    "gdb",
    # `-v /:/h` 한 줄이면 호스트 전체가 열린다
    "docker",
    "podman",
    # 훅 밖에서 나중에 실행되는 길
    "at",
    "batch",
    "crontab",
]

BASH_DEFAULTS = {
    "escalateOnSubstitution": True,
    "denyCommands": list(DENY_COMMANDS),
    # git 원격은 ②의 오케스트레이터가 전담한다. net 으로 보면 ask 소음만 늘어난다.
    "gitRemoteAsNet": False,
    # 헤드리스 허용 목록에 **더하는** 명령. 빼지는 못한다 (코드가 기본 목록의
    # 단일 출처다). AI 가 정책을 통해 목록을 넓히는 길을 막으려는 것이고,
    # 정책 파일은 어차피 프로젝트 밖이라 AI 가 못 고친다.
    # [사람이 손으로 추가할 명령 — 비어 있음]
    "allowExtra": [],
    # `specifications/Config.yaml` 의 `run.entrypoints` 를 **복사**해 둔다.
    # 훅은 YAML 을 읽지 않으므로(표준 라이브러리만) 여기로 거울을 둔다.
    # Claude 가 학습을 직접 돌리면 `newexp` 로 분류해 승인을 받는다.
    # [Config.yaml 의 entrypoints — 생성기가 채움]
    "entrypoints": [],
}

RUNNER_DEFAULTS = {
    # `~/.config/labremote/config.toml` 의 `[tokens]` 중 **학습에 넣어 줄 이름**.
    # 기본은 비어 있다 — 아무것도 주입하지 않는다.
    #
    # ⚠ 학습 코드는 AI 가 쓴 코드다. 환경 변수는 `os.environ` 한 줄이면 보인다.
    # 샌드박스는 파일을 가려 주지만 환경 변수는 못 가린다. 그래서 여기 적는 건
    # **읽기 전용·최소 권한 토큰만** 이어야 한다.
    # [학습에 필요한 토큰 이름 — 비어 있음. 예: HF_TOKEN, WANDB_API_KEY]
    "injectTokens": [],
}

HEADLESS_DEFAULTS = {
    # 실측(2026-11-04): `claude -p` 의 ask 는 사람에게 가지 않고 10초 안에
    # 자동 거부된다. 기다려 주지 않으므로 사유를 붙여 우리가 먼저 막고,
    # 승인 요청을 data/requests/ 에 남겨 ②의 대기열로 넘긴다.
    "onAsk": "deny-with-reason",
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
            # 원본 출력 보존 (PDF 9쪽). 돌고 있거나 한 번이라도 시작된 실험의
            # output/ 은 지우기·비우기·덮어쓰기 전부 막는다. result.csv 와
            # 로그는 **삭제·이동만** 막는다 — 루프가 돌면서 result.csv 를
            # 다시 쓰는 건 정상 동작(journal)이다.
            "outputDirs": ["output", "checkpoints"],
            "outputDeleteOnly": ["result.csv", "*.log"],
            # spec 은 폴더 밖 쓰기·삭제만 막는다. 읽기는 막지 않는다 —
            # 다만 아래 비밀 파일만 예외로 읽기까지 막는다. 정책 파일 읽기는
            # 허용한다(보호는 비밀이 아니라 강제로 하고 있고, 템플릿은 이미
            # 저장소에 공개돼 있다). docs/operations.md 에 근거를 적어 뒀다.
            "allowOutsideRead": True,
            # 헤드리스에서 **승인 없이 읽어도 되는** 뿌리. 기본은 프로젝트뿐이고
            # 여기 적은 것이 더해진다. conda 환경이나 공용 데이터셋을 Claude 가
            # 읽어야 하면 적어 주세요.
            # [읽기 허용 뿌리 — 비어 있음. 예: ~/miniconda3, ~/datasets]
            "readAllowRoots": [],
            # 코드의 SECRET_FILES 에 **더하는** 목록. 빼지는 못한다.
            # [웹훅·API 키 파일을 다른 곳에 둔다면 여기에]
            "secretFilesExtra": [],
            # 샌드박스 안에서 **쓸 수 있는 유일한 바깥**. 모델·pip·W&B 캐시와
            # 임시 파일이 여기로 모인다. 비우면 코드 기본값(~/lab-cache)이고,
            # 보호 경로(~/.claude · ~/.config/labremote · server/ · 다른
            # 프로젝트)와 겹치면 런처가 거부한다(`runner/cache.py`).
            "cacheDir": "",
            # 데이터셋 심볼릭 링크 예외. [데이터셋 링크 경로 — 미확인]
            # ⚠ 보호 목록(HARD_PROTECTED)과 겹쳐도 보호 목록이 이긴다.
            #   겹치면 doctor 가 ✘ 로 알리고 policy set 이 저장을 거부한다.
            "extraWritableRoots": [],
        },
        "bash": dict(BASH_DEFAULTS),
        "headless": dict(HEADLESS_DEFAULTS),
        "runner": dict(RUNNER_DEFAULTS),
        "logPath": L.LOOP_LAYOUT["approval_log"],
        "eventLogPath": L.LOOP_LAYOUT["hook_events"],
        "updatedAt": _now(),
        "updatedBy": "generator",
    }
