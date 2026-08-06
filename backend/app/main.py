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
from app.scenario_packs import (
    ScenarioPackNotFoundError,
    ScenarioPackSummary,
    scenario_pack_registry,
)
from app.scenario_runner import ScenarioRunResult, scenario_runner
from app.scenarios import ScenarioNotFoundError, load_scenario_by_id
from app.test_runs import (
    CreateTestRunRequest,
    ScenarioResultNotFoundError,
    TestRunNotFoundError,
    TestRunResultsResponse,
    TestRunSummary,
    run_service,
    run_store,
)

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


@app.get(
    "/api/scenario-packs",
    response_model=list[ScenarioPackSummary],
    tags=["test-runs"],
)
def list_scenario_packs() -> list[ScenarioPackSummary]:
    return scenario_pack_registry.list_packs()


@app.post(
    "/api/runs",
    response_model=TestRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["test-runs"],
)
async def create_test_run(request: CreateTestRunRequest) -> TestRunSummary:
    try:
        return await run_service.create_run(request.pack_id, request.agent_mode)
    except ScenarioPackNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scenario pack not found") from error


@app.get(
    "/api/runs/{run_id}",
    response_model=TestRunSummary,
    tags=["test-runs"],
)
def get_test_run(run_id: UUID) -> TestRunSummary:
    try:
        return run_store.get_run(run_id)
    except TestRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Test run not found") from error


@app.get(
    "/api/runs/{run_id}/results",
    response_model=TestRunResultsResponse,
    tags=["test-runs"],
)
def get_test_run_results(run_id: UUID) -> TestRunResultsResponse:
    try:
        return run_store.get_results(run_id)
    except TestRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Test run not found") from error


@app.get(
    "/api/runs/{run_id}/results/{scenario_id}",
    response_model=ScenarioRunResult,
    tags=["test-runs"],
)
def get_test_run_result(run_id: UUID, scenario_id: str) -> ScenarioRunResult:
    try:
        return run_store.get_result(run_id, scenario_id)
    except TestRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Test run not found") from error
    except ScenarioResultNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scenario result not found") from error
