"""Semantic shadow output must never reach deterministic release authority.

Every test here holds the deterministic input fixed and varies only the semantic
report, then asserts the deterministic-derived artifacts are byte-identical.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.agent_adapters import DemoAgentAdapter
from app.metrics import MetricDimension, MetricScore, MetricStatus
from app.models import AgentMode, AgentTarget
from app.readiness import build_release_readiness
from app.regression import build_comparison, run_score
from app.scenario_runner import RunStatus, ScenarioRunner, ScenarioRunResult
from app.scenarios import Severity, load_scenario_by_id
from app.semantic_judge import (
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticExpectationType,
    SemanticJudgeCheck,
    SemanticJudgeRequest,
    SemanticVerdict,
)
from app.test_runs import (
    RunAggregateCounts,
)
from app.test_runs import (
    TestRunLifecycleStatus as LifecycleStatus,
)
from app.test_runs import (
    TestRunSummary as RunSummary,
)
from app.trends import build_run_trends, trend_input_from_results

SEMANTIC_VARIANTS = ("absent", "pass", "fail", "uncertain", "error")


class StaticSemanticJudge:
    """Fake judge with no provider dependency, used to force one semantic outcome."""

    provider = "fake"
    model = "fake-judge-1"

    def __init__(self, report: SemanticEvaluationReport) -> None:
        self._report = report

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        return self._report


class ExplodingSemanticJudge:
    provider = "fake"
    model = "fake-judge-1"

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        raise RuntimeError("provider internals that must not leak")


class SlowSemanticJudge:
    provider = "fake"
    model = "fake-judge-1"

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        await asyncio.sleep(5)
        raise AssertionError("Semantic judge should have been cancelled by the timeout")


def semantic_report(variant: str) -> SemanticEvaluationReport | None:
    if variant == "absent":
        return None
    if variant == "error":
        return SemanticEvaluationReport.failed("Semantic evaluation failed.")
    verdict = {
        "pass": SemanticVerdict.PASS,
        "fail": SemanticVerdict.FAIL,
        "uncertain": SemanticVerdict.UNCERTAIN,
    }[variant]
    return SemanticEvaluationReport(
        status=SemanticEvaluationStatus.COMPLETED,
        provider="fake",
        model="fake-judge-1",
        checks=[
            SemanticJudgeCheck(
                expectation_id="e1",
                type=SemanticExpectationType.UNSUPPORTED_PROMISE,
                verdict=verdict,
                reason="advisory rationale",
                assistant_turns=[],
            )
        ],
    )


def scenario_result(
    variant: str,
    *,
    scenario_id: str = "INS-002",
    status: RunStatus = RunStatus.PASS,
    severity: Severity | None = None,
    goal_score: int = 90,
) -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        agent_label="agent",
        status=status,
        severity=severity,
        turns_executed=2,
        metrics=[
            MetricScore(
                dimension=MetricDimension.GOAL_COMPLETION,
                score=goal_score,
                status=MetricStatus.PASS,
                reason="deterministic",
            )
        ],
        semantic_evaluation=semantic_report(variant),
    )


def run_summary(run_id: UUID) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        pack_id="insurance-v1",
        pack_name="Insurance Reliability Pack v1",
        agent_target=AgentTarget.BUILT_IN_DEMO,
        agent_mode=AgentMode.HEALTHY,
        agent_label="agent",
        agent_version=None,
        lifecycle_status=LifecycleStatus.COMPLETED,
        aggregate=RunAggregateCounts(total=1, passed=1, failed=0, errors=0),
        completed_scenarios=1,
        total_scenarios=1,
        is_baseline=False,
        created_at=datetime.now(UTC),
    )


def stable_checks(result: ScenarioRunResult) -> list[tuple[object, ...]]:
    """Check identity without per-run tool-event UUIDs or timestamps."""

    return [
        (
            check.check_id,
            check.type,
            check.status,
            check.category,
            check.severity,
            check.reason,
            check.evidence.expected_tool,
            check.evidence.argument_name,
            check.evidence.actual_values,
        )
        for check in result.checks
    ]


def deterministic_fingerprint(
    results: list[ScenarioRunResult],
) -> tuple[object, ...]:
    """Everything downstream of deterministic evaluation, excluding semantic output."""

    run_id = UUID("00000000-0000-0000-0000-0000000000aa")
    baseline_id = UUID("00000000-0000-0000-0000-0000000000bb")
    baseline = [scenario_result("absent")]

    readiness = build_release_readiness(run_summary(run_id), results, None)
    comparison = build_comparison(
        baseline_run_id=baseline_id,
        current_run_id=run_id,
        pack_id="insurance-v1",
        baseline_results=baseline,
        current_results=results,
    )
    trend_input = trend_input_from_results(
        run_id=run_id,
        pack_id="insurance-v1",
        agent_label="agent",
        agent_version=None,
        lifecycle_status=LifecycleStatus.COMPLETED,
        created_at="2026-01-01T00:00:00Z",
        is_baseline=False,
        results=results,
    )
    trends = build_run_trends("insurance-v1", [trend_input])

    return (
        readiness.verdict,
        tuple(
            (reason.code, reason.level, reason.title, reason.detail)
            for reason in readiness.reasons
        ),
        run_score(results),
        comparison.status,
        comparison.score_delta,
        comparison.baseline_score,
        comparison.current_score,
        tuple(change.model_dump_json() for change in comparison.metric_changes),
        tuple(entry.model_dump_json() for entry in comparison.new_failures),
        tuple(entry.model_dump_json() for entry in comparison.resolved_failures),
        tuple(entry.model_dump_json() for entry in comparison.persistent_failures),
        trend_input.goal_scores,
        trend_input.statuses,
        trend_input.severities,
        trend_input.critical_failure_keys,
        tuple(point.model_dump_json() for point in trends.points),
        tuple(result.status for result in results),
        tuple(result.severity for result in results),
        tuple(check.model_dump_json() for result in results for check in result.checks),
        tuple(failure.model_dump_json() for result in results for failure in result.failures),
        tuple(metric.model_dump_json() for result in results for metric in result.metrics),
    )


def test_semantic_variants_produce_identical_deterministic_artifacts_on_pass() -> None:
    fingerprints = {
        variant: deterministic_fingerprint([scenario_result(variant)])
        for variant in SEMANTIC_VARIANTS
    }

    assert len(set(map(str, fingerprints.values()))) == 1, fingerprints


def test_semantic_variants_produce_identical_deterministic_artifacts_on_fail() -> None:
    fingerprints = {
        variant: deterministic_fingerprint(
            [
                scenario_result(
                    variant,
                    status=RunStatus.FAIL,
                    severity=Severity.CRITICAL,
                    goal_score=40,
                )
            ]
        )
        for variant in SEMANTIC_VARIANTS
    }

    assert len(set(map(str, fingerprints.values()))) == 1, fingerprints


def test_semantic_fail_never_downgrades_a_ready_verdict() -> None:
    ready = build_release_readiness(
        run_summary(uuid4()), [scenario_result("absent")], None
    )
    with_semantic_fail = build_release_readiness(
        run_summary(uuid4()), [scenario_result("fail")], None
    )

    assert ready.verdict is with_semantic_fail.verdict
    assert [reason.code for reason in ready.reasons] == [
        reason.code for reason in with_semantic_fail.reasons
    ]


@pytest.mark.parametrize("variant", ["pass", "fail", "uncertain", "error"])
def test_semantic_verdicts_do_not_change_scenario_status_end_to_end(variant: str) -> None:
    scenario = load_scenario_by_id("INS-002")
    judge = StaticSemanticJudge(semantic_report(variant) or SemanticEvaluationReport.disabled())

    baseline = asyncio.run(ScenarioRunner().run(scenario, DemoAgentAdapter(AgentMode.HEALTHY)))
    with_semantic = asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(scenario, DemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert baseline.status is with_semantic.status
    assert baseline.severity == with_semantic.severity
    assert stable_checks(baseline) == stable_checks(with_semantic)
    assert [failure.model_dump_json() for failure in baseline.failures] == [
        failure.model_dump_json() for failure in with_semantic.failures
    ]
    assert [metric.model_dump_json() for metric in baseline.metrics] == [
        metric.model_dump_json() for metric in with_semantic.metrics
    ]
    assert [turn.content for turn in baseline.transcript] == [
        turn.content for turn in with_semantic.transcript
    ]
    assert [event.tool for event in baseline.tool_trace] == [
        event.tool for event in with_semantic.tool_trace
    ]
    assert with_semantic.error is None


def test_semantic_provider_exception_is_contained_as_semantic_error() -> None:
    scenario = load_scenario_by_id("INS-002")

    result = asyncio.run(
        ScenarioRunner(semantic_judge=ExplodingSemanticJudge()).run(
            scenario, DemoAgentAdapter(AgentMode.HEALTHY)
        )
    )

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert "provider internals" not in (result.semantic_evaluation.error or "")


def test_semantic_timeout_leaves_the_deterministic_run_intact() -> None:
    scenario = load_scenario_by_id("INS-002")

    result = asyncio.run(
        ScenarioRunner(
            semantic_judge=SlowSemanticJudge(), semantic_timeout_seconds=0.01
        ).run(scenario, DemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR


def test_scenario_without_semantic_expectations_reports_no_semantic_evaluation() -> None:
    scenario = load_scenario_by_id("INS-001")
    assert not scenario.semantic_expectations

    judge = StaticSemanticJudge(
        semantic_report("fail") or SemanticEvaluationReport.disabled()
    )
    result = asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(scenario, DemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert result.semantic_evaluation is None
    assert result.status is RunStatus.PASS


def test_semantic_disabled_when_no_provider_is_configured() -> None:
    scenario = load_scenario_by_id("INS-002")

    result = asyncio.run(ScenarioRunner().run(scenario, DemoAgentAdapter(AgentMode.HEALTHY)))

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.DISABLED
    assert result.semantic_evaluation.advisory_only is True
    assert result.semantic_evaluation.mode == "shadow"
