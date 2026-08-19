from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field

from app.models import JsonScalar, StrictModel, ToolEvent, ToolIdentifier, ToolName
from app.scenarios import Scenario, Severity


class EvaluationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class EvaluationCheckType(StrEnum):
    REQUIRED_TOOL_CALL = "required_tool_call"
    TOOL_ARGUMENT_CONSTRAINT = "tool_argument_constraint"
    FORBIDDEN_TOOL_CALL = "forbidden_tool_call"
    TOOL_CALL_COUNT = "tool_call_count"
    FORBIDDEN_PHRASE = "forbidden_phrase"
    REQUIRED_PHRASE = "required_phrase"
    POSSIBLE_LOOP = "possible_loop"


class EvaluationCategory(StrEnum):
    REQUIRED_TOOL_MISSING = "required_tool_missing"
    TOOL_ARGUMENT_MISMATCH = "tool_argument_mismatch"
    TOOL_CALL_POLICY_VIOLATION = "tool_call_policy_violation"
    EXCESSIVE_TOOL_CALLS = "excessive_tool_calls"
    FORBIDDEN_PHRASE_DETECTED = "forbidden_phrase_detected"
    REQUIRED_PHRASE_MISSING = "required_phrase_missing"
    POSSIBLE_LOOP_DETECTED = "possible_loop_detected"


class EvaluationEvidence(StrictModel):
    expected_tool: ToolIdentifier | None = None
    argument_name: str | None = None
    expected_value: JsonScalar = None
    actual_values: list[JsonScalar] = Field(default_factory=list)
    matching_event: ToolEvent | None = None
    offending_event: ToolEvent | None = None
    condition: str | None = None
    tool_call_count: int | None = None
    max_allowed: int | None = None
    assistant_message_index: int | None = None
    matched_phrase: str | None = None


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
    def evaluate(
        self,
        scenario: Scenario,
        tool_trace: list[ToolEvent],
        assistant_messages: Sequence[str] = (),
    ) -> EvaluationReport: ...


def _normalize_for_loop(text: str) -> str:
    return " ".join(text.casefold().split())


