"""도구 호출 -> 행동 유형(Finding).

**필드명은 추측이 아니라 실측값이다.** 2026-11-03, Claude Code 2.1.317
(native) 에서 덤프 훅으로 받은 stdin 을 보고 확정했다. 원본은
`server/tests/fixtures/hook_events/` 에 있다.

    PreToolUse 최상위:
      session_id, transcript_path, cwd, prompt_id, permission_mode,
      effort{level}, hook_event_name, tool_name, tool_input, tool_use_id

    2026-11-04 에 더 본 것 (2.1.317):
      scratchpad_dir          임시 작업 폴더
      agent_id, agent_type    **서브에이전트 안에서 뜬 훅에만** 온다

    `agent_id` 가 대기 건 마감의 구분자다. 번들 스키마 설명대로 메인 스레드에는
    `--agent` 세션에서도 안 오고, `agent_type` 은 `--agent` 메인 스레드에도
    오므로 구분에 쓰면 안 된다 (`pretooluse._agent_of` 의 주석 참고).

    Edit   tool_input: file_path(절대), old_string, new_string, replace_all
    Write  tool_input: file_path(절대), content
    Bash   tool_input: command, description
    WebFetch tool_input: url, prompt
    Read   tool_input: file_path

후보로 남겨 둔 키는 아래 상수의 주석에 "실측 안 됨" 으로 표시했다. 다른
버전·다른 플랫폼에서 이름이 다를 수 있으니 지우지 않는다. 대신 **어느
후보로도 경로를 못 읽으면 차단**한다(`schema-unknown`).

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .. import paths
from .. import policy_defaults as D

__all__ = [
    "Finding",
    "Ctx",
    "classify_event",
    "read_allow_roots",
    "classify_path",
    "target_paths",
    "is_device_sink",
    "is_hard_protected",
    "is_secret",
]


# --- 실측한 키 -------------------------------------------------------------
# 맨 앞이 2.1.317 에서 실제로 본 키다. 뒤는 못 본 후보 — 순서대로 찾는다.

WRITE_PATH_KEYS = (
    "file_path",  # ✔ 실측 (Edit·Write·Read 모두)
    "notebook_path",  # 실측 안 됨 · NotebookEdit 용으로 남겨 둠
    "path",  # 실측 안 됨
    "filePath",  # 실측 안 됨 · camelCase 변형 대비
)

EDIT_OLD_KEYS = (
    "old_string",  # ✔ 실측
    "old_str",  # 실측 안 됨 · 다른 버전 표기 대비
)

EDIT_NEW_KEYS = (
    "new_string",  # ✔ 실측
    "new_str",  # 실측 안 됨
)

WRITE_TEXT_KEYS = (
    "content",  # ✔ 실측 (Write)
    "file_text",  # 실측 안 됨
    "contents",  # 실측 안 됨
)

EDIT_LIST_KEYS = ("edits",)  # 실측 안 됨 — 아래 MULTIEDIT 주석 참고

URL_KEYS = ("url", "query")  # ✔ url 실측 (WebFetch)

COMMAND_KEYS = ("command",)  # ✔ 실측 (Bash)

# MultiEdit 은 2.1.317 실측에서 **한 번도 관찰되지 않았다.** 한 파일 두 군데를
# 고치라고 시켜도 Claude 는 Edit 를 쓰고, 거절되자 Bash sed -> Write 순으로
# 우회했다. 그래도 matcher 와 아래 분류에서 빼지 않는다 — 다른 버전이나 다른
# 모델이 쓸 수 있고, 빠져 있으면 그게 그대로 구멍이 되기 때문이다.
MULTI_EDIT_TOOLS = ("MultiEdit",)

#: 파일을 쓰는 도구
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

#: 바깥으로 나가는 도구
NET_TOOLS = ("WebFetch", "WebSearch")

#: 📋 **2.1.318 에 실제로 있는 도구** (실측 2026-11-05 — 세션에 물어봤다).
#:
#: 직접: `Agent` `Artifact` `Bash` `Edit` `ListAgents` `Read` `ReportFindings`
#: `ScheduleWakeup` `SendFeedback` `Skill` `ToolSearch` `Workflow` `Write`
#: 지연: `ArtifactComments` `ArtifactData` `Cron{Create,Delete,List}`
#: `DesignSync` `Monitor` `NotebookEdit` `PushNotification` `RemoteTrigger`
#: `SendMessage` `TaskStop` `WebFetch` `WebSearch`
#:
#: ⚠ **없는 도구**: `Glob` `Grep` `TodoWrite` `MultiEdit` `NotebookRead` `LS`
#: `Task`. 번들에 문자열은 있지만 세션에 노출되지 않는다.
#:
#: 아래 목록에서 **빼지는 않는다** — 다른 판·다른 모델이 쓸 수 있고 빠져
#: 있으면 그게 구멍이다. 다만 **"막힌다" 고 말하지 않는다**: 없는 도구로는
#: 애초에 시도할 수 없다. `~/.ssh` 훑기의 실제 경로는 **`Bash`**(`ls`·
#: `grep -r`·`find`)이고 그건 `bashparse` 가 본다.
TOOLS_2_1_318 = frozenset(
    {
        "Agent", "Artifact", "ArtifactComments", "ArtifactData", "Bash",
        "CronCreate", "CronDelete", "CronList", "DesignSync", "Edit",
        "ListAgents", "Monitor", "NotebookEdit", "PushNotification", "Read",
        "RemoteTrigger", "ReportFindings", "ScheduleWakeup", "SendFeedback",
        "SendMessage", "Skill", "TaskStop", "ToolSearch", "WebFetch",
        "WebSearch", "Workflow", "Write",
    }
)

#: 이 판에는 **없는** 이름. 분류에는 남겨 두지만 시험·문서가 "막힌다" 고
#: 단정하지 않게 한 곳에 모아 둔다.
PHANTOM_TOOLS = frozenset(
    {"Glob", "Grep", "TodoWrite", "MultiEdit", "NotebookRead", "LS", "Task"}
)

#: 읽기 전용이라 경로 판정은 하지 않는 도구.
#  ToolSearch 는 도구 스키마만 불러온다 (실측: tool_input = {query, max_results}).
#  다만 쓰기 가능한 MCP 도구를 불러올 수는 있으므로 MCP 구멍 안내에 함께 적는다.
#  Skill·ReportFindings 는 2.1.318 에서 새로 보였다 — 파일을 안 건드린다.
#  `Glob`·`Grep`·`TodoWrite` 는 이 판에 없다 (PHANTOM_TOOLS).
READ_ONLY_TOOLS = (
    "Read", "Glob", "Grep", "ToolSearch", "TodoWrite", "Skill", "ReportFindings",
)

#: 경로를 받는 읽기 도구. 비밀 파일을 막고, **프로젝트 안인지**도 본다.
#  Read 는 file_path, Grep·Glob 은 path 를 쓴다.
#  ⚠ `Grep`·`Glob` 은 2.1.318 에 **없다.** 남겨 두는 건 앞날을 위한 것이고,
#  이 판에서 `~/.ssh` 를 훑는 실제 경로는 `Bash` 다.
SECRET_READ_TOOLS = {
    "Read": WRITE_PATH_KEYS,
    "Grep": ("path", "file_path"),
    "Glob": ("path", "file_path"),
}

#: 쓰기 대상으로 보지 않는 장치 파일. **정확한 이름만** 본다 —
#  `/dev/shm/x` 는 진짜 쓸 수 있는 폴더라 계속 막아야 한다.
#  실측: `ls .claude 2>/dev/null` 이 "폴더 밖 쓰기" 로 막혔다.
DEVICE_SINKS = frozenset(
    ["/dev/null", "/dev/zero", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty"]
)
#: `/dev/stderr` 는 `/proc/self/fd/2` 로 이어진다. 해소된 쪽도 알아봐야 한다.
_DEV_FD_RE = re.compile(r"\A(?:/dev/fd|/proc/self/fd|/proc/[0-9]+/fd)/[0-9]+\Z")


def is_device_sink(target: str) -> bool:
    """`/dev/null` 류인가. 쓰기 판정에서 아예 뺀다.

    `realpath` **전후 둘 다** 봐야 한다 — `/dev/stdout` 은 심볼릭 링크라
    해소하면 `/dev/pts/3` 이나 파이프 이름이 되어 알아볼 수 없다.
    """
    return target in DEVICE_SINKS or _DEV_FD_RE.match(target) is not None


@dataclass
class Finding:
    """도구 호출 하나에서 찾아낸 "이런 행동이 들어 있다" 한 건."""

    action: str
    rel: str | None = None  # 프로젝트 루트 기준 상대 경로
    target: str | None = None  # 절대 경로 · URL · 명령 조각
    detail: str = ""
    exp: str | None = None  # prev 일 때 어느 실험 폴더인지
    writes: bool = False  # 쓰기·삭제인가 (우회 추적에 쓴다)


@dataclass
class Ctx:
    """판정에 필요한 주변 정보."""

    root: str
    cwd: str
    name: str
    policy: object  # app.policy.Policy
    run: object  # app.runstate.RunState
    event: dict = field(default_factory=dict)
    headless: bool = False
    #: Claude Bash 샌드박스가 **실제로** 켜져 있나. 기본은 꺼짐으로 본다 —
    #: 모르면 코드 실행(`pytest` 등)을 열지 않는다 (fail-closed).
    sandbox: bool = False

    @property
    def paths_cfg(self) -> dict:
        return getattr(self.policy, "paths", {}) or {}


def pick(data: dict, keys: tuple[str, ...]):
    """후보 키를 순서대로 찾는다. 하나도 없으면 None."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def target_paths(tool: str, tool_input: dict) -> list[str]:
    """도구가 건드리는 파일 경로들. 하나도 못 찾으면 빈 리스트."""
    if tool in MULTI_EDIT_TOOLS:
        found: list[str] = []
        for item in pick(tool_input, EDIT_LIST_KEYS) or []:
            value = pick(item, WRITE_PATH_KEYS) if isinstance(item, dict) else None
            if value:
                found.append(str(value))
        shared = pick(tool_input, WRITE_PATH_KEYS)  # 상위에 공통 경로가 있는 변형
        if shared:
            found.append(str(shared))
        return found

    value = pick(tool_input, WRITE_PATH_KEYS)
    return [str(value)] if value else []


