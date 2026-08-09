from app.evaluator import (
    EvaluationCheckResult,
    EvaluationCheckType,
    EvaluationEvidence,
    EvaluationStatus,
)
from app.metrics import MetricDimension, MetricStatus, compute_metrics
from app.models import ToolName
from app.scenarios import Severity


def check(
    check_type: EvaluationCheckType,
    status: EvaluationStatus,
    severity: Severity | None = None,
    expected_tool: ToolName | None = None,
) -> EvaluationCheckResult:
    return EvaluationCheckResult(
        check_id="x",
        type=check_type,
        status=status,
        severity=severity,
        reason="reason",
        evidence=EvaluationEvidence(expected_tool=expected_tool),
    )


def by_dimension(checks: list[EvaluationCheckResult]) -> dict[MetricDimension, object]:
    return {metric.dimension: metric for metric in compute_metrics(checks)}


def test_metrics_are_not_applicable_when_scenario_declares_nothing() -> None:
    metrics = by_dimension([])

    assert metrics[MetricDimension.TOOL_USAGE].status is MetricStatus.NOT_APPLICABLE
    assert metrics[MetricDimension.TOOL_USAGE].score is None
    assert metrics[MetricDimension.HANDOFF].status is MetricStatus.NOT_APPLICABLE
    assert metrics[MetricDimension.SAFETY].status is MetricStatus.NOT_APPLICABLE
    assert metrics[MetricDimension.CONVERSATION_QUALITY].status is MetricStatus.NOT_APPLICABLE
    assert metrics[MetricDimension.GOAL_COMPLETION].status is MetricStatus.PASS
    assert metrics[MetricDimension.GOAL_COMPLETION].score == 100


def test_goal_completion_forces_fail_on_critical_severity_regardless_of_ratio() -> None:
    checks = [
        check(EvaluationCheckType.REQUIRED_TOOL_CALL, EvaluationStatus.PASS),
        check(EvaluationCheckType.FORBIDDEN_TOOL_CALL, EvaluationStatus.FAIL, Severity.CRITICAL),
    ]

    metrics = by_dimension(checks)

    assert metrics[MetricDimension.GOAL_COMPLETION].status is MetricStatus.FAIL
    assert "critical failure present" in metrics[MetricDimension.GOAL_COMPLETION].reason


def test_tool_usage_metric_scores_only_tool_related_checks() -> None:
    checks = [
        check(EvaluationCheckType.REQUIRED_TOOL_CALL, EvaluationStatus.PASS),
        check(EvaluationCheckType.TOOL_ARGUMENT_CONSTRAINT, EvaluationStatus.FAIL, Severity.MEDIUM),
        check(EvaluationCheckType.FORBIDDEN_TOOL_CALL, EvaluationStatus.PASS),
    ]

    metrics = by_dimension(checks)

    tool_usage = metrics[MetricDimension.TOOL_USAGE]
    assert tool_usage.status is MetricStatus.WARNING
    assert tool_usage.score == 50
    safety = metrics[MetricDimension.SAFETY]
    assert safety.status is MetricStatus.PASS
    assert safety.score == 100


def test_handoff_metric_only_counts_handoff_related_checks() -> None:
    checks = [
        check(
            EvaluationCheckType.REQUIRED_TOOL_CALL,
            EvaluationStatus.PASS,
            expected_tool=ToolName.HANDOFF_TO_HUMAN,
        ),
        check(
            EvaluationCheckType.REQUIRED_TOOL_CALL,
            EvaluationStatus.FAIL,
            Severity.LOW,
            expected_tool=ToolName.LOOKUP_POLICY,
        ),
    ]

    metrics = by_dimension(checks)

    assert metrics[MetricDimension.HANDOFF].status is MetricStatus.PASS
    assert metrics[MetricDimension.HANDOFF].score == 100


def test_conversation_quality_metric_fails_on_possible_loop() -> None:
    checks = [check(EvaluationCheckType.POSSIBLE_LOOP, EvaluationStatus.FAIL, Severity.MEDIUM)]

    metrics = by_dimension(checks)

    assert metrics[MetricDimension.CONVERSATION_QUALITY].status is MetricStatus.FAIL
    assert metrics[MetricDimension.CONVERSATION_QUALITY].score == 0
