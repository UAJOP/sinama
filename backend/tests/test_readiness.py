import asyncio

from app.models import AgentMode
from app.readiness import (
    ReadinessReasonCode,
    ReadinessReasonLevel,
    ReleaseReadinessVerdict,
    build_release_readiness,
)
from app.regression import ComparisonAvailability, RegressionComparisonResponse
from app.scenario_packs import scenario_pack_registry
from app.scenarios import Severity
from app.test_runs import InMemoryRunStore, RunService


async def execute(
    store: InMemoryRunStore,
    mode: AgentMode,
    version: str | None = None,
):
    service = RunService(store=store)
    created = await service.create_run("insurance-v1", mode, agent_version=version)
    return await service.wait_for_completion(created.run_id)


def full_results(store: InMemoryRunStore, run_id):  # type: ignore[no-untyped-def]
    summaries = store.get_results(run_id).results
    return [store.get_result(run_id, item.scenario_id) for item in summaries]


def test_queued_run_is_blocked_until_execution_finishes() -> None:
    store = InMemoryRunStore()
    pack = scenario_pack_registry.get_pack("insurance-v1")
    run = store.create_run(pack, AgentMode.HEALTHY)

    readiness = build_release_readiness(run, [], None)

    assert readiness.verdict is ReleaseReadinessVerdict.BLOCKED
    assert [reason.code for reason in readiness.reasons] == [
        ReadinessReasonCode.RUN_NOT_COMPLETED
    ]


def test_orchestration_error_run_is_blocked() -> None:
    store = InMemoryRunStore()
    pack = scenario_pack_registry.get_pack("insurance-v1")
    created = store.create_run(pack, AgentMode.HEALTHY)
    store.mark_error(created.run_id, "worker stopped")
    run = store.get_run(created.run_id)

    readiness = build_release_readiness(run, [], None)

    assert readiness.verdict is ReleaseReadinessVerdict.BLOCKED
    assert readiness.reasons[0].code is ReadinessReasonCode.RUN_EXECUTION_ERROR
    assert "worker stopped" in readiness.reasons[0].detail


def test_clean_completed_run_without_baseline_is_warning() -> None:
    store = InMemoryRunStore()
    run = asyncio.run(execute(store, AgentMode.HEALTHY, "v1"))

    readiness = build_release_readiness(
        run,
        full_results(store, run.run_id),
        store.get_comparison(run.run_id),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.WARNING
    assert readiness.comparison_status is ComparisonAvailability.NO_BASELINE
    assert [reason.code for reason in readiness.reasons] == [
        ReadinessReasonCode.NO_BASELINE_COMPARISON
    ]


def test_clean_baseline_run_is_ready() -> None:
    store = InMemoryRunStore()
    run = asyncio.run(execute(store, AgentMode.HEALTHY, "v1"))
    baseline = store.set_baseline(run.run_id)

    readiness = build_release_readiness(
        baseline,
        full_results(store, run.run_id),
        store.get_comparison(run.run_id),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.READY
    assert readiness.comparison_status is ComparisonAvailability.IS_BASELINE
    assert readiness.reasons == []


def test_broken_run_is_blocked_by_high_failures_and_regression() -> None:
    store = InMemoryRunStore()
    baseline = asyncio.run(execute(store, AgentMode.HEALTHY, "v1"))
    store.set_baseline(baseline.run_id)
    broken = asyncio.run(execute(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, "v2"))

    readiness = build_release_readiness(
        broken,
        full_results(store, broken.run_id),
        store.get_comparison(broken.run_id),
    )

    codes = {reason.code for reason in readiness.reasons}
    assert readiness.verdict is ReleaseReadinessVerdict.BLOCKED
    assert ReadinessReasonCode.HIGH_FAILURE in codes
    assert ReadinessReasonCode.REGRESSION_DETECTED in codes
    assert readiness.regression_status is not None


def test_medium_low_failures_are_warning_not_blocker() -> None:
    store = InMemoryRunStore()
    broken = asyncio.run(execute(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, "v1"))
    results = full_results(store, broken.run_id)
    adjusted = []
    for result in results:
        failures = [
            failure.model_copy(update={"severity": Severity.MEDIUM})
            for failure in result.failures
        ]
        adjusted.append(
            result.model_copy(
                update={
                    "severity": Severity.MEDIUM if failures else result.severity,
                    "failures": failures,
                }
            )
        )

    readiness = build_release_readiness(
        broken,
        adjusted,
        RegressionComparisonResponse(status=ComparisonAvailability.NO_BASELINE),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.WARNING
    assert any(
        reason.code is ReadinessReasonCode.NON_BLOCKING_FAILURE
        and reason.level is ReadinessReasonLevel.WARNING
        for reason in readiness.reasons
    )
    assert not any(reason.level is ReadinessReasonLevel.BLOCKER for reason in readiness.reasons)


def test_critical_failure_is_always_blocking() -> None:
    store = InMemoryRunStore()
    broken = asyncio.run(execute(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, "v1"))
    results = full_results(store, broken.run_id)
    result = next(item for item in results if item.failures)
    critical_failure = result.failures[0].model_copy(update={"severity": Severity.CRITICAL})
    adjusted = [
        item.model_copy(
            update={
                "severity": Severity.CRITICAL,
                "failures": [critical_failure, *item.failures[1:]],
            }
        )
        if item.scenario_id == result.scenario_id
        else item
        for item in results
    ]

    readiness = build_release_readiness(
        broken,
        adjusted,
        RegressionComparisonResponse(status=ComparisonAvailability.NO_BASELINE),
    )

    assert readiness.verdict is ReleaseReadinessVerdict.BLOCKED
    assert ReadinessReasonCode.CRITICAL_FAILURE in {
        reason.code for reason in readiness.reasons
    }