def previous_experiment(rel: str, ctx: Ctx) -> str | None:
    """끝났거나 실패한 실험 폴더면 그 ID, 아니면 None.

    주 근거는 **서버 쪽 runstate 의 `started` 목록**이다. 한 번이라도
    `labremote run-state --running` 으로 시작된 실험 ID 가 쌓이고, AI 는
    프로젝트 안에서 그 목록을 지울 수 없다.

    결과 파일(`result.csv`·`analysis.md`)은 **보조 근거**로만 본다.
      - AI 가 만들거나 지울 수 있어서 그것만으로는 약하다.
      - 중간에 죽은 실험은 result.csv 가 없다. 사양상 실패한 실험 폴더도
        남기고 새 폴더에서 재실행해야 하므로, started 가 그 구멍을 막는다.
      - 반대로 runstate 가 생기기 전에 만들어진 폴더는 started 에 없으니
        결과 파일로 건진다.

    지금 도는 실험은 "이전" 이 아니다.
    """
    cfg = ctx.paths_cfg
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != cfg.get("experimentsDir", "experiments"):
        return None
    exp = parts[1]
    if not re.match(cfg.get("experimentIdRe", "^EXP-[0-9]{3}$"), exp):
        return None
    if exp == getattr(ctx.run, "experiment_id", None):
        return None

    if exp in (getattr(ctx.run, "started", None) or []):
        return exp  # 한 번이라도 시작된 실험 — 결과가 없어도 손대면 안 된다

    folder = os.path.join(ctx.root, parts[0], exp)
    markers = cfg.get("prevMarkers") or ["result.csv", "analysis.md"]
    if any(os.path.exists(os.path.join(folder, m)) for m in markers):
        return exp  # 보조 근거: 결과가 남아 있는 폴더
    return None


