import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent_adapters import DemoAgentAdapter
from app.config import get_settings
from app.demo_agent import ConversationNotFoundError, demo_agent_service
from app.http_agent import (
    ConnectionTestResult,
    ExternalAgentConfiguration,
    build_http_agent_adapter,
    test_http_agent_connection,
)
from app.models import (
    ConversationResponse,
    CreateConversationRequest,
    ExecuteScenarioRequest,
    HealthResponse,
    SendMessageRequest,
)
from app.regression import RegressionComparisonResponse
from app.scenario_packs import (
    ScenarioPackNotFoundError,
    ScenarioPackSummary,
    scenario_pack_registry,
)
from app.scenario_runner import ScenarioRunResult, scenario_runner
from app.scenarios import ScenarioNotFoundError, load_scenario_by_id
from app.test_runs import (
    CreateTestRunRequest,
    InvalidRunAgentConfigurationError,
    RunNotCompletedError,
    ScenarioResultNotFoundError,
    TestRunNotFoundError,
    TestRunResultsResponse,
    TestRunSummary,
    run_service,
    run_store,
)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # A persisted queued/running run cannot resume without a durable worker
    # queue, so retire anything a previous process left mid-flight instead of
    # leaving permanently "running" zombie records behind.
    recovered = await asyncio.to_thread(run_store.recover_interrupted_runs)
    if recovered:
        logger.warning("Marked %s interrupted test run(s) as errored after restart.", recovered)
    yield


app = FastAPI(
    title="SINAMA API",
    description=(
        "Local API for the built-in Demo Insurance Agent and deterministic scenario runner."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    safe_errors = [
        {key: value for key, value in item.items() if key not in {"ctx", "input"}}
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
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

    adapter = DemoAgentAdapter(mode=request.agent_mode)
    return await scenario_runner.run(scenario, adapter)


@app.post(
    "/api/agents/external/test-connection",
    response_model=ConnectionTestResult,
    tags=["agents"],
)
async def test_external_agent_connection(
    request: ExternalAgentConfiguration,
) -> ConnectionTestResult:
    adapter = build_http_agent_adapter(request)
    return await test_http_agent_connection(adapter)


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
        return await run_service.create_run(
            request.pack_id,
            request.agent_mode,
            agent_target=request.agent_target,
            external_agent=request.external_agent,
        )
    except ScenarioPackNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scenario pack not found") from error
    except InvalidRunAgentConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get(
    "/api/runs",
    response_model=list[TestRunSummary],
    tags=["test-runs"],
)
def list_test_runs(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TestRunSummary]:
    """Recent run history, newest first.

    Bounded by design: this is the "reopen a recent run" surface, not an archive
    browser. Older runs remain persisted and reachable by id.
    """

    return run_store.list_runs(limit)


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


@app.post(
    "/api/runs/{run_id}/baseline",
    response_model=TestRunSummary,
    tags=["test-runs"],
)
def set_test_run_baseline(run_id: UUID) -> TestRunSummary:
    try:
        return run_store.set_baseline(run_id)
    except TestRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Test run not found") from error
    except RunNotCompletedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/runs/{run_id}/comparison",
    response_model=RegressionComparisonResponse,
    tags=["test-runs"],
)
def get_test_run_comparison(run_id: UUID) -> RegressionComparisonResponse:
    try:
        return run_store.get_comparison(run_id)
    except TestRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Test run not found") from error
