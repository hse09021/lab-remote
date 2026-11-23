"""Claude 연결 부품 — Python `claude-agent-sdk` 로 사용자가 **설치·로그인해 둔**
Claude Code 를 부른다(PLAN 1.2).

- `cli_path` 로 사용자의 `claude`(PATH · ~/.local/bin)를 쓴다. SDK 에 딸린 사본을
  쓰지 않는다.
- 읽을 설정: `setting_sources=["user", "project", "local"]` — 터미널에서 쓸 때와
  같게(사람이 고름, 2026-11-23). lab.remote 는 설정 파일을 **쓰지 않는다.**
- 권한: SDK 의 `can_use_tool` 콜백으로 받아 manager 에 넘긴다. bypass 계열 모드는
  쓰지 않는다.
- `AskUserQuestion`(객관식 질문)은 승인과 같은 길(`can_use_tool`)로 받아, 답을
  `updated_input={"questions": 원래 질문, "answers": {질문 글: 고른 label}}` 로 돌려준다.
- Ultracode 는 Claude Code 설정 키(`"ultracode": true`)다. 세션마다 `settings`
  (인라인 JSON → `--settings`)로 켠다 — 사용자 설정 파일을 쓰지 않는다
  (code.claude.com/docs/en/model-config · settings-reference).

확인한 것(설치된 claude-agent-sdk 0.2.187 · Claude Code 2.1.318):
`PermissionMode` = default·acceptEdits·plan·bypassPermissions·dontAsk·auto,
`EffortLevel` = low·medium·high·xhigh·max, 모델 목록은 연결 직후
`get_server_info()["models"]` 에 모델별 지원 Effort 와 함께 온다.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any

from .base import AgentBackend, ApprovalRequest, SessionConfig

__all__ = ["ClaudeBackend", "MODE_MAP", "EFFORTS", "cli_path", "probe_info", "probe_account", "summarize"]

#: 화면 Mode → SDK permission_mode
MODE_MAP = {"manual": "default", "edit": "acceptEdits", "plan": "plan", "auto": "auto"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
SETTING_SOURCES = ["user", "project", "local"]
#: 끄는 도구 — 없다. AskUserQuestion(Claude 의 객관식 질문)도 `can_use_tool` 로 와서
#: 화면의 질문 카드로 답한다(code.claude.com/docs/en/agent-sdk/user-input).
DISALLOWED: list[str] = []
#: 질문 도구 이름
ASK_TOOL = "AskUserQuestion"
#: 할 일 도구를 켠다. 공식 문서(code.claude.com/docs/en/agent-sdk/todo-tracking):
#: 할 일 도구는 Opus 4.7 · Sonnet 4.6 · Haiku 4.5 이하 모델에서만 기본으로 켜지고,
#: `allowed_tools` 에 할 일 도구 이름이 하나라도 있으면 그 세션은 켜진다.
#: 어느 계열(TodoWrite / Task*)이 나올지는 Claude Code 설정(CLAUDE_CODE_ENABLE_TASKS)
#: 에 따라 다르므로 둘 다 넣는다 — 실측(2026-11-23, 2.1.318)에서는 TodoWrite 가 나왔다.
#: 이 도구들은 화면의 할 일 목록만 고친다(파일·명령에 손대지 않음) — 승인 없이 둔다.
ALLOWED = ["TodoWrite", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]
OUTPUT_MAX = 4000


def cli_path() -> str:
    found = shutil.which("claude")
    if found:
        return found
    guess = os.path.expanduser("~/.local/bin/claude")
    return guess if os.access(guess, os.X_OK) else ""


def _scrub_env() -> None:
    # 키가 섞이면 구독이 아니라 종량제로 과금된다 — 서버 프로세스에서 지운다
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        os.environ.pop(key, None)


def summarize(name: str, data: dict[str, Any]) -> str:
    """도구 사용 줄에 보일 한 줄."""
    if name == ASK_TOOL and isinstance(data.get("questions"), list) and data["questions"]:
        first = data["questions"][0]
        if isinstance(first, dict):
            more = len(data["questions"]) - 1
            return str(first.get("question", ""))[:300] + (f" 외 {more}개" if more else "")
    for key in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query", "description", "prompt"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:300]
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:300]
    return ""


def _result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:OUTPUT_MAX]
    parts = []
    for item in content if isinstance(content, list) else [content]:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        elif isinstance(item, dict):
            parts.append(f"[{item.get('type', '?')}]")
    return "\n".join(parts)[:OUTPUT_MAX]


def _public_info(info: dict | None) -> dict:
    """화면에 내보낼 것만. **계정(이메일 등)은 빼고**."""
    info = info or {}
    return {
        "models": info.get("models") or [],
        "commands": [
            {"name": c.get("name"), "description": c.get("description", ""), "argumentHint": c.get("argumentHint", "")}
            for c in info.get("commands") or []
            if isinstance(c, dict) and c.get("name")
        ],
        "version": info.get("claude_code_version", ""),
    }


async def probe_info(cwd: str) -> dict:
    """모델 목록·슬래시 명령. 연결만 하고 메시지는 보내지 않는다(사용량 안 씀)."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    _scrub_env()
    path = cli_path()
    if not path:
        raise RuntimeError("Claude Code(claude)를 찾지 못했어요. 먼저 설치하고 로그인해 주세요.")
    options = ClaudeAgentOptions(cli_path=path, cwd=cwd, setting_sources=SETTING_SOURCES, permission_mode="default")
    async with ClaudeSDKClient(options=options) as client:
        return _public_info(await client.get_server_info())


