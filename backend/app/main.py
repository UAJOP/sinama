from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.agent_adapters import BuiltInDemoAgentAdapter
from app.config import get_settings
from app.demo_agent import ConversationNotFoundError, demo_agent_service
from app.models import (
    ConversationResponse,
    CreateConversationRequest,
    ExecuteScenarioRequest,
    HealthResponse,
    SendMessageRequest,
)
from app.scenario_runner import ScenarioRunResult, scenario_runner
from app.scenarios import ScenarioNotFoundError, load_scenario_by_id

settings = get_settings()
app = FastAPI(
    title="SINAMA API",
    description=(
        "Local API for the built-in Demo Insurance Agent and deterministic scenario runner."
    ),
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.post(
    "/api/demo-agent/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["demo-agent"],
)
def create_conversation(request: CreateConversationRequest) -> ConversationResponse:
    return demo_agent_service.create_conversation(request.mode)


@app.post(
    "/api/demo-agent/conversations/{conversation_id}/messages",
    response_model=ConversationResponse,
    tags=["demo-agent"],
)
def send_message(
    conversation_id: UUID,
    request: SendMessageRequest,
) -> ConversationResponse:
    try:
        return demo_agent_service.send_message(conversation_id, request.message)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error


@app.post(
    "/api/demo-agent/conversations/{conversation_id}/reset",
    response_model=ConversationResponse,
    tags=["demo-agent"],
)
def reset_conversation(conversation_id: UUID) -> ConversationResponse:
    try:
        return demo_agent_service.reset_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error


@app.post(
    "/api/scenarios/{scenario_id}/execute",
    response_model=ScenarioRunResult,
    tags=["scenarios"],
)
async def execute_scenario(
    scenario_id: str,
    request: ExecuteScenarioRequest,
) -> ScenarioRunResult:
    try:
        scenario = load_scenario_by_id(scenario_id)
    except ScenarioNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scenario not found") from error

    adapter = BuiltInDemoAgentAdapter(mode=request.agent_mode)
    return await scenario_runner.run(scenario, adapter)
