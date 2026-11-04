"""훅이 Claude 에게 돌려주는 사유 문구. 한 곳에 모아 둔다.

전부 한국어 해요체다 (`CLAUDE.md` 규칙). 그리고 **모든 deny·ask 사유에
`NO_WORKAROUND` 를 붙인다** — 2.1.317 실측에서 Edit 가 거절되자 Claude 가
`sed -i` 로, 그것도 막히자 `Write` 로 우회를 시도했다. 거절만 하고 끝내면
다른 도구를 찾으므로, 사유로 "멈추고 보고" 를 지시해야 한다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

__all__ = ["NO_WORKAROUND", "with_guard", "LABELS", "josa"]

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
    "hardProtect": "서버 보호 파일",
    "secret": "비밀 파일",
    "outputProtect": "실험 산출물 보존",
    "suspicious": "확인이 필요한 명령",
    "unparsed": "해석 못 한 명령",
    "unclassified": "분류 못 한 명령",
    "schema-unknown": "훅이 못 읽은 입력",
    "denied-command": "금지된 명령",
}


def with_guard(text: str) -> str:
    """사유 끝에 우회 금지 지시를 붙인다."""
    text = text.rstrip()
    if NO_WORKAROUND in text:
        return text
    return f"{text} {NO_WORKAROUND}"


# --- 조사 ------------------------------------------------------------------
# "패키지 설치 은 승인이 필요해요" 가 실측에서 나왔다. 이름이 정책 파일에서
# 오고 경로가 도구에서 오니, 문구를 쓰는 쪽에서 미리 고를 수 없다.

#: 받침이 있는 것으로 읽는 숫자 (일·삼·육·칠·팔·영/공 -> ㄹ ㅁ ㄱ ㄹ ㄹ ㅇ)
_DIGITS_WITH_FINAL = set("0136780")


def josa(word: str, pair: str = "은/는") -> str:
    """`word` 뒤에 붙일 조사를 골라 돌려준다 (조사만, 단어는 안 붙인다).

    한글 음절이면 종성으로, 숫자면 발음으로 고른다. 라틴 문자·기호로 끝나면
    **받침 없는 쪽**으로 떨어진다 — `analysis.md는` 처럼 읽히는 게 자연스럽고,
    영문 철자 발음까지 맞히려 들면 틀리는 경우가 더 많다.
    """
    with_final, without_final = pair.split("/")
    text = (word or "").rstrip()
    if not text:
        return without_final
    last = text[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:  # 가 ~ 힣
        return with_final if (code - 0xAC00) % 28 else without_final
    if last.isdigit():
        return with_final if last in _DIGITS_WITH_FINAL else without_final
    return without_final


# --- 잠긴 항목 -------------------------------------------------------------


def outside(target: str) -> str:
    return (
        f"프로젝트 폴더 밖은 쓰거나 지울 수 없어요: {target} · "
        "잠긴 항목이라 권한 단계와 상관없이 항상 막혀요."
    )


def self_protect(rel: str) -> str:
    return (
        f"{rel}{josa(rel)} 훅과 권한 설정을 지키는 파일이라 바꿀 수 없어요. "
        "권한을 바꾸려면 웹 UI 의 권한 설정이나 labremote policy set 을 써 주세요."
    )


def hard_protect(target: str) -> str:
    """정책으로도 못 여는 보호 목록. `extraWritableRoots` 보다 앞에서 판정한다."""
    return (
        f"{target}{josa(target)} 훅·권한 정책·MCP 설정을 담은 서버 쪽 파일이라 "
        "어떤 권한 설정에서도 바꿀 수 없어요. 권한을 바꾸려면 웹 UI 의 권한 "
        "설정이나 labremote policy set 을 써 주세요."
    )


def secret(target: str) -> str:
    """비밀 파일. 읽기·쓰기·복사 모두 막는다."""
    return (
        f"{target}{josa(target)} 비밀 값이 든 파일이라 읽거나 복사할 수 없어요. "
        "값이 필요하면 환경 변수 이름만 알려 주세요. 실험에 쓸 비밀 값은 "
        "프로젝트 폴더 밖(~/.config/labremote/<프로젝트>.env)에 둬요."
    )


def output_protect(rel: str, exp: str, how: str) -> str:
    """실험 산출물 보존. 지우기·비우기·덮어쓰기 전부 막는다."""
    return (
        f"{exp} 의 원본 출력이라 {how} 수 없어요 ({rel}). 결과를 다시 뽑아야 하면 "
        "새 실험 폴더에서 돌리고, 왜 그렇게 했는지 logs/Decision_log.md 에 "
        "남겨 주세요."
    )


def prev_locked(rel: str, exp: str) -> str:
    return (
        f"이전 실험 폴더 {exp} 는 덮어쓸 수 없어요 ({rel}). "
        "새 실험 폴더를 만들어 거기에 쓰고, 왜 그렇게 했는지 "
        "logs/Decision_log.md 에 남겨 주세요."
    )


def prev_appendable(rel: str, exp: str) -> str:
    return (
        f"{rel}{josa(rel)} 끝난 실험 {exp} 의 분석 노트예요. 결과 리뷰를 덧붙이는 "
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
        f"{rel}{josa(rel)} 종료 조건·평가 기준이라 잠겨 있어요. 지금은 실험이 멈춰 "
        "있으니 승인하면 바꿀 수 있어요. 바꾼 이유를 logs/Decision_log.md 에 남겨 주세요."
    )


# --- 정책에서 온 판정 -------------------------------------------------------


def ask_action(name: str, what: str) -> str:
    return f"{name}{josa(name)} 승인이 필요해요: {what}"


def block_action(name: str, what: str) -> str:
    return f"{name}{josa(name)} 지금 권한 단계에서 막혀 있어요: {what}"


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


def unclassified(cmd: str) -> str:
    """명령 꼴은 읽었지만 무엇을 건드리는지 모를 때.

    래퍼(`conda run`·`xargs`…)나 처음 보는 명령이 여기로 온다. 모르는 것을
    자동으로 열지 않는 게 목적이다.
    """
    return (
        f"훅이 이 명령이 무엇을 건드리는지 알지 못해요: {cmd} · "
        "모르는 명령은 자동으로 허용하지 않아요. 무엇을 하려는지 알려 주거나 "
        "아는 명령으로 풀어서 써 주세요."
    )


def headless_ask(name: str, inner: str) -> str:
    """헤드리스에서 승인창을 띄울 수 없을 때. 자동 허용으로는 절대 안 넘어간다.

    실측(2.1.317): `claude -p` 에서 ask 는 사람에게 가지 않고 10초 안에 자동
    거부된다. 그래서 기본값이 `deny-with-reason` 이고, 사유에 "요청을 남겨
    뒀다" 를 적어 ②의 승인 대기열로 넘긴다.
    """
    return (
        f"[승인 필요: {name}] {inner} 화면 없이 실행 중이라 지금은 승인받을 수 "
        "없어요. 승인 요청을 남겨 두었어요. 작업을 멈추고 보고해 주세요."
    )


def bypass_attempt(rel: str, before: str, now: str) -> str:
    return (
        f"{rel}{josa(rel)} 조금 전 {before} 로 막힌 대상이에요. {now} 로 다시 "
        "시도하는 건 우회예요."
    )
