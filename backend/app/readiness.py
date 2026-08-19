from enum import StrEnum
from uuid import UUID

from app.evaluator import EvaluationCheckType
from app.models import StrictModel
from app.regression import (
    ComparisonAvailability,
    RegressionComparisonResponse,
    RegressionStatus,
)
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.scenarios import Severity
from app.test_runs import TestRunLifecycleStatus, TestRunSummary


class ReleaseReadinessVerdict(StrEnum):
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"


class ReadinessReasonLevel(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class ReadinessReasonCode(StrEnum):
    RUN_NOT_COMPLETED = "run_not_completed"
    RUN_EXECUTION_ERROR = "run_execution_error"
    SCENARIO_EXECUTION_ERROR = "scenario_execution_error"
    CRITICAL_FAILURE = "critical_failure"
    HIGH_FAILURE = "high_failure"
    NON_BLOCKING_FAILURE = "non_blocking_failure"
    REGRESSION_DETECTED = "regression_detected"
    NO_BASELINE_COMPARISON = "no_baseline_comparison"
    INCOMPATIBLE_BASELINE = "incompatible_baseline"


class ReadinessReason(StrictModel):
    code: ReadinessReasonCode
    level: ReadinessReasonLevel
    title: str
    detail: str
    scenario_id: str | None = None
    failure_type: EvaluationCheckType | None = None
    failure_severity: Severity | None = None


class ReleaseReadinessResponse(StrictModel):
    run_id: UUID
    verdict: ReleaseReadinessVerdict
    reasons: list[ReadinessReason]
    comparison_status: ComparisonAvailability | None = None
    regression_status: RegressionStatus | None = None


def _failure_reason(result: ScenarioRunResult, failure_index: int) -> ReadinessReason:
    failure = result.failures[failure_index]
    if failure.severity is Severity.CRITICAL:
        code = ReadinessReasonCode.CRITICAL_FAILURE
        level = ReadinessReasonLevel.BLOCKER
        title = "Critical deterministic failure"
    elif failure.severity is Severity.HIGH:
        code = ReadinessReasonCode.HIGH_FAILURE
        level = ReadinessReasonLevel.BLOCKER
        title = "High-severity deterministic failure"
    else:
        code = ReadinessReasonCode.NON_BLOCKING_FAILURE
        level = ReadinessReasonLevel.WARNING
        title = "Non-blocking deterministic failure"

    return ReadinessReason(
        code=code,
        level=level,
        title=title,
        detail=failure.description,
        scenario_id=result.scenario_id,
        failure_type=failure.type,
        failure_severity=failure.severity,
    )


def _comparison_reasons(
    comparison_response: RegressionComparisonResponse,
) -> tuple[list[ReadinessReason], RegressionStatus | None]:
    if comparison_response.status is ComparisonAvailability.NO_BASELINE:
        return (
            [
                ReadinessReason(
                    code=ReadinessReasonCode.NO_BASELINE_COMPARISON,
                    level=ReadinessReasonLevel.WARNING,
                    title="No baseline comparison",
                    detail=(
                        "This run has no compatible baseline comparison, so release readiness "
                        "is based on absolute deterministic evidence only."
                    ),
                )
            ],
            None,
        )

    if comparison_response.status is ComparisonAvailability.INCOMPATIBLE:
        return (
            [
                ReadinessReason(
                    code=ReadinessReasonCode.INCOMPATIBLE_BASELINE,
                    level=ReadinessReasonLevel.WARNING,
                    title="Baseline is incompatible",
                    detail=(
                        "The configured baseline uses a different scenario snapshot and cannot "
                        "provide regression evidence for this run."
                    ),
                )
            ],
            None,
        )

    comparison = comparison_response.comparison
    if comparison is None:
        return [], None

    if comparison.status is RegressionStatus.REGRESSION:
        return (
            [
                ReadinessReason(
                    code=ReadinessReasonCode.REGRESSION_DETECTED,
                    level=ReadinessReasonLevel.BLOCKER,
                    title="Reliability regression detected",
                    detail=(
                        f"The current run moved {comparison.score_delta:+d} points versus the "
                        "baseline or introduced a new critical failure."
                    ),
                )
            ],
            comparison.status,
        )

    return [], comparison.status


def build_release_readiness(
    run: TestRunSummary,
    results: list[ScenarioRunResult],
    comparison_response: RegressionComparisonResponse | None,
) -> ReleaseReadinessResponse:
    reasons: list[ReadinessReason] = []
    regression_status: RegressionStatus | None = None
    comparison_status = comparison_response.status if comparison_response is not None else None

    if run.lifecycle_status is TestRunLifecycleStatus.ERROR:
        reasons.append(
            ReadinessReason(
                code=ReadinessReasonCode.RUN_EXECUTION_ERROR,
                level=ReadinessReasonLevel.BLOCKER,
                title="Run execution failed",
                detail=(
                    run.error.reason
                    if run.error is not None
                    else "The test run ended with an orchestration error."
                ),
            )
        )
    elif run.lifecycle_status is not TestRunLifecycleStatus.COMPLETED:
        reasons.append(
            ReadinessReason(
                code=ReadinessReasonCode.RUN_NOT_COMPLETED,
                level=ReadinessReasonLevel.BLOCKER,
                title="Run is not complete",
                detail="Release readiness is blocked until the test run reaches a terminal state.",
            )
        )

    for result in results:
        if result.status is RunStatus.ERROR:
            reasons.append(
                ReadinessReason(
                    code=ReadinessReasonCode.SCENARIO_EXECUTION_ERROR,
                    level=ReadinessReasonLevel.BLOCKER,
                    title="Scenario could not be evaluated",
                    detail=(
                        result.error.reason
                        if result.error is not None
                        else "A scenario ended with an execution error."
                    ),
                    scenario_id=result.scenario_id,
                )
            )
        for index in range(len(result.failures)):
            reasons.append(_failure_reason(result, index))

    if run.lifecycle_status is TestRunLifecycleStatus.COMPLETED and comparison_response is not None:
        comparison_reasons, regression_status = _comparison_reasons(comparison_response)
        reasons.extend(comparison_reasons)

    has_blocker = any(reason.level is ReadinessReasonLevel.BLOCKER for reason in reasons)
    has_warning = any(reason.level is ReadinessReasonLevel.WARNING for reason in reasons)
    verdict = (
        ReleaseReadinessVerdict.BLOCKED
        if has_blocker
        else ReleaseReadinessVerdict.WARNING
        if has_warning
        else ReleaseReadinessVerdict.READY
    )

    return ReleaseReadinessResponse(
        run_id=run.run_id,
        verdict=verdict,
        reasons=reasons,
        comparison_status=comparison_status,
        regression_status=regression_status,
    )