def is_hard_protected(target: str) -> bool:
    """정책과 무관하게 항상 막는 서버 쪽 파일인가 (`extraWritableRoots` 보다 앞)."""
    return paths.match_abs_globs(target, D.HARD_PROTECTED())


def secret_patterns(ctx: Ctx) -> list[str]:
    """코드 목록 + **런타임 경로** + 정책이 더한 목록. 빼지는 못한다.

    런타임 경로는 `LAB_DATA_DIR` 를 따라 움직이는 것들이다
    (`<data>/denials/**` — 승인 증거. 파일 본문까지 담겨 있다).
    """
    extra = ctx.paths_cfg.get("secretFilesExtra") or []
    return (
        list(D.SECRET_FILES)
        + list(D.SECRET_RUNTIME())
        + [str(p) for p in extra if p]
    )


def is_secret(target: str, ctx: Ctx) -> bool:
    """비밀 값이 든 파일인가. 예시 파일(`.env.example`)은 비밀이 아니다."""
    if paths.match_abs_globs(target, D.SECRET_EXEMPT):
        return False
    return paths.match_abs_globs(target, secret_patterns(ctx))


def protected_experiment(rel: str, ctx: Ctx) -> str | None:
    """원본 출력을 지켜야 하는 실험 ID. **지금 도는 실험도 포함**한다.

    `previous_experiment` 와 다른 점이 여기다 — 이전 실험은 `prev` 잠금이
    이미 덮지만, "돌고 있는 실험의 output 을 지우는 것" 은 아무도 안 막고
    있었다(실측 8번에서 ask -> 승인으로 지워졌다). CLAUDE.md 는 "원본 출력을
    보존해요" 라고 적어 두고 훅은 ask 로 뒀던 불일치를 메운다.
    """
    cfg = ctx.paths_cfg
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != cfg.get("experimentsDir", "experiments"):
        return None
    exp = parts[1]
    if not re.match(cfg.get("experimentIdRe", "^EXP-[0-9]{3}$"), exp):
        return None
    if exp == getattr(ctx.run, "experiment_id", None):
        return exp
    if exp in (getattr(ctx.run, "started", None) or []):
        return exp
    folder = os.path.join(ctx.root, parts[0], exp)
    markers = cfg.get("prevMarkers") or ["result.csv", "analysis.md"]
    if any(os.path.exists(os.path.join(folder, m)) for m in markers):
        return exp
    return None


