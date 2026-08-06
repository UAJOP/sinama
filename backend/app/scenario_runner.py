import asyncio
import logging
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.agent_adapters import (
    AgentAdapter,
    AgentSession,
    AgentTurnResult,
    MalformedAgentResponseError,
)
from app.evaluator import (
    DeterministicToolEvaluator,
    EvaluationCheckResult,
    EvaluationStatus,
    ScenarioEvaluator,
)
from app.models import StrictModel, ToolEvent
from app.scenarios import Scenario, Severity

logger = logging.getLogger(__name__)


class TranscriptRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TranscriptTurn(StrictModel):
    sequence: int = Field(ge=1)
    role: TranscriptRole
    content: str


class RunStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class ExecutionErrorCategory(StrEnum):
    MISSING_SCENARIO = "missing_scenario"
    AGENT_TIMEOUT = "agent_timeout"
    MALFORMED_AGENT_RESPONSE = "malformed_agent_response"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    ADAPTER_ERROR = "adapter_error"


class ScenarioExecutionError(StrictModel):
    category: ExecutionErrorCategory
    reason: str


class ScenarioRunResult(StrictModel):
    scenario_id: str
    scenario_version: str
    agent_label: str
    status: RunStatus
    severity: Severity | None = None
    evaluation_scope: Literal["deterministic_tool_contract"] = "deterministic_tool_contract"
    checks: list[EvaluationCheckResult] = Field(default_factory=list)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    tool_trace: list[ToolEvent] = Field(default_factory=list)
    turns_executed: int = Field(ge=0)
    unscored_expectations: list[str] = Field(default_factory=list)
    error: ScenarioExecutionError | None = None


class ScenarioRunner:
    def __init__(self, evaluator: ScenarioEvaluator | None = None) -> None:
        self._evaluator = evaluator or DeterministicToolEvaluator()

    async def run(
        self,
        scenario: Scenario | None,
        adapter: AgentAdapter,
        *,
        turn_timeout_seconds: float = 5.0,
    ) -> ScenarioRunResult:
        if scenario is None:
            return self._error_result(
                scenario=None,
                adapter_label=adapter.label,
                transcript=[],
                tool_trace=[],
                turns_executed=0,
                category=ExecutionErrorCategory.MISSING_SCENARIO,
                reason="Scenario was not found.",
            )

        transcript: list[TranscriptTurn] = []
        tool_trace: list[ToolEvent] = []
        turns_executed = 0

        try:
            session = await asyncio.wait_for(
                adapter.start_session(), timeout=turn_timeout_seconds
            )
            if not isinstance(session, AgentSession):
                raise MalformedAgentResponseError("Adapter returned an invalid session.")
        except TimeoutError:
            return self._error_result(
                scenario,
                adapter.label,
                transcript,
                tool_trace,
                turns_executed,
                ExecutionErrorCategory.AGENT_TIMEOUT,
                "Agent session creation exceeded the configured timeout.",
            )
        except MalformedAgentResponseError:
            return self._error_result(
                scenario,
                adapter.label,
                transcript,
                tool_trace,
                turns_executed,
                ExecutionErrorCategory.MALFORMED_AGENT_RESPONSE,
                "Agent adapter returned a malformed session response.",
            )
        except Exception:
            logger.exception("Unexpected adapter error while starting scenario %s", scenario.id)
            return self._error_result(
                scenario,
                adapter.label,
                transcript,
                tool_trace,
                turns_executed,
                ExecutionErrorCategory.ADAPTER_ERROR,
                "Agent adapter failed while creating a session.",
            )

        for message in scenario.scripted_user_turns:
            if turns_executed >= scenario.max_turns:
                return self._error_result(
                    scenario,
                    adapter.label,
                    transcript,
                    tool_trace,
                    turns_executed,
                    ExecutionErrorCategory.MAX_TURNS_EXCEEDED,
                    f"Scenario exceeded its maximum of {scenario.max_turns} agent turns.",
                )

            transcript.append(
                TranscriptTurn(
                    sequence=len(transcript) + 1,
                    role=TranscriptRole.USER,
                    content=message,
                )
            )
            try:
                turn = await asyncio.wait_for(
                    adapter.send_message(session, message),
                    timeout=turn_timeout_seconds,
                )
                if not isinstance(turn, AgentTurnResult):
                    raise MalformedAgentResponseError("Adapter returned an invalid turn.")
            except TimeoutError:
                return self._error_result(
                    scenario,
                    adapter.label,
                    transcript,
                    tool_trace,
                    turns_executed,
                    ExecutionErrorCategory.AGENT_TIMEOUT,
                    "Agent turn exceeded the configured timeout.",
                )
            except MalformedAgentResponseError:
                return self._error_result(
                    scenario,
                    adapter.label,
                    transcript,
                    tool_trace,
                    turns_executed,
                    ExecutionErrorCategory.MALFORMED_AGENT_RESPONSE,
                    "Agent adapter returned a malformed turn response.",
                )
            except Exception:
                logger.exception(
                    "Unexpected adapter error in scenario %s turn %s",
                    scenario.id,
                    turns_executed + 1,
                )
                return self._error_result(
                    scenario,
                    adapter.label,
                    transcript,
                    tool_trace,
                    turns_executed,
                    ExecutionErrorCategory.ADAPTER_ERROR,
                    "Agent adapter failed while processing a turn.",
                )

            turns_executed += 1
            transcript.append(
                TranscriptTurn(
                    sequence=len(transcript) + 1,
                    role=TranscriptRole.ASSISTANT,
                    content=turn.assistant_message,
                )
            )
            tool_trace.extend(turn.tool_events)

        report = self._evaluator.evaluate(scenario, tool_trace)
        return ScenarioRunResult(
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            agent_label=adapter.label,
            status=(
                RunStatus.FAIL
                if report.status is EvaluationStatus.FAIL
                else RunStatus.PASS
            ),
            severity=report.severity,
            checks=report.checks,
            transcript=transcript,
            tool_trace=tool_trace,
            turns_executed=turns_executed,
            unscored_expectations=report.unscored_expectations,
        )

    @staticmethod
    def _error_result(
        scenario: Scenario | None,
        adapter_label: str,
        transcript: list[TranscriptTurn],
        tool_trace: list[ToolEvent],
        turns_executed: int,
        category: ExecutionErrorCategory,
        reason: str,
    ) -> ScenarioRunResult:
        return ScenarioRunResult(
            scenario_id=scenario.id if scenario is not None else "unknown",
            scenario_version=scenario.version if scenario is not None else "unknown",
            agent_label=adapter_label,
            status=RunStatus.ERROR,
            transcript=transcript,
            tool_trace=tool_trace,
            turns_executed=turns_executed,
            error=ScenarioExecutionError(category=category, reason=reason),
        )


scenario_runner = ScenarioRunner()
