"""Deterministic baseline/regression comparison, built entirely on top of the
existing per-scenario `metrics` and `failures` (see metrics.py / failures.py).

No parallel scoring or failure system is introduced here - this module only
aggregates and diffs data the evaluator already produced.
"""

from enum import StrEnum
from statistics import mean
from uuid import UUID

from app.failures import Failure
from app.metrics import MetricDimension
from app.models import StrictModel
from app.scenario_runner import ScenarioRunResult
from app.scenarios import Severity

REGRESSION_THRESHOLD = 5


class RegressionStatus(StrEnum):
    IMPROVED = "improved"
    STABLE = "stable"
    REGRESSION = "regression"


class MetricComparisonStatus(StrEnum):
    IMPROVED = "improved"
    STABLE = "stable"
    REGRESSED = "regressed"
    NOT_APPLICABLE = "not_applicable"


class MetricComparison(StrictModel):
    dimension: MetricDimension
    baseline_score: int | None
    current_score: int | None
    delta: int | None
    status: MetricComparisonStatus


class ScenarioFailure(StrictModel):
    scenario_id: str
    failure: Failure


class RegressionComparison(StrictModel):
    baseline_run_id: UUID
    current_run_id: UUID
    pack_id: str
    baseline_score: int
    current_score: int
    score_delta: int
    status: RegressionStatus
    metric_changes: list[MetricComparison]
    new_failures: list[ScenarioFailure]
    resolved_failures: list[ScenarioFailure]
    persistent_failures: list[ScenarioFailure]


class ComparisonAvailability(StrEnum):
    NO_BASELINE = "no_baseline"
    IS_BASELINE = "is_baseline"
    INCOMPATIBLE = "incompatible"
    AVAILABLE = "available"


class RegressionComparisonResponse(StrictModel):
    status: ComparisonAvailability
    comparison: RegressionComparison | None = None


def _scenario_goal_score(result: ScenarioRunResult) -> int:
    """A scenario always contributes a 0-100 score: errored/unevaluated scenarios
    count as 0, since an unevaluated scenario is at least as bad a reliability
    signal as a fully failed one."""

    goal = next(
        (
            metric
            for metric in result.metrics
            if metric.dimension is MetricDimension.GOAL_COMPLETION
        ),
        None,
    )
    if goal is not None and goal.score is not None:
        return goal.score
    return 0


def run_score(results: list[ScenarioRunResult]) -> int:
    if not results:
        return 0
    return round(mean(_scenario_goal_score(result) for result in results))


def _dimension_score(results: list[ScenarioRunResult], dimension: MetricDimension) -> int | None:
    scores = [
        metric.score
        for result in results
        for metric in result.metrics
        if metric.dimension is dimension and metric.score is not None
    ]
    if not scores:
        return None
    return round(mean(scores))


def _metric_status(delta: int | None) -> MetricComparisonStatus:
    if delta is None:
        return MetricComparisonStatus.NOT_APPLICABLE
    if delta >= REGRESSION_THRESHOLD:
        return MetricComparisonStatus.IMPROVED
    if delta <= -REGRESSION_THRESHOLD:
        return MetricComparisonStatus.REGRESSED
    return MetricComparisonStatus.STABLE


def compare_metrics(
    baseline_results: list[ScenarioRunResult],
    current_results: list[ScenarioRunResult],
) -> list[MetricComparison]:
    comparisons: list[MetricComparison] = []
    for dimension in MetricDimension:
        baseline_score = _dimension_score(baseline_results, dimension)
        current_score = _dimension_score(current_results, dimension)
        # A missing score on either side can't produce a meaningful delta - report
        # not_applicable rather than treating the missing side as zero.
        if baseline_score is None or current_score is None:
            comparisons.append(
                MetricComparison(
                    dimension=dimension,
                    baseline_score=baseline_score,
                    current_score=current_score,
                    delta=None,
                    status=MetricComparisonStatus.NOT_APPLICABLE,
                )
            )
            continue
        delta = current_score - baseline_score
        comparisons.append(
            MetricComparison(
                dimension=dimension,
                baseline_score=baseline_score,
                current_score=current_score,
                delta=delta,
                status=_metric_status(delta),
            )
        )
    return comparisons


def _fingerprint(scenario_id: str, failure: Failure) -> str:
    # Turn number is deliberately excluded: the same regression recurring a turn
    # later due to an unrelated conversation change should still count as the
    # same failure, not a new one.
    return f"{scenario_id}:{failure.type.value}:{failure.title}"


def _index_failures(results: list[ScenarioRunResult]) -> dict[str, ScenarioFailure]:
    return {
        _fingerprint(result.scenario_id, failure): ScenarioFailure(
            scenario_id=result.scenario_id, failure=failure
        )
        for result in results
        for failure in result.failures
    }


def diff_failures(
    baseline_results: list[ScenarioRunResult],
    current_results: list[ScenarioRunResult],
) -> tuple[list[ScenarioFailure], list[ScenarioFailure], list[ScenarioFailure]]:
    baseline_index = _index_failures(baseline_results)
    current_index = _index_failures(current_results)

    new_failures = [current_index[key] for key in current_index.keys() - baseline_index.keys()]
    resolved_failures = [
        baseline_index[key] for key in baseline_index.keys() - current_index.keys()
    ]
    persistent_failures = [
        current_index[key] for key in current_index.keys() & baseline_index.keys()
    ]
    return new_failures, resolved_failures, persistent_failures


def _has_new_critical_failure(new_failures: list[ScenarioFailure]) -> bool:
    return any(entry.failure.severity is Severity.CRITICAL for entry in new_failures)


def compute_regression_status(score_delta: int, has_new_critical_failure: bool) -> RegressionStatus:
    if has_new_critical_failure:
        return RegressionStatus.REGRESSION
    if score_delta >= REGRESSION_THRESHOLD:
        return RegressionStatus.IMPROVED
    if score_delta <= -REGRESSION_THRESHOLD:
        return RegressionStatus.REGRESSION
    return RegressionStatus.STABLE


def build_comparison(
    *,
    baseline_run_id: UUID,
    current_run_id: UUID,
    pack_id: str,
    baseline_results: list[ScenarioRunResult],
    current_results: list[ScenarioRunResult],
) -> RegressionComparison:
    baseline_score = run_score(baseline_results)
    current_score = run_score(current_results)
    score_delta = current_score - baseline_score
    new_failures, resolved_failures, persistent_failures = diff_failures(
        baseline_results, current_results
    )
    status = compute_regression_status(score_delta, _has_new_critical_failure(new_failures))

    return RegressionComparison(
        baseline_run_id=baseline_run_id,
        current_run_id=current_run_id,
        pack_id=pack_id,
        baseline_score=baseline_score,
        current_score=current_score,
        score_delta=score_delta,
        status=status,
        metric_changes=compare_metrics(baseline_results, current_results),
        new_failures=new_failures,
        resolved_failures=resolved_failures,
        persistent_failures=persistent_failures,
    )
