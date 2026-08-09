from uuid import uuid4

from app.evaluator import EvaluationCheckType
from app.failures import Failure
from app.metrics import MetricDimension, MetricScore, MetricStatus
from app.regression import (
    MetricComparisonStatus,
    RegressionStatus,
    build_comparison,
    compare_metrics,
    diff_failures,
)
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.scenarios import Severity


def goal_metric(score: int) -> MetricScore:
    return MetricScore(
        dimension=MetricDimension.GOAL_COMPLETION,
        score=score,
        status=MetricStatus.PASS,
        reason="x",
    )


def metric(dimension: MetricDimension, score: int | None) -> MetricScore:
    status = MetricStatus.NOT_APPLICABLE if score is None else MetricStatus.PASS
    return MetricScore(dimension=dimension, score=score, status=status, reason="x")


def failure(
    severity: Severity = Severity.HIGH,
    title: str = "Required tool was not called",
    check_type: EvaluationCheckType = EvaluationCheckType.REQUIRED_TOOL_CALL,
    turn: int | None = None,
) -> Failure:
    return Failure(
        type=check_type,
        severity=severity,
        turn=turn,
        title=title,
        description="d",
        expected="e",
        actual="a",
        suggestion="s",
    )


def result(
    scenario_id: str = "INS-001",
    metrics: list[MetricScore] | None = None,
    failures: list[Failure] | None = None,
) -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        agent_label="test",
        status=RunStatus.PASS,
        turns_executed=1,
        metrics=metrics or [],
        failures=failures or [],
    )


def comparison(baseline: list[ScenarioRunResult], current: list[ScenarioRunResult]):
    return build_comparison(
        baseline_run_id=uuid4(),
        current_run_id=uuid4(),
        pack_id="insurance-v1",
        baseline_results=baseline,
        current_results=current,
    )


def test_score_delta_of_plus_five_is_improved() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)])],
        [result(metrics=[goal_metric(85)])],
    )
    assert outcome.score_delta == 5
    assert outcome.status is RegressionStatus.IMPROVED


def test_score_delta_of_plus_four_is_stable() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)])],
        [result(metrics=[goal_metric(84)])],
    )
    assert outcome.score_delta == 4
    assert outcome.status is RegressionStatus.STABLE


def test_score_delta_of_minus_four_is_stable() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)])],
        [result(metrics=[goal_metric(76)])],
    )
    assert outcome.score_delta == -4
    assert outcome.status is RegressionStatus.STABLE


def test_score_delta_of_minus_five_is_regression() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)])],
        [result(metrics=[goal_metric(75)])],
    )
    assert outcome.score_delta == -5
    assert outcome.status is RegressionStatus.REGRESSION


def test_new_critical_failure_forces_regression_regardless_of_score_delta() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)], failures=[])],
        [
            result(
                metrics=[goal_metric(90)],
                failures=[failure(severity=Severity.CRITICAL, title="Data leaked")],
            )
        ],
    )
    assert outcome.score_delta == 10
    assert outcome.status is RegressionStatus.REGRESSION


def test_persistent_critical_failure_does_not_force_override() -> None:
    shared_failure = failure(severity=Severity.CRITICAL, title="Same critical issue")
    outcome = comparison(
        [result(metrics=[goal_metric(80)], failures=[shared_failure])],
        [result(metrics=[goal_metric(82)], failures=[shared_failure])],
    )
    assert outcome.status is RegressionStatus.STABLE


def test_errored_scenario_with_no_metrics_counts_as_zero_reliability() -> None:
    outcome = comparison(
        [result(metrics=[goal_metric(80)])],
        [result(metrics=[])],
    )
    assert outcome.current_score == 0
    assert outcome.status is RegressionStatus.REGRESSION


def test_metric_delta_calculation_averages_across_scenarios() -> None:
    baseline = [
        result("INS-001", metrics=[metric(MetricDimension.TOOL_USAGE, 100)]),
        result("INS-002", metrics=[metric(MetricDimension.TOOL_USAGE, 80)]),
    ]
    current = [
        result("INS-001", metrics=[metric(MetricDimension.TOOL_USAGE, 70)]),
        result("INS-002", metrics=[metric(MetricDimension.TOOL_USAGE, 74)]),
    ]
    changes = {change.dimension: change for change in compare_metrics(baseline, current)}
    tool_usage = changes[MetricDimension.TOOL_USAGE]
    assert tool_usage.baseline_score == 90
    assert tool_usage.current_score == 72
    assert tool_usage.delta == -18
    assert tool_usage.status is MetricComparisonStatus.REGRESSED


def test_metric_comparison_is_not_applicable_when_both_runs_lack_it() -> None:
    baseline = [result(metrics=[metric(MetricDimension.HANDOFF, None)])]
    current = [result(metrics=[metric(MetricDimension.HANDOFF, None)])]
    changes = {change.dimension: change for change in compare_metrics(baseline, current)}
    handoff = changes[MetricDimension.HANDOFF]
    assert handoff.status is MetricComparisonStatus.NOT_APPLICABLE
    assert handoff.baseline_score is None
    assert handoff.current_score is None
    assert handoff.delta is None


def test_metric_comparison_avoids_misleading_delta_when_only_one_side_has_it() -> None:
    baseline = [result(metrics=[metric(MetricDimension.HANDOFF, None)])]
    current = [result(metrics=[metric(MetricDimension.HANDOFF, 100)])]
    changes = {change.dimension: change for change in compare_metrics(baseline, current)}
    handoff = changes[MetricDimension.HANDOFF]
    assert handoff.status is MetricComparisonStatus.NOT_APPLICABLE
    assert handoff.delta is None
    assert handoff.current_score == 100


def test_new_failure_is_detected() -> None:
    new_failures, resolved, persistent = diff_failures(
        [result(failures=[])],
        [result(failures=[failure(title="Newly introduced")])],
    )
    assert len(new_failures) == 1
    assert new_failures[0].failure.title == "Newly introduced"
    assert resolved == []
    assert persistent == []


def test_resolved_failure_is_detected() -> None:
    new_failures, resolved, persistent = diff_failures(
        [result(failures=[failure(title="Fixed now")])],
        [result(failures=[])],
    )
    assert resolved[0].failure.title == "Fixed now"
    assert new_failures == []
    assert persistent == []


def test_persistent_failure_is_detected() -> None:
    shared = failure(title="Still broken")
    new_failures, resolved, persistent = diff_failures(
        [result(failures=[shared])],
        [result(failures=[shared])],
    )
    assert persistent[0].failure.title == "Still broken"
    assert new_failures == []
    assert resolved == []


def test_failure_identity_ignores_turn_number() -> None:
    baseline_failure = failure(title="Same regression", turn=2)
    current_failure = failure(title="Same regression", turn=5)
    new_failures, resolved, persistent = diff_failures(
        [result(failures=[baseline_failure])],
        [result(failures=[current_failure])],
    )
    assert persistent
    assert new_failures == []
    assert resolved == []


def test_failure_identity_is_scoped_per_scenario() -> None:
    same_shape_failure = failure(title="Missing document")
    new_failures, resolved, persistent = diff_failures(
        [result("INS-001", failures=[same_shape_failure])],
        [result("INS-002", failures=[same_shape_failure])],
    )
    assert len(new_failures) == 1
    assert new_failures[0].scenario_id == "INS-002"
    assert len(resolved) == 1
    assert resolved[0].scenario_id == "INS-001"
    assert persistent == []