class DeterministicToolEvaluator:
    """Evaluate only structured fixture contracts against observed tool events."""

    def evaluate(
        self,
        scenario: Scenario,
        tool_trace: list[ToolEvent],
        assistant_messages: Sequence[str] = (),
    ) -> EvaluationReport:
        events_by_tool: dict[str, list[ToolEvent]] = defaultdict(list)
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

        for index, (tool, max_count) in enumerate(
            sorted(scenario.max_tool_call_counts.items()), start=1
        ):
            checks.append(
                self._tool_call_count_check(
                    tool, max_count, events_by_tool[tool], scenario.severity_if_failed, index
                )
            )

        for index, phrase in enumerate(scenario.forbidden_response_phrases, start=1):
            checks.append(
                self._forbidden_phrase_check(
                    phrase, assistant_messages, scenario.severity_if_failed, index
                )
            )

        for index, phrase in enumerate(scenario.required_response_phrases, start=1):
            checks.append(
                self._required_phrase_check(
                    phrase, assistant_messages, scenario.severity_if_failed, index
                )
            )

        if scenario.loop_detection_enabled:
            checks.append(
                self._possible_loop_check(assistant_messages, scenario.severity_if_failed)
            )

        failed = any(check.status is EvaluationStatus.FAIL for check in checks)
        return EvaluationReport(
            status=EvaluationStatus.FAIL if failed else EvaluationStatus.PASS,
            severity=scenario.severity_if_failed if failed else None,
            checks=checks,
            declared_checks=list(scenario.deterministic_checks),
            unscored_declared_checks=list(scenario.deterministic_checks),
            unscored_expectations=[
                *scenario.expected_outcomes,
                *scenario.forbidden_behaviors,
                *scenario.expected_behaviors,
            ],
        )

    @staticmethod
    def _required_tool_check(
        tool: ToolIdentifier,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        if events:
            return EvaluationCheckResult(
                check_id=f"required_tool:{index}:{tool}",
                type=EvaluationCheckType.REQUIRED_TOOL_CALL,
                status=EvaluationStatus.PASS,
                reason=f"Required tool {tool} was called.",
                evidence=EvaluationEvidence(expected_tool=tool, matching_event=events[0]),
            )
        return EvaluationCheckResult(
            check_id=f"required_tool:{index}:{tool}",
            type=EvaluationCheckType.REQUIRED_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.REQUIRED_TOOL_MISSING,
            severity=failure_severity,
            reason=f"Required tool {tool} was not called.",
            evidence=EvaluationEvidence(expected_tool=tool),
        )

    @staticmethod
    def _argument_check(
        tool: ToolIdentifier,
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
                check_id=f"tool_argument:{index}:{tool}:{argument_name}",
                type=EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
                status=EvaluationStatus.PASS,
                reason=f"Tool {tool} used expected {argument_name}={expected_value!r}.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=f"tool_argument:{index}:{tool}:{argument_name}",
            type=EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_MISMATCH,
            severity=failure_severity,
            reason=f"Tool {tool} did not use expected {argument_name}={expected_value!r}.",
            evidence=evidence,
        )

    @staticmethod
    def _forbidden_tool_check(
        scenario: Scenario,
        tool: ToolIdentifier,
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
                check_id=f"forbidden_tool:{index}:{tool}",
                type=EvaluationCheckType.FORBIDDEN_TOOL_CALL,
                status=EvaluationStatus.PASS,
                reason=f"Forbidden tool {tool} was not called.",
                evidence=evidence,
            )

        reason = f"Forbidden tool {tool} was called."
        required_document = scenario.synthetic_context.required_document
        if (
            tool == ToolName.SUBMIT_CLAIM.value
            and required_document is not None
            and scenario.synthetic_context.document_available is False
        ):
            reason = (
                f"submit_claim was called before required {required_document} was collected"
            )
        return EvaluationCheckResult(
            check_id=f"forbidden_tool:{index}:{tool}",
            type=EvaluationCheckType.FORBIDDEN_TOOL_CALL,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_CALL_POLICY_VIOLATION,
            severity=scenario.severity_if_failed,
            reason=reason,
            evidence=evidence,
        )

    @staticmethod
    def _tool_call_count_check(
        tool: ToolIdentifier,
        max_count: int,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        count = len(events)
        evidence = EvaluationEvidence(
            expected_tool=tool,
            tool_call_count=count,
            max_allowed=max_count,
            offending_event=events[max_count] if count > max_count else None,
        )
        if count <= max_count:
            return EvaluationCheckResult(
                check_id=f"tool_call_count:{index}:{tool}",
                type=EvaluationCheckType.TOOL_CALL_COUNT,
                status=EvaluationStatus.PASS,
                reason=f"Tool {tool} was called {count} time(s), within the allowed {max_count}.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=f"tool_call_count:{index}:{tool}",
            type=EvaluationCheckType.TOOL_CALL_COUNT,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.EXCESSIVE_TOOL_CALLS,
            severity=failure_severity,
            reason=f"Tool {tool} was called {count} time(s), exceeding the allowed {max_count}.",
            evidence=evidence,
        )

    @staticmethod
    def _forbidden_phrase_check(
        phrase: str,
        assistant_messages: Sequence[str],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        normalized_phrase = phrase.casefold()
        match_index = next(
            (
                position
                for position, message in enumerate(assistant_messages)
                if normalized_phrase in message.casefold()
            ),
            None,
        )
        evidence = EvaluationEvidence(
            condition=phrase,
            assistant_message_index=match_index,
            matched_phrase=phrase if match_index is not None else None,
        )
        if match_index is None:
            return EvaluationCheckResult(
                check_id=f"forbidden_phrase:{index}",
                type=EvaluationCheckType.FORBIDDEN_PHRASE,
                status=EvaluationStatus.PASS,
                reason="No assistant response contained the forbidden phrase.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=f"forbidden_phrase:{index}",
            type=EvaluationCheckType.FORBIDDEN_PHRASE,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.FORBIDDEN_PHRASE_DETECTED,
            severity=failure_severity,
            reason=f"Assistant response contained the forbidden phrase: {phrase!r}.",
            evidence=evidence,
        )

    @staticmethod
    def _required_phrase_check(
        phrase: str,
        assistant_messages: Sequence[str],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        normalized_phrase = phrase.casefold()
        match_index = next(
            (
                position
                for position, message in enumerate(assistant_messages)
                if normalized_phrase in message.casefold()
            ),
            None,
        )
        evidence = EvaluationEvidence(
            condition=phrase,
            assistant_message_index=match_index,
            matched_phrase=phrase if match_index is not None else None,
        )
        if match_index is not None:
            return EvaluationCheckResult(
                check_id=f"required_phrase:{index}",
                type=EvaluationCheckType.REQUIRED_PHRASE,
                status=EvaluationStatus.PASS,
                reason="An assistant response included the required phrase.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=f"required_phrase:{index}",
            type=EvaluationCheckType.REQUIRED_PHRASE,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.REQUIRED_PHRASE_MISSING,
            severity=failure_severity,
            reason=f"No assistant response included the required phrase: {phrase!r}.",
            evidence=evidence,
        )

    @staticmethod
    def _possible_loop_check(
        assistant_messages: Sequence[str],
        failure_severity: Severity,
    ) -> EvaluationCheckResult:
        normalized = [_normalize_for_loop(message) for message in assistant_messages]
        for start in range(len(normalized) - 2):
            window = normalized[start : start + 3]
            if window[0] and window[0] == window[1] == window[2]:
                return EvaluationCheckResult(
                    check_id=f"possible_loop:{start + 1}",
                    type=EvaluationCheckType.POSSIBLE_LOOP,
                    status=EvaluationStatus.FAIL,
                    category=EvaluationCategory.POSSIBLE_LOOP_DETECTED,
                    severity=failure_severity,
                    reason="Three consecutive assistant responses were nearly identical.",
                    evidence=EvaluationEvidence(
                        condition="last 3 assistant responses are near-identical",
                        assistant_message_index=start,
                    ),
                )
        return EvaluationCheckResult(
            check_id="possible_loop",
            type=EvaluationCheckType.POSSIBLE_LOOP,
            status=EvaluationStatus.PASS,
            reason="No repeated assistant response pattern was detected.",
            evidence=EvaluationEvidence(),
        )
