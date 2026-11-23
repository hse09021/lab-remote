"""에이전트 공통 규칙 — Claude 전용 이름을 쓰지 않는다(나중에 Codex 를 붙일 수 있게).

연결 부품(`claude.py` 등)은 `AgentBackend` 를 구현하고, 무슨 일이 생길 때마다
`emit(event)` 로 **공통 모양의 이벤트**를 낸다. 화면과 저장은 이 모양만 안다.

이벤트 (`type` 별 칸):
- `user`       {text}
- `text`       {text, parent?}                 에이전트의 글
- `tool`       {toolId, name, summary, input, parent?}
- `tool_result`{toolId, ok, output}
- `todos`      {items: [{content, status}]}    할 일
- `subagent`   {taskId, description, status}   하위 에이전트
- `result`     {ok, durationMs, turns, costUsd?, usage?, error?}
- `approval`   {approvalId, state, ...}        승인 요청·결과 (manager 가 낸다)
- `system`     {text}                          연결·오류 등

승인: 도구를 쓰기 전 `ask(request) -> Decision` 을 부른다. manager 가 화면·
Inbox·Discord 에 올리고, 먼저 온 답을 돌려준다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

__all__ = [
    "MODES",
    "MODE_LABELS",
    "ApprovalRequest",
    "Decision",
    "AgentBackend",
    "Emit",
    "Ask",
]

#: 화면의 Mode — 에이전트가 실제로 받는 값은 연결 부품이 옮긴다.
#: bypass 계열은 두지 않는다(PLAN 1.2).
MODES = ("manual", "edit", "plan", "auto")
MODE_LABELS = {
    "manual": "Manual",
    "edit": "Edit automatically",
    "plan": "Plan",
    "auto": "Auto",
}


@dataclass
class ApprovalRequest:
    tool: str
    input: dict[str, Any]
    title: str = ""
    reason: str = ""
    path: str = ""
    tool_use_id: str = ""
    agent_id: str = ""


@dataclass
class Decision:
    allow: bool
    message: str = ""
    #: 허용할 때 입력을 바꿔 넘길 때(지금은 안 쓴다)
    updated_input: dict[str, Any] | None = None
    #: 거부하면서 세션을 멈출지
    interrupt: bool = False


Emit = Callable[[dict], None]
Ask = Callable[[ApprovalRequest], Awaitable[Decision]]


@dataclass
class SessionConfig:
    cwd: str
    mode: str = "manual"
    model: str = ""  # 빈 값 = 에이전트 기본값
    effort: str = ""  # 빈 값 = 기본값
    resume: str = ""  # 이어 갈 에이전트 쪽 세션 id
    extra: dict[str, Any] = field(default_factory=dict)


class AgentBackend(abc.ABC):
    """세션 하나와 연결된 에이전트 프로세스."""

    kind: str = ""

    def __init__(self, config: SessionConfig, emit: Emit, ask: Ask) -> None:
        self.config = config
        self.emit = emit
        self.ask = ask
        #: 에이전트 쪽 세션 id (이어 가기에 쓴다)
        self.agent_session_id: str = config.resume

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def send(self, text: str) -> None:
        """메시지를 보내고 바로 돌아온다. 응답은 `emit` 으로 흘러온다."""

    @abc.abstractmethod
    async def wait_idle(self) -> None:
        """지금 차례가 끝날 때까지."""

    @abc.abstractmethod
    async def interrupt(self) -> None: ...

    @abc.abstractmethod
    async def set_mode(self, mode: str) -> None: ...

    @abc.abstractmethod
    async def set_model(self, model: str) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def busy(self) -> bool: ...
