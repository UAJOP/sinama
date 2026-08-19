from uuid import UUID

from app.evaluator import EvaluationCheckResult, EvaluationCheckType, EvaluationStatus
from app.models import StrictModel
from app.scenarios import Severity


class Failure(StrictModel):
    """Structured, human-readable record of a single failed deterministic check."""

    type: EvaluationCheckType
    severity: Severity
    turn: int | None
    title: str
    description: str
    expected: str
    actual: str
    suggestion: str


def build_failures(
    checks: list[EvaluationCheckResult],
    event_turn: dict[UUID, int],
) -> list[Failure]:
    return [
        _to_failure(check, event_turn)
        for check in checks
        if check.status is EvaluationStatus.FAIL
    ]


def _resolve_turn(check: EvaluationCheckResult, event_turn: dict[UUID, int]) -> int | None:
    evidence = check.evidence
    if evidence.offending_event is not None:
        return event_turn.get(evidence.offending_event.id)
    if evidence.assistant_message_index is not None:
        return evidence.assistant_message_index + 1
    return None


def _range_description(min_value: float | None, max_value: float | None) -> str:
    if min_value is not None and max_value is not None:
        return f"between {min_value} and {max_value}, inclusive"
    if min_value is not None:
        return f"at least {min_value}"
    return f"at most {max_value}"


def _to_failure(check: EvaluationCheckResult, event_turn: dict[UUID, int]) -> Failure:
    evidence = check.evidence
    severity = check.severity or Severity.MEDIUM

    if check.type is EvaluationCheckType.REQUIRED_TOOL_CALL:
        title = f"Required tool {evidence.expected_tool} was not called"
        expected = f"Agent should call {evidence.expected_tool}."
        actual = "No matching tool call was observed."
        suggestion = "Ensure the agent invokes the required tool before responding to the customer."
    elif check.type is EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT:
        title = f"Unexpected value for {evidence.argument_name}"
        expected = (
            f"{evidence.expected_tool} should be called with "
            f"{evidence.argument_name}={evidence.expected_value!r}."
        )
        actual = f"Observed value(s): {evidence.actual_values!r}."
        suggestion = "Verify the agent passes the correct argument value to the tool."
    elif check.type is EvaluationCheckType.FORBIDDEN_TOOL_CALL:
        title = f"Forbidden tool {evidence.expected_tool} was called"
        expected = f"{evidence.expected_tool} should not be called while: {evidence.condition}."
        actual = check.reason
        suggestion = "Add a guard that blocks this tool call until its precondition is satisfied."
    elif check.type is EvaluationCheckType.TOOL_CALL_COUNT:
        title = f"{evidence.expected_tool} was called too many times"
        expected = f"At most {evidence.max_allowed} call(s)."
        actual = f"{evidence.tool_call_count} call(s) were observed."
        suggestion = (
            "Cache or short-circuit repeated tool calls once the required data has "
            "already been retrieved."
        )
    elif check.type is EvaluationCheckType.TOOL_PRECONDITION:
        title = f"{evidence.expected_tool} was called before its prerequisite"
        expected = (
            f"{evidence.prerequisite_tool} should occur before {evidence.expected_tool}."
        )
        actual = check.reason
        suggestion = (
            f"Gate {evidence.expected_tool} until {evidence.prerequisite_tool} has completed "
            "successfully in the current workflow."
        )
    elif check.type is EvaluationCheckType.TOOL_ARGUMENT_EXISTS:
        title = f"Required argument {evidence.argument_name} was missing"
        expected = f"Every {evidence.expected_tool} call should include {evidence.argument_name}."
        actual = "At least one observed tool call omitted the argument."
        suggestion = "Validate required tool arguments before dispatching the tool call."
    elif check.type is EvaluationCheckType.TOOL_ARGUMENT_ONE_OF:
        title = f"Unexpected value for {evidence.argument_name}"
        expected = f"Allowed value(s): {evidence.allowed_values!r}."
        actual = f"Observed value(s): {evidence.actual_values!r}."
        suggestion = "Constrain the tool argument to the scenario-approved value set."
    elif check.type is EvaluationCheckType.TOOL_ARGUMENT_PATTERN:
        title = f"Invalid format for {evidence.argument_name}"
        expected = f"Value should fully match pattern {evidence.pattern!r}."
        actual = f"Observed value(s): {evidence.actual_values!r}."
        suggestion = "Normalize and validate the argument format before invoking the tool."
    elif check.type is EvaluationCheckType.TOOL_ARGUMENT_RANGE:
        title = f"Out-of-range value for {evidence.argument_name}"
        expected = (
            f"Value should be {_range_description(evidence.min_value, evidence.max_value)}."
        )
        actual = f"Observed value(s): {evidence.actual_values!r}."
        suggestion = "Validate numeric bounds before dispatching the tool call."
    elif check.type is EvaluationCheckType.FORBIDDEN_PHRASE:
        title = "Agent used a forbidden phrase"
        expected = f"Responses should not contain: {evidence.condition!r}."
        actual = f"Matched phrase: {evidence.matched_phrase!r}."
        suggestion = (
            "Require the agent to ground this type of statement in tool output "
            "instead of asserting it directly."
        )
    elif check.type is EvaluationCheckType.REQUIRED_PHRASE:
        title = "Agent omitted a required disclosure"
        expected = f"A response should contain: {evidence.condition!r}."
        actual = "No assistant response included the required phrase."
        suggestion = "Update the agent's response templates to include this disclosure."
    else:
        title = "Possible response loop detected"
        expected = "Assistant responses should progress the conversation."
        actual = "Three consecutive assistant responses were nearly identical."
        suggestion = (
            "Add state tracking so the agent recognizes when the customer isn't "
            "progressing and escalates or rephrases."
        )

    return Failure(
        type=check.type,
        severity=severity,
        turn=_resolve_turn(check, event_turn),
        title=title,
        description=check.reason,
        expected=expected,
        actual=actual,
        suggestion=suggestion,
    )
