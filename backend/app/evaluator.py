import math
import re
from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field

from app.models import JsonScalar, StrictModel, ToolEvent, ToolName, ToolReference
from app.scenarios import (
    ArgumentConstraint,
    ArgumentExistsConstraint,
    ArgumentOneOfConstraint,
    ArgumentPatternConstraint,
    ArgumentRangeConstraint,
    Scenario,
    Severity,
    ToolOrderConstraint,
)


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
    TOOL_PRECONDITION = "tool_precondition"
    TOOL_ARGUMENT_EXISTS = "tool_argument_exists"
    TOOL_ARGUMENT_ONE_OF = "tool_argument_one_of"
    TOOL_ARGUMENT_PATTERN = "tool_argument_pattern"
    TOOL_ARGUMENT_RANGE = "tool_argument_range"


class EvaluationCategory(StrEnum):
    REQUIRED_TOOL_MISSING = "required_tool_missing"
    TOOL_ARGUMENT_MISMATCH = "tool_argument_mismatch"
    TOOL_CALL_POLICY_VIOLATION = "tool_call_policy_violation"
    EXCESSIVE_TOOL_CALLS = "excessive_tool_calls"
    FORBIDDEN_PHRASE_DETECTED = "forbidden_phrase_detected"
    REQUIRED_PHRASE_MISSING = "required_phrase_missing"
    POSSIBLE_LOOP_DETECTED = "possible_loop_detected"
    TOOL_PRECONDITION_VIOLATION = "tool_precondition_violation"
    TOOL_ARGUMENT_MISSING = "tool_argument_missing"
    TOOL_ARGUMENT_NOT_ALLOWED = "tool_argument_not_allowed"
    TOOL_ARGUMENT_PATTERN_MISMATCH = "tool_argument_pattern_mismatch"
    TOOL_ARGUMENT_RANGE_VIOLATION = "tool_argument_range_violation"


class EvaluationEvidence(StrictModel):
    expected_tool: ToolReference | None = None
    prerequisite_tool: ToolReference | None = None
    argument_name: str | None = None
    expected_value: JsonScalar = None
    allowed_values: list[JsonScalar] = Field(default_factory=list)
    pattern: str | None = None
    min_value: float | None = None
    max_value: float | None = None
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


def _json_scalar_matches(actual: JsonScalar, expected: JsonScalar) -> bool:
    # JSON booleans are distinct from numbers even though bool subclasses int in Python.
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


