import asyncio
import logging
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.agent_adapters import (
    AgentAdapter,
    AgentRequestError,
    AgentSession,
    AgentTimeoutError,
    AgentTurnResult,
    MalformedAgentResponseError,
)
from app.config import get_settings
from app.evaluator import (
    DeterministicToolEvaluator,
    EvaluationCheckResult,
    EvaluationStatus,
    ScenarioEvaluator,
)
from app.failures import Failure, build_failures
from app.masking import mask_sensitive_text
from app.metrics import MetricScore, compute_metrics
from app.models import StrictModel, ToolEvent
from app.scenarios import Scenario, Severity
from app.semantic_judge import (
    SemanticEvaluationReport,
    SemanticJudge,
    SemanticJudgeRequest,
    SemanticTranscriptTurn,
    run_semantic_shadow,
)
from app.semantic_judge_factory import build_semantic_judge

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
    declared_checks: list[str] = Field(default_factory=list)
    unscored_declared_checks: list[str] = Field(default_factory=list)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    tool_trace: list[ToolEvent] = Field(default_factory=list)
    turns_executed: int = Field(ge=0)
    unscored_expectations: list[str] = Field(default_factory=list)
    metrics: list[MetricScore] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    # Additive field keeps historical persisted results valid while exposing
    # optional advisory semantic evidence on newly evaluated scenarios.
    semantic_evaluation: SemanticEvaluationReport | None = None
    error: ScenarioExecutionError | None = None


class ScenarioRunner:
    def __init__(
        self,
        evaluator: ScenarioEvaluator | None = None,
        *,
        semantic_judge: SemanticJudge | None = None,
        semantic_timeout_seconds: float = 8.0,
    ) -> None:
        self._evaluator = evaluator or DeterministicToolEvaluator()
        self._semantic_judge = semantic_judge
        self._semantic_timeout_seconds = semantic_timeout_seconds

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
        assistant_messages: list[str] = []
        event_turn: dict[UUID, int] = {}
        turns_executed = 0

        try:
            session = await asyncio.wait_for(
                adapter.start_session(), timeout=turn_timeout_seconds
            )
            if not isinstance(session, AgentSession):
                raise MalformedAgentResponseError("Adapter returned an invalid session.")
        except (TimeoutError, AgentTimeoutError):
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
        except AgentRequestError:
            return self._error_result(
                scenario,
                adapter.label,
                transcript,
                tool_trace,
                turns_executed,
                ExecutionErrorCategory.ADAPTER_ERROR,
                "Agent adapter failed while creating a session.",
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
            except (TimeoutError, AgentTimeoutError):
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
            except AgentRequestError:
                return self._error_result(
                    scenario,
                    adapter.label,
                    transcript,
                    tool_trace,
                    turns_executed,
                    ExecutionErrorCategory.ADAPTER_ERROR,
                    "Agent adapter failed while processing a turn.",
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
            assistant_messages.append(turn.assistant_message)
            for event in turn.tool_events:
                event_turn[event.id] = turns_executed
            tool_trace.extend(turn.tool_events)

        report = self._evaluator.evaluate(scenario, tool_trace, assistant_messages)
        metrics = compute_metrics(report.checks)
        failures = build_failures(report.checks, event_turn)

        masked_transcript = [
            turn.model_copy(update={"content": mask_sensitive_text(turn.content)})
            for turn in transcript
        ]
        masked_tool_trace = [self._mask_tool_event(event) for event in tool_trace]
        masked_by_id = {event.id: event for event in masked_tool_trace}
        masked_checks = [self._mask_check(check, masked_by_id) for check in report.checks]
        semantic_evaluation = await self._semantic_evaluation(scenario, masked_transcript)

        # Semantic evaluation is intentionally computed only after all deterministic
        # status/severity/metrics/failures have been finalized. Its verdict cannot
        # alter the authoritative deterministic result in shadow mode.
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
            checks=masked_checks,
            declared_checks=report.declared_checks,
            unscored_declared_checks=report.unscored_declared_checks,
            metrics=metrics,
            failures=failures,
            transcript=masked_transcript,
            tool_trace=masked_tool_trace,
            turns_executed=turns_executed,
            unscored_expectations=report.unscored_expectations,
            semantic_evaluation=semantic_evaluation,
        )

    async def _semantic_evaluation(
        self,
        scenario: Scenario,
        masked_transcript: list[TranscriptTurn],
    ) -> SemanticEvaluationReport | None:
        if not scenario.semantic_expectations:
            return None
        if self._semantic_judge is None:
            return SemanticEvaluationReport.disabled()

        request = SemanticJudgeRequest(
            scenario_id=scenario.id,
            scenario_title=scenario.title,
            initial_user_goal=mask_sensitive_text(scenario.initial_user_goal),
            expectations=scenario.semantic_expectations,
            transcript=[
                SemanticTranscriptTurn(
                    sequence=turn.sequence,
                    role=turn.role.value,
                    content=turn.content,
                )
                for turn in masked_transcript
            ],
        )
        return await run_semantic_shadow(
            self._semantic_judge,
            request,
            timeout_seconds=self._semantic_timeout_seconds,
        )

    @staticmethod
    def _mask_tool_event(event: ToolEvent) -> ToolEvent:
        masked_arguments = {
            key: mask_sensitive_text(value) if isinstance(value, str) else value
            for key, value in event.arguments.items()
        }
        return event.model_copy(update={"arguments": masked_arguments})

    @staticmethod
    def _mask_check(
        check: EvaluationCheckResult,
        masked_by_id: dict[UUID, ToolEvent],
    ) -> EvaluationCheckResult:
        evidence = check.evidence
        matching = (
            masked_by_id.get(evidence.matching_event.id) if evidence.matching_event else None
        )
        offending = (
            masked_by_id.get(evidence.offending_event.id) if evidence.offending_event else None
        )
        return check.model_copy(
            update={
                "evidence": evidence.model_copy(
                    update={"matching_event": matching, "offending_event": offending}
                )
            }
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
            declared_checks=(
                list(scenario.deterministic_checks) if scenario is not None else []
            ),
            unscored_declared_checks=(
                list(scenario.deterministic_checks) if scenario is not None else []
            ),
            unscored_expectations=(
                [
                    *scenario.expected_outcomes,
                    *scenario.forbidden_behaviors,
                    *scenario.expected_behaviors,
                ]
                if scenario is not None
                else []
            ),
            error=ScenarioExecutionError(category=category, reason=reason),
        )


_runtime_settings = get_settings()
scenario_runner = ScenarioRunner(
    semantic_judge=build_semantic_judge(_runtime_settings),
    semantic_timeout_seconds=_runtime_settings.semantic_judge_timeout_seconds,
)
