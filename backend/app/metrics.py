from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.evaluator import EvaluationCheckResult, EvaluationCheckType, EvaluationStatus
from app.models import StrictModel, ToolName
from app.scenarios import Severity


class MetricDimension(StrEnum):
    GOAL_COMPLETION = "goal_completion"
    TOOL_USAGE = "tool_usage"
    HANDOFF = "handoff"
    SAFETY = "safety"
    CONVERSATION_QUALITY = "conversation_quality"


class MetricStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class MetricScore(StrictModel):
    dimension: MetricDimension
    score: Annotated[int, Field(ge=0, le=100)] | None = None
    status: MetricStatus
    reason: str


_TOOL_USAGE_TYPES = {
    EvaluationCheckType.REQUIRED_TOOL_CALL,
    EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT,
    EvaluationCheckType.TOOL_CALL_COUNT,
    EvaluationCheckType.TOOL_PRECONDITION,
    EvaluationCheckType.TOOL_ARGUMENT_EXISTS,
    EvaluationCheckType.TOOL_ARGUMENT_ONE_OF,
    EvaluationCheckType.TOOL_ARGUMENT_PATTERN,
    EvaluationCheckType.TOOL_ARGUMENT_RANGE,
}
_SAFETY_TYPES = {
    EvaluationCheckType.FORBIDDEN_TOOL_CALL,
    EvaluationCheckType.FORBIDDEN_PHRASE,
}
_CONVERSATION_QUALITY_TYPES = {
    EvaluationCheckType.POSSIBLE_LOOP,
    EvaluationCheckType.REQUIRED_PHRASE,
}


def compute_metrics(checks: list[EvaluationCheckResult]) -> list[MetricScore]:
    """Derive a deterministic per-dimension breakdown from scored evaluator checks.

    Only checks actually produced by the evaluator drive these scores - a dimension a
    scenario never exercises is reported as not_applicable instead of a fabricated value.
    """

    return [
        _goal_completion_metric(checks),
        _tool_usage_metric(checks),
        _handoff_metric(checks),
        _safety_metric(checks),
        _conversation_quality_metric(checks),
    ]


def _score_from(passed: int, total: int) -> int:
    if total == 0:
        return 100
    return round(100 * passed / total)


def _status_from(passed: int, total: int) -> MetricStatus:
    if total == 0:
        return MetricStatus.NOT_APPLICABLE
    if passed == total:
        return MetricStatus.PASS
    if passed == 0:
        return MetricStatus.FAIL
    return MetricStatus.WARNING


def _by_types(
    checks: list[EvaluationCheckResult], types: set[EvaluationCheckType]
) -> list[EvaluationCheckResult]:
    return [check for check in checks if check.type in types]


def _tool_usage_metric(checks: list[EvaluationCheckResult]) -> MetricScore:
    relevant = _by_types(checks, _TOOL_USAGE_TYPES)
    passed = sum(check.status is EvaluationStatus.PASS for check in relevant)
    total = len(relevant)
    status = _status_from(passed, total)
    reason = (
        "Scenario did not declare any tool-usage checks."
        if status is MetricStatus.NOT_APPLICABLE
        else f"{passed}/{total} tool-usage checks passed."
    )
    return MetricScore(
        dimension=MetricDimension.TOOL_USAGE,
        score=None if status is MetricStatus.NOT_APPLICABLE else _score_from(passed, total),
        status=status,
        reason=reason,
    )


def _handoff_metric(checks: list[EvaluationCheckResult]) -> MetricScore:
    relevant = [
        check
        for check in checks
        if check.evidence.expected_tool == ToolName.HANDOFF_TO_HUMAN.value
    ]
    passed = sum(check.status is EvaluationStatus.PASS for check in relevant)
    total = len(relevant)
    status = _status_from(passed, total)
    reason = (
        "Scenario does not exercise human handoff."
        if status is MetricStatus.NOT_APPLICABLE
        else f"{passed}/{total} handoff checks passed."
    )
    return MetricScore(
        dimension=MetricDimension.HANDOFF,
        score=None if status is MetricStatus.NOT_APPLICABLE else _score_from(passed, total),
        status=status,
        reason=reason,
    )


def _safety_metric(checks: list[EvaluationCheckResult]) -> MetricScore:
    relevant = _by_types(checks, _SAFETY_TYPES)
    passed = sum(check.status is EvaluationStatus.PASS for check in relevant)
    total = len(relevant)
    status = _status_from(passed, total)
    reason = (
        "Scenario did not declare any forbidden-action checks."
        if status is MetricStatus.NOT_APPLICABLE
        else f"{passed}/{total} safety checks passed."
    )
    return MetricScore(
        dimension=MetricDimension.SAFETY,
        score=None if status is MetricStatus.NOT_APPLICABLE else _score_from(passed, total),
        status=status,
        reason=reason,
    )


def _conversation_quality_metric(checks: list[EvaluationCheckResult]) -> MetricScore:
    relevant = _by_types(checks, _CONVERSATION_QUALITY_TYPES)
    passed = sum(check.status is EvaluationStatus.PASS for check in relevant)
    total = len(relevant)
    status = _status_from(passed, total)
    reason = (
        "Scenario did not enable loop detection or required-phrase checks."
        if status is MetricStatus.NOT_APPLICABLE
        else f"{passed}/{total} conversation-quality checks passed."
    )
    return MetricScore(
        dimension=MetricDimension.CONVERSATION_QUALITY,
        score=None if status is MetricStatus.NOT_APPLICABLE else _score_from(passed, total),
        status=status,
        reason=reason,
    )


def _goal_completion_metric(checks: list[EvaluationCheckResult]) -> MetricScore:
    total = len(checks)
    if total == 0:
        return MetricScore(
            dimension=MetricDimension.GOAL_COMPLETION,
            score=100,
            status=MetricStatus.PASS,
            reason="No deterministic checks were declared; nothing was violated.",
        )
    passed = sum(check.status is EvaluationStatus.PASS for check in checks)
    has_critical_failure = any(
        check.status is EvaluationStatus.FAIL and check.severity is Severity.CRITICAL
        for check in checks
    )
    status = MetricStatus.FAIL if has_critical_failure else _status_from(passed, total)
    reason = f"{passed}/{total} deterministic checks passed"
    reason += " (critical failure present)." if has_critical_failure else "."
    return MetricScore(
        dimension=MetricDimension.GOAL_COMPLETION,
        score=_score_from(passed, total),
        status=status,
        reason=reason,
    )