def _output_finding(rel: str, target: str, ctx: Ctx, *, deleting: bool, destructive: bool):
    """실험 산출물 보존 판정. 대상이 아니면 None."""
    if not destructive:
        return None
    exp = protected_experiment(rel, ctx)
    if not exp:
        return None
    cfg = ctx.paths_cfg
    inner = rel.split("/")[2:]  # experiments/EXP-NNN/<여기부터>
    if not inner:
        return None
    if inner[0] in (cfg.get("outputDirs") or ["output"]):
        how = "지우거나 비우거나 덮어쓸"
        return Finding(
            "outputProtect", rel=rel, target=target, exp=exp, detail=how, writes=True
        )
    # result.csv·로그는 **삭제·이동만** 막는다. 수정은 기록(journal)이다.
    if deleting and paths.match_globs(inner[-1], cfg.get("outputDeleteOnly") or []):
        return Finding(
            "outputProtect", rel=rel, target=target, exp=exp, detail="지우거나 옮길", writes=True
        )
    return None


def classify_path(
    raw: str,
    ctx: Ctx,
    *,
    deleting: bool = False,
    truncating: bool = False,
    overwrite: bool = False,
) -> list[Finding]:
    """경로 하나를 보고 Finding 을 만든다.

    여러 개가 나올 수 있다 (예: 이전 실험 폴더의 config.yaml -> prev + hparam).
    가장 제한적인 것이 이기는 건 decide.combine 이 한다.

    `deleting` 지우거나 밖으로 옮김 · `truncating` 비움(`>` · truncate) ·
    `overwrite` 기존 내용을 덮어씀(Write·Edit·cp 목적지). 셋 다 "파괴적" 이고,
    `overwrite` 는 **파일이 이미 있을 때만** 그렇다.
    """
    cfg = ctx.paths_cfg

    # /dev/null 류는 쓰기 대상이 아니다. `2>/dev/null` 이 막히면 읽기 명령까지
    # 승인을 받게 된다 (실측). 심볼릭 링크를 해소하면 /dev/pts/3 처럼 바뀌므로
    # **해소 전** 이름도 같이 본다.
    plain = os.path.expanduser(raw)
    if not os.path.isabs(plain):
        plain = os.path.normpath(os.path.join(ctx.cwd, plain))
    if is_device_sink(plain):
        return []

    target = paths.safe_resolve(raw, ctx.cwd)
    if is_device_sink(target):
        return []

    # 정책보다 앞선다. extraWritableRoots 예외로도 못 연다.
    if is_hard_protected(target):
        return [Finding("hardProtect", target=target, detail=raw, writes=True)]

    if is_secret(target, ctx):
        return [Finding("secret", target=target, detail=raw, writes=True)]

    rel = paths.rel_or_none(ctx.root, target)

    if rel is None:
        extra = cfg.get("extraWritableRoots") or []
        if extra and paths.is_inside_any(extra, target):
            return [
                Finding("code", rel=raw, target=target, detail="extraWritableRoots 예외", writes=True)
            ]
        return [Finding("outside", target=target, writes=True)]

    out: list[Finding] = []
    destructive = deleting or truncating or (overwrite and os.path.isfile(target))
    output_hit = _output_finding(
        rel, target, ctx, deleting=deleting, destructive=destructive
    )
    if output_hit:
        out.append(output_hit)
    if paths.match_globs(rel, cfg.get("selfProtectedFiles") or []):
        out.append(Finding("selfProtect", rel=rel, target=target, writes=True))
    if paths.match_globs(rel, cfg.get("stopLockedFiles") or []):
        out.append(Finding("stop", rel=rel, target=target, writes=True))

    exp = previous_experiment(rel, ctx)
    if exp:
        out.append(Finding("prev", rel=rel, target=target, exp=exp, writes=True))

    if paths.match_globs(rel, cfg.get("journalFiles") or []):
        out.append(Finding("journal", rel=rel, target=target, writes=True))
    elif paths.match_globs(rel, cfg.get("hparamFiles") or []):
        out.append(Finding("hparam", rel=rel, target=target, writes=True))
    elif deleting:
        out.append(Finding("del", rel=rel, target=target, writes=True))
    elif not out:
        out.append(Finding("code", rel=rel, target=target, writes=True))

    if deleting and not any(f.action == "del" for f in out):
        out.append(Finding("del", rel=rel, target=target, writes=True))
    return out


