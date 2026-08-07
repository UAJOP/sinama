from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentMode(StrEnum):
    HEALTHY = "healthy"
    BROKEN_PREMATURE_SUBMISSION = "broken_premature_submission"


class AgentTarget(StrEnum):
    BUILT_IN_DEMO = "built_in_demo"
    EXTERNAL_HTTP = "external_http"


class ConversationPhase(StrEnum):
    AWAITING_INTENT = "awaiting_intent"
    AWAITING_POLICY = "awaiting_policy"
    AWAITING_CLAIM_DETAILS = "awaiting_claim_details"
    AWAITING_DAMAGE_PHOTO = "awaiting_damage_photo"
    SUBMITTED = "submitted"
    HANDED_OFF = "handed_off"


class ToolName(StrEnum):
    LOOKUP_POLICY = "lookup_policy"
    COLLECT_CLAIM_DETAILS = "collect_claim_details"
    REQUEST_DOCUMENT = "request_document"
    SUBMIT_CLAIM = "submit_claim"
    HANDOFF_TO_HUMAN = "handoff_to_human"


JsonScalar = str | int | float | bool | None
NonEmptyMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
]


class ToolEvent(StrictModel):
    id: UUID
    tool: ToolName
    arguments: dict[str, JsonScalar]
    timestamp: datetime


class ConversationState(StrictModel):
    policy_number: str | None = None
    policy_lookup_occurred: bool = False
    damage_description: str | None = None
    damage_photo_exists: bool = False
    claim_submitted: bool = False
    phase: ConversationPhase = ConversationPhase.AWAITING_INTENT
    mode: AgentMode


class CreateConversationRequest(StrictModel):
    mode: AgentMode = AgentMode.HEALTHY


class ExecuteScenarioRequest(StrictModel):
    agent_mode: AgentMode = AgentMode.HEALTHY


class SendMessageRequest(StrictModel):
    message: NonEmptyMessage


class ConversationResponse(StrictModel):
    conversation_id: UUID
    mode: AgentMode
    assistant_message: str
    state: ConversationState
    new_events: list[ToolEvent]


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["sinama-api"] = "sinama-api"
    version: str = "0.1.0"
