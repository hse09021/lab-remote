"""읽기 전용 에이전트 한 번 — 계획 모드 · 읽기 도구만 · 정해진 JSON으로 답하기.

라이브러리 질문 · 논문 요약 · 리더 설명이 같이 쓴다(Scenario와 같은 방식). 명령을 돌리거나
파일을 고치지 못한다. 사람이 눌렀을 때만 불린다.
"""

from __future__ import annotations

import json

__all__ = ["ReadOnlyError", "READ_TOOLS", "ask"]

READ_TOOLS = ["Read", "Glob", "Grep"]


class ReadOnlyError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 실패 사유."""


async def ask(cwd: str, prompt: str, schema: dict, *, model: str = "", max_turns: int = 30, query_fn=None) -> tuple[dict, str]:
    """`(답 JSON, 쓴 모델)`. 실패하면 ReadOnlyError."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny, ResultMessage

    from .claude import SETTING_SOURCES, _scrub_env, cli_path

    async def read_only(tool_name, _input, _ctx):
        if tool_name in READ_TOOLS:
            return PermissionResultAllow()
        return PermissionResultDeny(message="읽기만 해요.")

    _scrub_env()
    if not cli_path():
        raise ReadOnlyError("Claude Code(claude)를 찾지 못했어요.")
    options = ClaudeAgentOptions(
        # PDF · 이미지를 읽으면 메시지 하나가 SDK 기본 상한(1MB)을 넘어요 (실측 2026-11-24)
        max_buffer_size=32 * 1024 * 1024,
        cli_path=cli_path(),
        cwd=cwd,
        setting_sources=SETTING_SOURCES,
        permission_mode="plan",
        tools=list(READ_TOOLS),
        can_use_tool=read_only,
        model=model or None,
        max_turns=max_turns,
        output_format={"type": "json_schema", "schema": schema},
    )
    run = query_fn
    if run is None:
        from claude_agent_sdk import ClaudeSDKClient

        async def run(opts, text):
            async with ClaudeSDKClient(options=opts) as client:
                await client.query(text)
                async for msg in client.receive_response():
                    yield msg

    result = None
    used = ""
    async for msg in run(options, prompt):
        if isinstance(msg, AssistantMessage):
            used = msg.model or used
        elif isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise ReadOnlyError("답을 끝내지 못했어요: " + "; ".join((result.errors or []) if result else [])[:300])
    data = result.structured_output
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        raise ReadOnlyError("지정한 형식(JSON)으로 답을 받지 못했어요.")
    return data, used
