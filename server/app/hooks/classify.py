"""도구 호출 -> 행동 유형(Finding).

**필드명은 추측이 아니라 실측값이다.** 2026-11-03, Claude Code 2.1.317
(native) 에서 덤프 훅으로 받은 stdin 을 보고 확정했다. 원본은
`server/tests/fixtures/hook_events/` 에 있다.

    PreToolUse 최상위:
      session_id, transcript_path, cwd, prompt_id, permission_mode,
      effort{level}, hook_event_name, tool_name, tool_input, tool_use_id

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

__all__ = ["Finding", "Ctx", "classify_event", "classify_path", "target_paths"]


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

#: 읽기 전용이라 판정하지 않는 도구. matcher 에도 넣지 않는다.
#  ToolSearch 는 도구 스키마만 불러온다 (실측: tool_input = {query, max_results}).
#  다만 쓰기 가능한 MCP 도구를 불러올 수는 있으므로 MCP 구멍 안내에 함께 적는다.
READ_ONLY_TOOLS = ("Read", "Glob", "Grep", "ToolSearch", "TodoWrite")


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


def classify_path(raw: str, ctx: Ctx, *, deleting: bool = False) -> list[Finding]:
    """경로 하나를 보고 Finding 을 만든다.

    여러 개가 나올 수 있다 (예: 이전 실험 폴더의 config.yaml -> prev + hparam).
    가장 제한적인 것이 이기는 건 decide.combine 이 한다.
    """
    cfg = ctx.paths_cfg
    target = paths.safe_resolve(raw, ctx.cwd)
    rel = paths.rel_or_none(ctx.root, target)

    if rel is None:
        extra = cfg.get("extraWritableRoots") or []
        if extra and paths.is_inside_any(extra, target):
            return [
                Finding("code", rel=raw, target=target, detail="extraWritableRoots 예외", writes=True)
            ]
        return [Finding("outside", target=target, writes=True)]

    out: list[Finding] = []
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
            found.extend(classify_path(item, ctx))
        return found

    if tool == "Bash":
        from . import bashparse

        command = pick(tool_input, COMMAND_KEYS)
        if command is None:
            return [Finding("schema-unknown", detail=f"Bash · 받은 키: {sorted(tool_input)}", writes=True)]
        return bashparse.classify(str(command), ctx)

    if tool in NET_TOOLS:
        return [Finding("net", target=str(pick(tool_input, URL_KEYS) or ""))]

    # 읽기 전용이거나 모르는 도구 -> 판정하지 않는다 (defer)
    return []
