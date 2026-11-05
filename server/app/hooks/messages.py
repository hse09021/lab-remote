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
BY_GRANT = "사람 승인 · 1회용"

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
    "bashAllowed": "읽기 명령",
    "readAllowed": "프로젝트 안 읽기",
    "toolAllowed": "읽기 도구",
    "readOutside": "프로젝트 밖 읽기",
    "schema-unknown": "훅이 못 읽은 입력",
    "denied-command": "금지된 명령",
    "trainrun": "학습 직접 실행",
    "coderun": "코드 실행 (소켓 차단 확인 전)",
}


def with_guard(text: str) -> str:
    """사유 끝에 우회 금지 지시를 붙인다."""
    text = text.rstrip()
    if NO_WORKAROUND in text:
        return text
    return f"{text} {NO_WORKAROUND}"


def add_before_guard(text: str, extra: str) -> str:
    """이미 우회 금지 지시가 붙은 사유에 한 마디를 **그 앞에** 끼운다.

    "멈추고 보고해 주세요" 가 문장 중간에 끼면 지시가 흐려진다.
    """
    if not extra:
        return text
    head = text.replace(NO_WORKAROUND, "").rstrip() if NO_WORKAROUND in text else text.rstrip()
    return with_guard(f"{head} {extra}")


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


#: 📦 패키지 설치만 안내가 다르다 — 승인해도 **Claude 의 Bash 로는 안 된다.**
#:
#: S1 의 M3 실측: conda 환경은 프로젝트 밖이라 샌드박스가 쓰기를 버린다.
#: `pip install` 이 프로그램에는 성공으로 보이고 실제로는 아무 일도 안 난다.
#: 그래서 요청 파일을 쓰게 안내한다 — 설치는 오케스트레이터가 한다.
PKG_HINT = (
    "설치는 제가 직접 못 해요 — conda 환경이 프로젝트 폴더 밖이라 샌드박스가 "
    "쓰기를 버려서, 성공한 것처럼 보이고 실제로는 안 깔려요. "
    "{request} 에 패키지 이름과 버전만 적어 주세요 "
    '(예: {{"version": 1, "packages": [{{"name": "peft", "spec": "==0.13.2"}}], '
    '"reason": "왜 필요한지"}}). '
    "사람이 승인하면 시스템이 설치하고 결과를 {result} 로 알려 줘요."
)


def pkg_hint() -> str:
    from .. import loop_layout as L

    return PKG_HINT.format(
        request=L.LOOP_LAYOUT["install_request"],
        result=L.LOOP_LAYOUT["install_result"],
    )


def ask_action(name: str, what: str, *, action: str = "") -> str:
    text = f"{name}{josa(name)} 승인이 필요해요: {what}"
    if action == "pkg":
        text += " · " + pkg_hint()
    return text


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
    # ⚠ `inner` 에 이미 `NO_WORKAROUND`("…작업을 멈추고 보고해 주세요.")가
    # 붙어 있다(`with_guard`). 여기서 또 붙이면 같은 지시가 두 번 나온다 —
    # 실측에서 Claude 가 받은 사유에 그대로 두 번 보였다.
    tail = "화면 없이 실행 중이라 지금은 승인받을 수 없어요. 승인 요청을 남겨 두었어요."
    if NO_WORKAROUND not in inner:
        tail += " " + NO_WORKAROUND
    return f"[승인 필요: {name}] {inner} {tail}"


def also_needed(names: list[str]) -> str:
    """한 호출에서 걸린 행동이 둘 이상일 때. **전부** 보여 준다.

    하나만 알려 주면 Claude 가 "그것만 승인받으면 된다" 고 보고하게 되고,
    사람은 나머지를 모른 채 승인한다.
    """
    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    if len(unique) < 2:
        return ""
    return "이 호출에서 승인이 필요한 것이 " + str(len(unique)) + "가지예요: " + " · ".join(unique) + "."


def read_outside(target: str) -> str:
    """프로젝트 밖 읽기. 헤드리스에서만 승인을 받는다."""
    return (
        f"프로젝트 폴더 밖이라 읽기 전에 승인이 필요해요: {target} · "
        "자격 증명이나 남의 자료일 수 있고, 네트워크가 열려 있어서 읽은 건 "
        "밖으로 나갈 수 있어요. 꼭 필요하면 무엇에 쓰는지 알려 주세요."
    )


def grant_used(name: str, grant_id: str) -> str:
    """사람이 승인한 1회용 허가로 통과했을 때. 다시 쓸 수 없다는 걸 적는다."""
    return (
        f"{name}{josa(name)} 사람이 승인해 준 1회용 허가로 진행해요 ({grant_id}). "
        "같은 허가는 다시 쓸 수 없어요."
    )


def bypass_attempt(rel: str, before: str, now: str) -> str:
    return (
        f"{rel}{josa(rel)} 조금 전 {before} 로 막힌 대상이에요. {now} 로 다시 "
        "시도하는 건 우회예요."
    )

#: 🔑 **학습은 오케스트레이터만 띄운다** — 헤드리스는 프리셋과 무관하게 거절.
#:
#: 왜 `newexp` 에서 떼어 냈나 (2026-11-05): `full` 프리셋은 `newexp` 를
#: **자동 허용**한다. entrypoint 직접 실행이 `newexp` 였으니, `full` 에서는
#: Claude 가 학습을 혼자 돌릴 수 있었다. 그러면 셋이 깨진다.
#:
#:   1. 오케스트레이터의 GPU 큐와 **동시에** GPU 를 쓴다
#:      (`ux_jobs_running` 은 우리 큐만 지킨다 — 큐 밖의 프로세스는 못 막는다)
#:   2. 10분 넘는 Bash 문제가 다시 생긴다 (①의 [미확인] (b))
#:   3. "학습은 오케스트레이터만" 원칙이 깨진다 — `run.json` 검증도,
#:      샌드박스도, 타임아웃도, 체크포인트 회수도 전부 지나간다
#:
#: 그래서 정책이 정하는 자리에 두지 않는다. 권한 단계를 올려도 안 열린다.
def trainrun_headless(what: str) -> str:
    return (
        f"학습은 제가 직접 돌리지 않아요: {what} · "
        "학습은 시스템(오케스트레이터)이 띄워요 — GPU 를 한 번에 하나만 쓰고, "
        "타임아웃·체크포인트·샌드박스를 같이 걸어 줘요. "
        "experiments/<실험 ID>/run.json 에 entrypoint 와 args 로 **명세만** "
        "적어 주세요. 그러면 시스템이 돌리고 결과를 알려 줘요. "
        "권한 단계와 무관하게 막혀 있어서 승인으로도 열리지 않아요."
    )


def coderun_unverified(what: str, project: str = "<프로젝트>") -> str:
    return (
        f"코드 실행은 지금 승인이 필요해요: {what} · "
        "Claude Bash 샌드박스가 유닉스 소켓을 막는지 사람이 아직 확인하지 않아서, "
        "헤드리스에서는 권한 단계와 무관하게 사람이 한 번 보고 정해요. "
        f"확인 절차: labremote sandbox-check {project} → 결과를 보고 "
        f"labremote policy-socket-verified {project} --on --note \"…\""
    )


def trainrun_interactive(what: str) -> str:
    return (
        f"학습을 직접 돌리려고 해요: {what} · "
        "보통은 run.json 에 명세만 쓰고 시스템이 띄워요. "
        "그래야 GPU 를 한 번에 하나만 쓰고 타임아웃·체크포인트가 걸려요. "
        "그래도 지금 직접 돌릴 거면 승인해 주세요."
    )
