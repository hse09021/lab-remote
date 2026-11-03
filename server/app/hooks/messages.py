"""훅이 Claude 에게 돌려주는 사유 문구. 한 곳에 모아 둔다.

전부 한국어 해요체다 (`CLAUDE.md` 규칙). 그리고 **모든 deny·ask 사유에
`NO_WORKAROUND` 를 붙인다** — 2.1.317 실측에서 Edit 가 거절되자 Claude 가
`sed -i` 로, 그것도 막히자 `Write` 로 우회를 시도했다. 거절만 하고 끝내면
다른 도구를 찾으므로, 사유로 "멈추고 보고" 를 지시해야 한다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

__all__ = ["NO_WORKAROUND", "with_guard", "LABELS"] 

#: 우회 금지 지시. 모든 deny·ask 사유 끝에 붙는다.
NO_WORKAROUND = "다른 도구나 명령으로 돌아가지 말고 작업을 멈추고 보고해 주세요."

#: 승인 로그 `handledBy` 칸
BY_LOCK = "Hooks · 잠금"
BY_POLICY = "AI · 권한 단계"
BY_APP = "Claude 앱"
BY_SYSTEM = "시스템"

#: 승인 로그 `action` 칸에서 정책 밖 분류에 쓰는 이름
LABELS = {
    "journal": "기록 갱신",
    "selfProtect": "훅·정책 파일 보호",
    "suspicious": "확인이 필요한 명령",
    "unparsed": "해석 못 한 명령",
    "schema-unknown": "훅이 못 읽은 입력",
    "denied-command": "금지된 명령",
}


def with_guard(text: str) -> str:
    """사유 끝에 우회 금지 지시를 붙인다."""
    text = text.rstrip()
    if NO_WORKAROUND in text:
        return text
    return f"{text} {NO_WORKAROUND}"


# --- 잠긴 항목 -------------------------------------------------------------


def outside(target: str) -> str:
    return (
        f"프로젝트 폴더 밖은 쓰거나 지울 수 없어요: {target} · "
        "잠긴 항목이라 권한 단계와 상관없이 항상 막혀요."
    )


def self_protect(rel: str) -> str:
    return (
        f"{rel} 은 훅과 권한 설정을 지키는 파일이라 바꿀 수 없어요. "
        "권한을 바꾸려면 웹 UI 의 권한 설정이나 labremote policy set 을 써 주세요."
    )


def prev_locked(rel: str, exp: str) -> str:
    return (
        f"이전 실험 폴더 {exp} 는 덮어쓸 수 없어요 ({rel}). "
        "새 실험 폴더를 만들어 거기에 쓰고, 왜 그렇게 했는지 "
        "logs/Decision_log.md 에 남겨 주세요."
    )


def prev_appendable(rel: str, exp: str) -> str:
    return (
        f"{rel} 은 끝난 실험 {exp} 의 분석 노트예요. 결과 리뷰를 덧붙이는 "
        "것이면 승인해 주세요. 결과 자체를 고치는 것이면 안 돼요."
    )


def stop_running(rel: str, exp: str | None) -> str:
    running = f"{exp} 가 돌고 있어요" if exp else "실험이 돌고 있어요"
    return (
        f"{running}. 지금은 종료 조건과 평가 기준({rel})을 바꿀 수 없어요. "
        "결과를 보고 기준을 고치면 실험이 의미를 잃어요."
    )


def stop_idle(rel: str) -> str:
    return (
        f"{rel} 은 종료 조건·평가 기준이라 잠겨 있어요. 지금은 실험이 멈춰 "
        "있으니 승인하면 바꿀 수 있어요. 바꾼 이유를 logs/Decision_log.md 에 남겨 주세요."
    )


# --- 정책에서 온 판정 -------------------------------------------------------


def ask_action(name: str, what: str) -> str:
    return f"{name} 은 승인이 필요해요: {what}"


def block_action(name: str, what: str) -> str:
    return f"{name} 은 지금 권한 단계에서 막혀 있어요: {what}"


def denied_command(cmd: str) -> str:
    return (
        f"이 명령은 쓸 수 없어요: {cmd} · 훅을 끄거나 돌아가는 데 쓰일 수 있는 명령이에요."
    )


# --- 훅 자신의 문제 ---------------------------------------------------------


SCHEMA_UNKNOWN = (
    "훅이 이 도구의 대상 경로를 읽지 못했어요. 안전을 위해 막았어요. "
    "logs/hook_events.jsonl 에 받은 키를 남겼으니 알려 주세요."
)

HOOK_ERROR = "훅이 판정에 실패했어요(기록은 남겼어요). 작업을 멈추고 알려 주세요."

BAD_INPUT = "훅이 입력을 읽지 못했어요. 작업을 멈추고 알려 주세요."


def policy_error(detail: str) -> str:
    return f"권한 정책을 읽을 수 없어 막았어요: {detail}"


def suspicious(cmd: str) -> str:
    return (
        f"명령 안에 다른 명령을 끼워 넣는 부분이 있어서 훅이 무엇을 건드리는지 "
        f"알 수 없어요: {cmd} · 무엇을 하려는지 풀어서 다시 써 주세요."
    )


def unparsed(cmd: str) -> str:
    return f"명령을 해석하지 못했어요(따옴표가 안 맞는 것 같아요): {cmd}"


def headless_ask(name: str, inner: str) -> str:
    """헤드리스에서 승인창을 띄울 수 없을 때. 자동 허용으로는 절대 안 넘어간다."""
    return (
        f"[승인 필요: {name}] {inner} 지금은 사람에게 물어볼 수 없는 "
        "자동 실행이라 일단 막았어요. 승인 대기로 알렸으니 기다려 주세요."
    )


def bypass_attempt(rel: str, before: str, now: str) -> str:
    return (
        f"{rel} 은 조금 전 {before} 로 막힌 대상이에요. {now} 로 다시 시도하는 건 "
        "우회예요."
    )