async def probe_account(cwd: str) -> dict:
    """로그인했나 — 연결만 해서 Claude Code 가 알려 주는 계정 정보를 본다.

    자격 증명 파일을 읽지 않는다. **이메일은 돌려주지 않고** 구독 종류만 쓴다.
    (확인: 연결 직후 `get_server_info()["account"]` 에 subscriptionType · apiProvider 가
    온다 — 2026-11-23, Claude Code 2.1.318. 로그아웃 상태의 모양은 재 보지 않았다.)
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    _scrub_env()
    path = cli_path()
    if not path:
        return {"installed": False, "loggedIn": False, "plan": ""}
    options = ClaudeAgentOptions(cli_path=path, cwd=cwd, setting_sources=[], permission_mode="default")
    async with ClaudeSDKClient(options=options) as client:
        info = await client.get_server_info() or {}
    account = info.get("account") if isinstance(info.get("account"), dict) else {}
    plan = str(account.get("subscriptionType") or account.get("apiProvider") or "")
    return {"installed": True, "loggedIn": bool(account.get("subscriptionType") or account.get("email")), "plan": plan}


class ClaudeBackend(AgentBackend):
    kind = "claude"

    def __init__(self, config: SessionConfig, emit, ask) -> None:
        super().__init__(config, emit, ask)
        self._client = None
        self._reader: asyncio.Task | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._stderr: list[str] = []
        self.info: dict = {}
        #: 할 일 — Claude Code 2.1.x 는 TaskCreate/TaskUpdate 로 관리한다(실행 파일의
        #: 스키마로 확인: subject · status pending/in_progress/completed/deleted)
        self._tasks: dict[str, dict] = {}
        self._creating: dict[str, str] = {}  # tool_use_id → subject

    # --- 연결 --------------------------------------------------------------

    def _options(self):
        import warnings

        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import CanUseToolShadowedWarning

        # TodoWrite 를 허용 목록에 넣어서 나는 경고 — 일부러 그렇게 했다
        warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

        cfg = self.config
        mode = MODE_MAP.get(cfg.mode, "default")
        return ClaudeAgentOptions(
            # PDF · 이미지를 읽으면 메시지 하나가 SDK 기본 상한(1MB)을 넘어요 (실측 2026-11-24)
            max_buffer_size=32 * 1024 * 1024,
            cli_path=cli_path(),
            cwd=cfg.cwd,
            setting_sources=SETTING_SOURCES,
            permission_mode=mode,
            model=cfg.model or None,
            effort=cfg.effort if cfg.effort in EFFORTS else None,
            resume=self.agent_session_id or None,
            can_use_tool=self._can_use_tool,
            allowed_tools=list(ALLOWED),
            disallowed_tools=list(DISALLOWED),
            settings=json.dumps({"ultracode": True}) if cfg.extra.get("ultracode") else None,
            stderr=self._on_stderr,
        )

    def _on_stderr(self, line: str) -> None:
        self._stderr = (self._stderr + [line])[-20:]

    async def connect(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient

        if not cli_path():
            raise RuntimeError("Claude Code(claude)를 찾지 못했어요. 먼저 설치하고 로그인해 주세요.")
        _scrub_env()
        self._client = ClaudeSDKClient(options=self._options())
        await self._client.connect()
        self.info = _public_info(await self._client.get_server_info())
        self._reader = asyncio.create_task(self._read(), name="agent-reader")

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._idle.set()

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    # --- 보내기 ------------------------------------------------------------

    async def send(self, text: str) -> None:
        if not self._client:
            raise RuntimeError("에이전트에 연결돼 있지 않아요.")
        self._idle.clear()
        try:
            await self._client.query(text)
        except Exception:
            self._idle.set()
            raise

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def interrupt(self) -> None:
        if self._client:
            await self._client.interrupt()

    async def set_mode(self, mode: str) -> None:
        self.config.mode = mode
        if self._client:
            await self._client.set_permission_mode(MODE_MAP.get(mode, "default"))

    async def set_model(self, model: str) -> None:
        self.config.model = model
        if self._client:
            await self._client.set_model(model or None)

    # --- 권한 --------------------------------------------------------------

    async def _can_use_tool(self, tool_name: str, tool_input: dict, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        request = ApprovalRequest(
            tool=tool_name,
            input=dict(tool_input or {}),
            title=getattr(context, "title", None) or "",
            reason=getattr(context, "decision_reason", None) or "",
            path=getattr(context, "blocked_path", None) or "",
            tool_use_id=getattr(context, "tool_use_id", None) or "",
            agent_id=getattr(context, "agent_id", None) or "",
        )
        decision = await self.ask(request)
        if decision.allow:
            return PermissionResultAllow(updated_input=decision.updated_input)
        return PermissionResultDeny(message=decision.message or "사람이 거부했어요.", interrupt=decision.interrupt)

    # --- 할 일 ------------------------------------------------------------

    def _emit_tasks(self) -> None:
        self.emit({"type": "todos", "items": [dict(t) for t in self._tasks.values()]})

    def _track_task_call(self, tool_id: str, name: str, data: dict) -> None:
        if name == "TaskCreate":
            self._creating[tool_id] = str(data.get("subject") or data.get("description") or "")
        elif name == "TaskUpdate":
            tid = str(data.get("taskId") or "")
            task = self._tasks.get(tid)
            if not task:
                return
            status = data.get("status")
            if status == "deleted":
                self._tasks.pop(tid, None)
            else:
                if isinstance(status, str):
                    task["status"] = status
                if isinstance(data.get("subject"), str):
                    task["content"] = data["subject"]
            self._emit_tasks()

    def _track_task_result(self, tool_id: str, result: Any, text: str) -> None:
        subject = self._creating.pop(tool_id, None)
        if subject is None:
            return
        tid = _task_id_from(result, text) or str(len(self._tasks) + 1)
        self._tasks[tid] = {"content": subject, "status": "pending"}
        self._emit_tasks()

    # --- 받기 --------------------------------------------------------------

    async def _read(self) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )
        from claude_agent_sdk.types import TaskNotificationMessage, TaskStartedMessage

        try:
            async for msg in self._client.receive_messages():
                if isinstance(msg, TaskStartedMessage):
                    self.emit({"type": "subagent", "taskId": msg.task_id, "description": msg.description, "status": "running", "toolId": msg.tool_use_id})
                elif isinstance(msg, TaskNotificationMessage):
                    self.emit({"type": "subagent", "taskId": msg.task_id, "description": msg.summary, "status": str(msg.status), "toolId": msg.tool_use_id})
                elif isinstance(msg, SystemMessage):
                    if msg.subtype == "init" and isinstance(msg.data, dict) and msg.data.get("session_id"):
                        self.agent_session_id = msg.data["session_id"]
                elif isinstance(msg, AssistantMessage):
                    parent = msg.parent_tool_use_id
                    if msg.error:
                        self.emit({"type": "system", "text": f"에이전트 오류: {msg.error}"})
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            self.emit({"type": "text", "text": block.text, "parent": parent})
                        elif isinstance(block, ToolUseBlock):
                            data = dict(block.input or {})
                            self.emit({"type": "tool", "toolId": block.id, "name": block.name, "summary": summarize(block.name, data), "input": _trim_input(data), "parent": parent})
                            self._track_task_call(block.id, block.name, data)
                            if block.name == "TodoWrite" and isinstance(data.get("todos"), list):
                                self.emit({"type": "todos", "items": [
                                    {"content": str(t.get("content", "")), "status": str(t.get("status", ""))}
                                    for t in data["todos"] if isinstance(t, dict)
                                ]})
                elif isinstance(msg, UserMessage):
                    if isinstance(msg.content, list):
                        for block in msg.content:
                            if isinstance(block, ToolResultBlock):
                                self.emit({"type": "tool_result", "toolId": block.tool_use_id, "ok": not block.is_error, "output": _result_text(block.content)})
                                self._track_task_result(block.tool_use_id, msg.tool_use_result, _result_text(block.content))
                elif isinstance(msg, ResultMessage):
                    if msg.session_id:
                        self.agent_session_id = msg.session_id
                    self.emit({
                        "type": "result",
                        "ok": not msg.is_error,
                        "durationMs": msg.duration_ms,
                        "turns": msg.num_turns,
                        "costUsd": msg.total_cost_usd,
                        "usage": _usage(msg.usage),
                        "error": "; ".join(msg.errors or []) if msg.is_error else "",
                    })
                    self._idle.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 프로세스가 죽었거나 끊겼다
            tail = " / ".join(self._stderr[-3:])
            self.emit({"type": "system", "text": f"에이전트 연결이 끊겼어요: {type(exc).__name__}{f' · {tail}' if tail else ''}"})
            self._client = None
        finally:
            self._idle.set()


def _task_id_from(result: Any, text: str) -> str:
    if isinstance(result, dict):
        task = result.get("task")
        if isinstance(task, dict) and task.get("id") is not None:
            return str(task["id"])
    import re

    m = re.search(r"#(\d+)", text or "")
    return m.group(1) if m else ""


def _trim_input(data: dict) -> dict:
    """승인 카드·도구 줄에 쓸 입력. 너무 긴 글은 자른다."""
    out = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 20000:
            out[k] = v[:20000] + "\n… (잘렸어요)"
        else:
            out[k] = v
    return out


def _usage(usage: dict | None) -> dict | None:
    if not isinstance(usage, dict):
        return None
    keep = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {k: usage[k] for k in keep if isinstance(usage.get(k), int)}
