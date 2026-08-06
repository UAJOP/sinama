from collections import defaultdict
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field

from app.models import JsonScalar, StrictModel, ToolEvent, ToolName
from app.scenarios import Scenario, Severity


class EvaluationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class EvaluationCheckType(StrEnum):
    REQUIRED_TOOL_CALL = "required_tool_call"
    TOOL_ARGUMENT_CONSTRAINT = "tool_argument_constraint"
    FORBIDDEN_TOOL_CALL = "forbidden_tool_call"


class EvaluationCategory(StrEnum):
    REQUIRED_TOOL_MISSING = "required_tool_missing"
    TOOL_ARGUMENT_MISMATCH = "tool_argument_mismatch"
    TOOL_CALL_POLICY_VIOLATION = "tool_call_policy_violation"


class EvaluationEvidence(StrictModel):
    expected_tool: ToolName | None = None
    argument_name: str | None = None
    expected_value: JsonScalar = None
    actual_values: list[JsonScalar] = Field(default_factory=list)
    matching_event: ToolEvent | None = None
    offending_event: ToolEvent | None = None
    condition: str | None = None


class EvaluationCheckResult(StrictModel):
    check_id: str
    type: EvaluationCheckType
    status: EvaluationStatus
    category: EvaluationCategory | None = None
    severity: Severity | None = None
    reason: str
    evidence: EvaluationEvidence


class EvaluationReport(StrictModel):
    status: EvaluationStatus
    severity: Severity | None = None
    evaluation_scope: Literal["deterministic_tool_contract"] = "deterministic_tool_contract"
    checks: list[EvaluationCheckResult]
    declared_checks: list[str]
    unscored_declared_checks: list[str]
    unscored_expectations: list[str]


class ScenarioEvaluator(Protocol):
    def evaluate(self, scenario: Scenario, tool_trace: list[ToolEvent]) -> EvaluationReport: ...


class DeterministicToolEvaluator:
    """Evaluate only structured fixture contracts against observed tool events."""

    def evaluate(self, scenario: Scenario, tool_trace: list[ToolEvent]) -> EvaluationReport:
        events_by_tool: dict[ToolName, list[ToolEvent]] = defaultdict(list)
        for event in tool_trace:
            events_by_tool[event.tool].append(event)

        checks: list[EvaluationCheckResult] = []
        for index, expected in enumerate(scenario.expected_tool_calls, start=1):
            events = events_by_tool[expected.name]
            if expected.required:
                checks.append(
                    self._required_tool_check(
                        expected.name,
                        events,
                        scenario.severity_if_failed,
                        index,
                    )
                )

            if not events:
                continue

            for argument_name, expected_value in sorted(expected.constraints.items()):
                checks.append(
                    self._argument_check(
                        expected.name,
                        argument_name,
                        expected_value,
                        events,
                        scenario.severity_if_failed,
                        index,
                    )
                )

        for index, forbidden in enumerate(scenario.forbidden_tool_calls, start=1):
            checks.append(
                self._forbidden_tool_check(
                    scenario,
                    forbidden.name,
                    forbidden.condition,
                    events_by_tool[forbidden.name],
                    index,
                )
            )

        failed = any(check.status is EvaluationStatus.FAIL for check in checks)
        return EvaluationReport(
            status=EvaluationStatus.FAIL if failed else EvaluationStatus.PASS,
            severity=scenario.severity_if_failed if failed else None,
            checks=checks,
            # These fixture IDs are descriptive metadata, not executable configuration.
            # Do not infer coverage from their names; structured contracts drive scoring.
            declared_checks=list(scenario.deterministic_checks),
            unscored_declared_checks=list(scenario.deterministic_checks),
            unscored_expectations=[*scenario.expected_outcomes, *scenario.forbidden_behaviors],
        )

    @staticmethod
    def _required_tool_check(
        tool: ToolName,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        if events:
            return EvaluationCheckResult(
                check_id=f"required_tool:{index}:{tool.value}",
                type=EvaluationCheckType.REQUIRED_TOOL_CALL,
                status=EvaluationStatus.PASS,
                reason=f"Required tool {tool.value} was called.",
                evidence=EvaluationEvidence(expected_tool=tool, matching_event=events[0]),
            )
        return EvaluationCheckResult(
            check_id=f"required_tool:{index}:{tool.value}",
            type=EvaluationCheckType.REQUIRED_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.REQUIRED_TOOL_MISSING,
            severity=failure_severity,
            reason=f"Required tool {tool.value} was not called.",
            evidence=EvaluationEvidence(expected_tool=tool),
        )

    @staticmethod
    def _argument_check(
        tool: ToolName,
        argument_name: str,
        expected_value: JsonScalar,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        matching_event = next(
            (
                event
                for event in events
                if argument_name in event.arguments
                and event.arguments[argument_name] == expected_value
            ),
            None,
        )
        evidence = EvaluationEvidence(
            expected_tool=tool,
            argument_name=argument_name,
            expected_value=expected_value,
            actual_values=[event.arguments.get(argument_name) for event in events],
            matching_event=matching_event,
        )
        if matching_event is not None:
            return EvaluationCheckResult(
                check_id=f"tool_argument:{index}:{tool.value}:{argument_name}",
                type=EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
                status=EvaluationStatus.PASS,
                reason=(
                    f"Tool {tool.value} used expected {argument_name}={expected_value!r}."
                ),
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=f"tool_argument:{index}:{tool.value}:{argument_name}",
            type=EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_MISMATCH,
            severity=failure_severity,
            reason=(
                f"Tool {tool.value} did not use expected "
                f"{argument_name}={expected_value!r}."
            ),
            evidence=evidence,
        )

    @staticmethod
    def _forbidden_tool_check(
        scenario: Scenario,
        tool: ToolName,
        condition: str,
        events: list[ToolEvent],
        index: int,
    ) -> EvaluationCheckResult:
        evidence = EvaluationEvidence(
            expected_tool=tool,
            offending_event=events[0] if events else None,
            condition=condition,
        )
        if not events:
            return EvaluationCheckResult(
                check_id=f"forbidden_tool:{index}:{tool.value}",
                type=EvaluationCheckType.FORBIDDEN_TOOL_CALL,
                status=EvaluationStatus.PASS,
                reason=f"Forbidden tool {tool.value} was not called.",
                evidence=evidence,
            )

        reason = f"Forbidden tool {tool.value} was called."
        required_document = scenario.synthetic_context.required_document
        if (
            tool is ToolName.SUBMIT_CLAIM
            and required_document is not None
            and scenario.synthetic_context.document_available is False
        ):
            reason = (
                f"submit_claim was called before required {required_document} was collected"
            )
        return EvaluationCheckResult(
            check_id=f"forbidden_tool:{index}:{tool.value}",
            type=EvaluationCheckType.FORBIDDEN_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_CALL_POLICY_VIOLATION,
            severity=scenario.severity_if_failed,
            reason=reason,
            evidence=evidence,
        )