class DeterministicToolEvaluator:
    """Evaluate structured fixture contracts against observed tool/response evidence."""

    def evaluate(
        self,
        scenario: Scenario,
        tool_trace: list[ToolEvent],
        assistant_messages: Sequence[str] = (),
    ) -> EvaluationReport:
        events_by_tool: dict[ToolReference, list[ToolEvent]] = defaultdict(list)
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
            sorted(scenario.max_tool_call_counts.items(), key=lambda item: str(item[0])),
            start=1,
        ):
            checks.append(
                self._tool_call_count_check(
                    tool, max_count, events_by_tool[tool], scenario.severity_if_failed, index
                )
            )

        for index, constraint in enumerate(scenario.tool_order_constraints, start=1):
            checks.append(
                self._tool_precondition_check(
                    constraint,
                    tool_trace,
                    scenario.severity_if_failed,
                    index,
                )
            )

        for index, constraint in enumerate(scenario.argument_constraints, start=1):
            events = events_by_tool[constraint.tool]
            # Match the existing exact-argument semantics: absence of an optional
            # tool is not itself an argument violation. Required-tool rules own that.
            if events:
                checks.append(
                    self._rich_argument_check(
                        constraint,
                        events,
                        scenario.severity_if_failed,
                        index,
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
        tool: ToolReference,
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
        tool: ToolReference,
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
                and _json_scalar_matches(event.arguments[argument_name], expected_value)
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
        tool: ToolReference,
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
            tool == ToolName.SUBMIT_CLAIM
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
        tool: ToolReference,
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
    def _tool_precondition_check(
        constraint: ToolOrderConstraint,
        tool_trace: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        evidence = EvaluationEvidence(
            expected_tool=constraint.after,
            prerequisite_tool=constraint.before,
            condition=f"{constraint.before} before {constraint.after}",
        )
        after_position = next(
            (
                (position, event)
                for position, event in enumerate(tool_trace)
                if event.tool == constraint.after
            ),
            None,
        )
        if after_position is None:
            return EvaluationCheckResult(
                check_id=f"tool_precondition:{index}:{constraint.before}:{constraint.after}",
                type=EvaluationCheckType.TOOL_PRECONDITION,
                status=EvaluationStatus.PASS,
                reason=f"Tool {constraint.after} was not called, so its prerequisite was not violated.",
                evidence=evidence,
            )

        position, after_event = after_position
        prerequisite_event = next(
            (
                event
                for event in reversed(tool_trace[:position])
                if event.tool == constraint.before
            ),
            None,
        )
        if prerequisite_event is not None:
            evidence.matching_event = prerequisite_event
            return EvaluationCheckResult(
                check_id=f"tool_precondition:{index}:{constraint.before}:{constraint.after}",
                type=EvaluationCheckType.TOOL_PRECONDITION,
                status=EvaluationStatus.PASS,
                reason=f"Tool {constraint.before} occurred before {constraint.after}.",
                evidence=evidence,
            )

        evidence.offending_event = after_event
        return EvaluationCheckResult(
            check_id=f"tool_precondition:{index}:{constraint.before}:{constraint.after}",
            type=EvaluationCheckType.TOOL_PRECONDITION,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_PRECONDITION_VIOLATION,
            severity=failure_severity,
            reason=f"Tool {constraint.after} was called before prerequisite {constraint.before}.",
            evidence=evidence,
        )

    @classmethod
    def _rich_argument_check(
        cls,
        constraint: ArgumentConstraint,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        if isinstance(constraint, ArgumentExistsConstraint):
            return cls._argument_exists_check(constraint, events, failure_severity, index)
        if isinstance(constraint, ArgumentOneOfConstraint):
            return cls._argument_one_of_check(constraint, events, failure_severity, index)
        if isinstance(constraint, ArgumentPatternConstraint):
            return cls._argument_pattern_check(constraint, events, failure_severity, index)
        return cls._argument_range_check(constraint, events, failure_severity, index)

    @staticmethod
    def _argument_exists_check(
        constraint: ArgumentExistsConstraint,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        offending = next(
            (event for event in events if constraint.argument not in event.arguments),
            None,
        )
        evidence = EvaluationEvidence(
            expected_tool=constraint.tool,
            argument_name=constraint.argument,
            actual_values=[event.arguments.get(constraint.argument) for event in events],
            matching_event=events[0] if offending is None else None,
            offending_event=offending,
        )
        check_id = f"tool_argument_exists:{index}:{constraint.tool}:{constraint.argument}"
        if offending is None:
            return EvaluationCheckResult(
                check_id=check_id,
                type=EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
                status=EvaluationStatus.PASS,
                reason=f"Every {constraint.tool} call included argument {constraint.argument}.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=check_id,
            type=EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_MISSING,
            severity=failure_severity,
            reason=f"A {constraint.tool} call omitted required argument {constraint.argument}.",
            evidence=evidence,
        )

    @staticmethod
    def _argument_one_of_check(
        constraint: ArgumentOneOfConstraint,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        def is_allowed(event: ToolEvent) -> bool:
            if constraint.argument not in event.arguments:
                return False
            actual = event.arguments[constraint.argument]
            return any(_json_scalar_matches(actual, allowed) for allowed in constraint.values)

        offending = next((event for event in events if not is_allowed(event)), None)
        evidence = EvaluationEvidence(
            expected_tool=constraint.tool,
            argument_name=constraint.argument,
            allowed_values=list(constraint.values),
            actual_values=[event.arguments.get(constraint.argument) for event in events],
            matching_event=events[0] if offending is None else None,
            offending_event=offending,
        )
        check_id = f"tool_argument_one_of:{index}:{constraint.tool}:{constraint.argument}"
        if offending is None:
            return EvaluationCheckResult(
                check_id=check_id,
                type=EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
                status=EvaluationStatus.PASS,
                reason=f"Every {constraint.tool}.{constraint.argument} value was allowed.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=check_id,
            type=EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_NOT_ALLOWED,
            severity=failure_severity,
            reason=f"A {constraint.tool}.{constraint.argument} value was outside the allowed set.",
            evidence=evidence,
        )

    @staticmethod
    def _argument_pattern_check(
        constraint: ArgumentPatternConstraint,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        compiled = re.compile(constraint.pattern)

        def matches(event: ToolEvent) -> bool:
            if constraint.argument not in event.arguments:
                return False
            actual = event.arguments[constraint.argument]
            return isinstance(actual, str) and len(actual) <= 4_096 and compiled.fullmatch(actual) is not None

        offending = next((event for event in events if not matches(event)), None)
        evidence = EvaluationEvidence(
            expected_tool=constraint.tool,
            argument_name=constraint.argument,
            pattern=constraint.pattern,
            actual_values=[event.arguments.get(constraint.argument) for event in events],
            matching_event=events[0] if offending is None else None,
            offending_event=offending,
        )
        check_id = f"tool_argument_pattern:{index}:{constraint.tool}:{constraint.argument}"
        if offending is None:
            return EvaluationCheckResult(
                check_id=check_id,
                type=EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
                status=EvaluationStatus.PASS,
                reason=f"Every {constraint.tool}.{constraint.argument} value matched the required pattern.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=check_id,
            type=EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_PATTERN_MISMATCH,
            severity=failure_severity,
            reason=f"A {constraint.tool}.{constraint.argument} value did not match the required pattern.",
            evidence=evidence,
        )

    @staticmethod
    def _argument_range_check(
        constraint: ArgumentRangeConstraint,
        events: list[ToolEvent],
        failure_severity: Severity,
        index: int,
    ) -> EvaluationCheckResult:
        def in_range(event: ToolEvent) -> bool:
            if constraint.argument not in event.arguments:
                return False
            actual = event.arguments[constraint.argument]
            if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                return False
            numeric = float(actual)
            if not math.isfinite(numeric):
                return False
            if constraint.min_value is not None and numeric < constraint.min_value:
                return False
            return constraint.max_value is None or numeric <= constraint.max_value

        offending = next((event for event in events if not in_range(event)), None)
        evidence = EvaluationEvidence(
            expected_tool=constraint.tool,
            argument_name=constraint.argument,
            min_value=constraint.min_value,
            max_value=constraint.max_value,
            actual_values=[event.arguments.get(constraint.argument) for event in events],
            matching_event=events[0] if offending is None else None,
            offending_event=offending,
        )
        check_id = f"tool_argument_range:{index}:{constraint.tool}:{constraint.argument}"
        if offending is None:
            return EvaluationCheckResult(
                check_id=check_id,
                type=EvaluationCheckType.TOOL_ARGUMENT_RANGE,
                status=EvaluationStatus.PASS,
                reason=f"Every {constraint.tool}.{constraint.argument} value was within range.",
                evidence=evidence,
            )
        return EvaluationCheckResult(
            check_id=check_id,
            type=EvaluationCheckType.TOOL_ARGUMENT_RANGE,
            status=EvaluationStatus.FAIL,
            category=EvaluationCategory.TOOL_ARGUMENT_RANGE_VIOLATION,
            severity=failure_severity,
            reason=f"A {constraint.tool}.{constraint.argument} value was outside the required range.",
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
