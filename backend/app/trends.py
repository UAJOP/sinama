from dataclasses import dataclass
from statistics import mean
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from app.models import StrictModel
from app.regression import RegressionStatus, compute_regression_status
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.scenarios import Severity

TrendLifecycleStatus = Literal["completed", "error"]


class TrendOutcomeCounts(StrictModel):
    total: int
    passed: int
    failed: int
    errors: int


class TrendSeverityCounts(StrictModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class RunTrendPoint(StrictModel):
    run_id: UUID
    pack_id: str
    agent_label: str
    agent_version: str | None
    lifecycle_status: TrendLifecycleStatus
    created_at: str
    is_baseline: bool
    score: int | None
    outcomes: TrendOutcomeCounts
    severities: TrendSeverityCounts
    reference_run_id: UUID | None = None
    score_delta: int | None = None
    direction: RegressionStatus | None = None


class RunTrendResponse(StrictModel):
    pack_id: str
    points: list[RunTrendPoint]


@dataclass(frozen=True)
class TrendRunInput:
    run_id: UUID
    pack_id: str
    agent_label: str
    agent_version: str | None
    lifecycle_status: TrendLifecycleStatus
    created_at: str
    is_baseline: bool
    scenario_ids: tuple[str, ...]
    statuses: tuple[RunStatus, ...]
    goal_scores: tuple[int, ...]
    severities: tuple[Severity, ...]
    critical_failure_keys: frozenset[str]


@runtime_checkable
class TrendStore(Protocol):
    def list_trends(self, pack_id: str, limit: int = 20) -> RunTrendResponse: ...


def trend_input_from_results(
    *,
    run_id: UUID,
    pack_id: str,
    agent_label: str,
    agent_version: str | None,
    lifecycle_status: TrendLifecycleStatus,
    created_at: str,
    is_baseline: bool,
    results: list[ScenarioRunResult],
) -> TrendRunInput:
    from app.regression import critical_failure_fingerprints, scenario_goal_score

    critical_keys: set[str] = set()
    for result in results:
        critical_keys.update(critical_failure_fingerprints(result))

    return TrendRunInput(
        run_id=run_id,
        pack_id=pack_id,
        agent_label=agent_label,
        agent_version=agent_version,
        lifecycle_status=lifecycle_status,
        created_at=created_at,
        is_baseline=is_baseline,
        scenario_ids=tuple(result.scenario_id for result in results),
        statuses=tuple(result.status for result in results),
        goal_scores=tuple(scenario_goal_score(result) for result in results),
        severities=tuple(result.severity for result in results if result.severity is not None),
        critical_failure_keys=frozenset(critical_keys),
    )


def _outcomes(statuses: tuple[RunStatus, ...]) -> TrendOutcomeCounts:
    return TrendOutcomeCounts(
        total=len(statuses),
        passed=sum(status is RunStatus.PASS for status in statuses),
        failed=sum(status is RunStatus.FAIL for status in statuses),
        errors=sum(status is RunStatus.ERROR for status in statuses),
    )


def _severity_counts(severities: tuple[Severity, ...]) -> TrendSeverityCounts:
    return TrendSeverityCounts(
        critical=sum(severity is Severity.CRITICAL for severity in severities),
        high=sum(severity is Severity.HIGH for severity in severities),
        medium=sum(severity is Severity.MEDIUM for severity in severities),
        low=sum(severity is Severity.LOW for severity in severities),
    )


def _score(run: TrendRunInput) -> int | None:
    if run.lifecycle_status != "completed":
        return None
    if not run.goal_scores:
        return 0
    return round(mean(run.goal_scores))


def _compatible(reference: TrendRunInput, current: TrendRunInput) -> bool:
    return reference.pack_id == current.pack_id and reference.scenario_ids == current.scenario_ids


def build_run_trends(pack_id: str, runs: list[TrendRunInput]) -> RunTrendResponse:
    ordered = sorted(runs, key=lambda run: (run.created_at, str(run.run_id)))
    points: list[RunTrendPoint] = []
    completed_history: list[tuple[TrendRunInput, int]] = []

    for run in ordered:
        score = _score(run)
        reference_run_id: UUID | None = None
        score_delta: int | None = None
        direction: RegressionStatus | None = None

        if score is not None:
            reference = next(
                (
                    (prior_run, prior_score)
                    for prior_run, prior_score in reversed(completed_history)
                    if _compatible(prior_run, run)
                ),
                None,
            )
            if reference is not None:
                prior_run, prior_score = reference
                score_delta = score - prior_score
                reference_run_id = prior_run.run_id
                has_new_critical = bool(
                    run.critical_failure_keys - prior_run.critical_failure_keys
                )
                direction = compute_regression_status(score_delta, has_new_critical)
            completed_history.append((run, score))

        points.append(
            RunTrendPoint(
                run_id=run.run_id,
                pack_id=run.pack_id,
                agent_label=run.agent_label,
                agent_version=run.agent_version,
                lifecycle_status=run.lifecycle_status,
                created_at=run.created_at,
                is_baseline=run.is_baseline,
                score=score,
                outcomes=_outcomes(run.statuses),
                severities=_severity_counts(run.severities),
                reference_run_id=reference_run_id,
                score_delta=score_delta,
                direction=direction,
            )
        )

    return RunTrendResponse(pack_id=pack_id, points=points)