def read_allow_roots(ctx: Ctx) -> list[str]:
    """읽어도 되는 뿌리. 프로젝트 + 정책이 **더한** 목록.

    기본은 프로젝트뿐이다. conda 환경이나 데이터셋을 Claude 가 읽어야 하면
    정책의 `paths.readAllowRoots` 에 적는다 — 정책은 프로젝트 밖이라 AI 가
    못 고친다.
    """
    extra = ctx.paths_cfg.get("readAllowRoots") or []
    out = [ctx.root]
    for item in extra:
        text = str(item).strip()
        if text and not text.startswith("["):
            out.append(paths.real(text))
    return out


def _read_allowed(target: str, ctx: Ctx) -> bool:
    return any(paths.is_inside(paths.real(root), target) for root in read_allow_roots(ctx))


def classify_event(event: dict, ctx: Ctx) -> list[Finding]:
    """PreToolUse 이벤트 하나를 Finding 목록으로."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool in WRITE_TOOLS:
        targets = target_paths(tool, tool_input)
        if not targets:
            # 어느 후보 키로도 경로를 못 읽었다 -> 열지 않고 닫는다.
            return [
                Finding(
                    "schema-unknown",
                    detail=f"{tool} · 받은 키: {sorted(tool_input)}",
                    writes=True,
                )
            ]
        found: list[Finding] = []
        for item in targets:
            # 쓰기 도구는 기존 내용을 덮어쓴다. 파일이 이미 있으면 파괴적이다.
            found.extend(classify_path(item, ctx, overwrite=True))
        return found

    if tool in SECRET_READ_TOOLS:
        # 비밀 파일은 읽기까지 막는다. 그 밖은 **어디를 읽는지**로 가른다.
        raw = pick(tool_input, SECRET_READ_TOOLS[tool])
        if not raw:
            # 경로 없이 부른 것 (`Grep` 의 기본 경로 = cwd)
            return [Finding("toolAllowed", target=tool)]
        target = paths.safe_resolve(str(raw), ctx.cwd)
        if is_secret(target, ctx):
            return [Finding("secret", target=target, detail=f"{tool} · {raw}")]
        if _read_allowed(target, ctx):
            return [
                Finding(
                    "readAllowed",
                    rel=paths.rel_or_none(ctx.root, target),
                    target=target,
                )
            ]
        # 프로젝트 밖 읽기. 대화형은 그대로 두고(defer) 헤드리스는 승인을 받는다
        # — 네트워크가 열려 있으니 읽힌 건 곧 나갈 수 있다.
        return [Finding("readOutside", target=target, detail=f"{tool} · {raw}")]

    if tool == "Bash":
        from . import bashparse

        command = pick(tool_input, COMMAND_KEYS)
        if command is None:
            return [Finding("schema-unknown", detail=f"Bash · 받은 키: {sorted(tool_input)}", writes=True)]
        # 분류 못 한 세그먼트까지 받는다 — 미분류가 allow 로 떨어지는 구멍을 막는다.
        return bashparse.classify_with_coverage(str(command), ctx)

    if tool in NET_TOOLS:
        return [Finding("net", target=str(pick(tool_input, URL_KEYS) or ""))]

    if tool in READ_ONLY_TOOLS:
        # 경로를 안 받는 읽기·기록 도구 (`TodoWrite`·`ToolSearch`…)
        return [Finding("toolAllowed", target=tool)]

    # **모르는 도구.** 대화형은 Claude Code 승인 흐름에 맡기고(defer), 헤드리스는
    # 승인을 받는다. 헤드리스에서 defer 는 통과가 아니라 **정지**라서,
    # "모르는 건 조용히 지나간다" 가 아니라 "모르는 건 멈춘다" 로 둔다.
    return [Finding("unclassified", target=tool, detail="모르는 도구")]
