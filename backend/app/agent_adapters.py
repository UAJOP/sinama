from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import Field

from app.demo_agent import DemoAgentService, demo_agent_service
from app.models import AgentMode, JsonScalar, StrictModel, ToolEvent


class AgentSession(StrictModel):
    session_id: str = Field(min_length=1)


class AgentTurnResult(StrictModel):
    assistant_message: str = Field(min_length=1, max_length=2_000)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    state_metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class MalformedAgentResponseError(RuntimeError):
    """Raised by adapters that cannot normalize an agent response safely."""


class AgentAdapter(Protocol):
    @property
    def label(self) -> str: ...

    async def start_session(self) -> AgentSession: ...

    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult: ...


@dataclass
class BuiltInDemoAgentAdapter:
    """Async adapter around the local deterministic Demo Insurance Agent."""

    mode: AgentMode
    service: DemoAgentService = demo_agent_service
    configuration_label: str | None = None

    @property
    def label(self) -> str:
        return self.configuration_label or self.mode.value

    async def start_session(self) -> AgentSession:
        response = self.service.create_conversation(self.mode)
        return AgentSession(session_id=str(response.conversation_id))

    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        response = self.service.send_message(UUID(session.session_id), message)
        return AgentTurnResult(
            assistant_message=response.assistant_message,
            tool_events=response.new_events,
            state_metadata=response.state.model_dump(mode="json"),
        )
