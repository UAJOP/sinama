import asyncio
from typing import cast

from app.agent_adapters import (
    AgentSession,
    AgentTurnResult,
    BuiltInDemoAgentAdapter,
)
from app.evaluator import EvaluationCategory, EvaluationStatus
from app.models import AgentMode, ToolEvent, ToolName
from app.scenario_runner import (
    ExecutionErrorCategory,
    RunStatus,
    ScenarioRunner,
    ScenarioRunResult,
)
from app.scenarios import Scenario, load_scenario_by_id


def scenario_fixture(scenario_id: str) -> Scenario:
    return load_scenario_by_id(scenario_id)


def run_built_in(scenario_id: str, mode: AgentMode, label: str | None = None):
    adapter = BuiltInDemoAgentAdapter(mode=mode, configuration_label=label)
    return asyncio.run(ScenarioRunner().run(scenario_fixture(scenario_id), adapter))


class StaticAdapter:
    def __init__(self, label: str, turns: list[AgentTurnResult]) -> None:
        self.label = label
        self._turns = iter(turns)

    async def start_session(self) -> AgentSession:
        return AgentSession(session_id="static-session")

    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        return next(self._turns)


class SlowAdapter(StaticAdapter):
    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        await asyncio.sleep(0.05)
        return await super().send_message(session, message)


class MalformedAdapter(StaticAdapter):
    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        return cast(AgentTurnResult, {"assistant_message": "invalid"})


class ExplodingAdapter(StaticAdapter):
    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        raise RuntimeError("private upstream failure details")


def test_ins_001_healthy_passes_with_ordered_transcript_and_tool_trace() -> None:
    result = run_built_in("INS-001", AgentMode.HEALTHY)
    scenario = scenario_fixture("INS-001")

    assert result.status is RunStatus.PASS
    assert result.severity is None
    assert result.turns_executed == 3
    assert [turn.sequence for turn in result.transcript] == list(range(1, 7))
    assert [turn.role.value for turn in result.transcript] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [event.tool for event in result.tool_trace] == [
        ToolName.LOOKUP_POLICY,
        ToolName.COLLECT_CLAIM_DETAILS,
        ToolName.REQUEST_DOCUMENT,
    ]
    assert all(isinstance(event, ToolEvent) for event in result.tool_trace)
    assert result.declared_checks == scenario.deterministic_checks
    assert result.unscored_declared_checks == scenario.deterministic_checks


def test_ins_001_broken_fails_high_from_observed_behavior() -> None:
    result = run_built_in("INS-001", AgentMode.BROKEN_PREMATURE_SUBMISSION)

    assert result.status is RunStatus.FAIL
    assert result.severity is not None and result.severity.value == "high"
    failed_checks = [check for check in result.checks if check.status is EvaluationStatus.FAIL]
    assert [check.check_id for check in failed_checks] == [
        "required_tool:2:request_document",
        "forbidden_tool:1:submit_claim",
    ]
    forbidden = next(
        check
        for check in result.checks
        if check.category is EvaluationCategory.TOOL_CALL_POLICY_VIOLATION
    )
    assert forbidden.status is EvaluationStatus.FAIL
    assert forbidden.evidence.offending_event is not None
    assert forbidden.evidence.offending_event.arguments["status"] == "premature"
    assert forbidden.evidence.offending_event.arguments["missing_requirement"] == "damage_photo"


def test_ins_004_healthy_handoff_passes() -> None:
    result = run_built_in("INS-004", AgentMode.HEALTHY)

    assert result.status is RunStatus.PASS
    assert [event.tool for event in result.tool_trace] == [ToolName.HANDOFF_TO_HUMAN]
    assert result.tool_trace[0].arguments["reason"] == "customer_request"


def test_max_turn_guard_stops_after_limit_and_preserves_evidence() -> None:
    scenario = scenario_fixture("INS-001").model_copy(update={"max_turns": 1})
    result = asyncio.run(
        ScenarioRunner().run(scenario, BuiltInDemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.MAX_TURNS_EXCEEDED
    assert result.turns_executed == 1
    assert len(result.transcript) == 2


def test_turn_timeout_returns_safe_error_and_preserves_transcript() -> None:
    scenario = scenario_fixture("INS-004")
    adapter = SlowAdapter(
        "slow-agent",
        [AgentTurnResult(assistant_message="late", tool_events=[])],
    )
    result = asyncio.run(
        ScenarioRunner().run(scenario, adapter, turn_timeout_seconds=0.001)
    )

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.AGENT_TIMEOUT
    assert result.error.reason == "Agent turn exceeded the configured timeout."
    assert [turn.role.value for turn in result.transcript] == ["user"]
    assert result.turns_executed == 0


def test_malformed_adapter_response_returns_typed_error() -> None:
    scenario = scenario_fixture("INS-004")
    result = asyncio.run(ScenarioRunner().run(scenario, MalformedAdapter("bad", [])))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.MALFORMED_AGENT_RESPONSE
    assert result.error.reason == "Agent adapter returned a malformed turn response."


def test_unexpected_adapter_exception_does_not_expose_internal_details() -> None:
    scenario = scenario_fixture("INS-004")
    result = asyncio.run(ScenarioRunner().run(scenario, ExplodingAdapter("bad", [])))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.ADAPTER_ERROR
    assert "private upstream" not in result.error.reason


def test_missing_scenario_returns_typed_execution_error() -> None:
    result = asyncio.run(
        ScenarioRunner().run(None, StaticAdapter("any-agent", []))
    )

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.MISSING_SCENARIO


def test_evaluator_fails_illegal_trace_even_when_agent_label_says_healthy() -> None:
    broken_behavior = run_built_in(
        "INS-001",
        AgentMode.BROKEN_PREMATURE_SUBMISSION,
        label="healthy",
    )

    assert broken_behavior.agent_label == "healthy"
    assert broken_behavior.status is RunStatus.FAIL


def test_compliant_trace_passes_with_arbitrary_agent_label() -> None:
    compliant_behavior = run_built_in(
        "INS-001",
        AgentMode.HEALTHY,
        label="production-v37",
    )

    assert compliant_behavior.agent_label == "production-v37"
    assert compliant_behavior.status is RunStatus.PASS


def test_repeated_runs_have_identical_normalized_evaluation() -> None:
    first = run_built_in("INS-001", AgentMode.BROKEN_PREMATURE_SUBMISSION)
    second = run_built_in("INS-001", AgentMode.BROKEN_PREMATURE_SUBMISSION)

    def normalize(result: ScenarioRunResult) -> tuple[object, ...]:
        return (
            result.status,
            result.severity,
            tuple(
                (check.check_id, check.status, check.reason, check.severity)
                for check in result.checks
            ),
            tuple(result.declared_checks),
            tuple(result.unscored_declared_checks),
        )

    assert normalize(first) == normalize(second)
