"""Historical persisted results predate the semantic fields and must stay readable.

Semantic data is stored inside the existing ScenarioRunResult JSON payload, so these
tests assert the additive field never breaks older records or downstream consumers.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db.sql_run_store import SqlRunStore
from app.metrics import MetricDimension, MetricScore, MetricStatus
from app.models import AgentMode, AgentTarget
from app.readiness import build_release_readiness
from app.regression import build_comparison, run_score
from app.scenario_packs import ScenarioPackRegistry
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.semantic_judge import (
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticExpectationType,
    SemanticJudgeCheck,
    SemanticVerdict,
)
from app.test_runs import InMemoryRunStore
from app.test_runs import (
    TestRunLifecycleStatus as LifecycleStatus,
)
from app.test_runs import (
    TestRunSummary as RunSummary,
)
from app.trends import build_run_trends, trend_input_from_results

LEGACY_RESULT_PAYLOAD: dict[str, object] = {
    "scenario_id": "INS-001",
    "scenario_version": "1.0.0",
    "agent_label": "healthy",
    "status": "pass",
    "severity": None,
    "evaluation_scope": "deterministic_tool_contract",
    "checks": [],
    "declared_checks": ["lookup_policy_called_with_expected_policy_id"],
    "unscored_declared_checks": ["lookup_policy_called_with_expected_policy_id"],
    "transcript": [{"sequence": 1, "role": "user", "content": "Merhaba"}],
    "tool_trace": [],
    "turns_executed": 1,
    "unscored_expectations": [],
    "metrics": [
        {
            "dimension": "goal_completion",
            "score": 100,
            "status": "pass",
            "reason": "1/1 deterministic checks passed.",
        }
    ],
    "failures": [],
    "error": None,
}


def semantic_result(scenario_id: str = "INS-002") -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        agent_label="healthy",
        status=RunStatus.PASS,
        turns_executed=1,
        metrics=[
            MetricScore(
                dimension=MetricDimension.GOAL_COMPLETION,
                score=100,
                status=MetricStatus.PASS,
                reason="deterministic",
            )
        ],
        semantic_evaluation=SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider="openai",
            model="gpt-5.4-nano",
            checks=[
                SemanticJudgeCheck(
                    expectation_id="no_unsupported_payment_guarantee",
                    type=SemanticExpectationType.UNSUPPORTED_PROMISE,
                    verdict=SemanticVerdict.FAIL,
                    reason="advisory",
                    assistant_turns=[2],
                )
            ],
        ),
    )


def test_legacy_payload_without_semantic_fields_still_deserializes() -> None:
    result = ScenarioRunResult.model_validate(LEGACY_RESULT_PAYLOAD)

    assert result.scenario_id == "INS-001"
    assert result.status is RunStatus.PASS
    assert result.semantic_evaluation is None


def test_legacy_payload_survives_a_serialization_round_trip() -> None:
    result = ScenarioRunResult.model_validate(LEGACY_RESULT_PAYLOAD)

    round_tripped = ScenarioRunResult.model_validate(json.loads(result.model_dump_json()))

    assert round_tripped.semantic_evaluation is None
    assert round_tripped.model_dump_json() == result.model_dump_json()


def test_sql_store_result_loader_accepts_legacy_payloads() -> None:
    loaded = SqlRunStore._load_result(dict(LEGACY_RESULT_PAYLOAD))

    assert loaded.scenario_id == "INS-001"
    assert loaded.semantic_evaluation is None


def test_sql_store_result_loader_round_trips_semantic_payloads() -> None:
    stored = semantic_result().model_dump(mode="json")

    loaded = SqlRunStore._load_result(stored)

    assert loaded.semantic_evaluation is not None
    assert loaded.semantic_evaluation.checks[0].verdict is SemanticVerdict.FAIL
    assert loaded.semantic_evaluation.advisory_only is True


def test_memory_store_preserves_semantic_payloads_as_immutable_copies() -> None:
    store = InMemoryRunStore()
    pack = ScenarioPackRegistry().get_pack("insurance-v1")
    run = store.create_run(pack, AgentMode.HEALTHY)
    store.mark_running(run.run_id)
    store.add_result(run.run_id, semantic_result())
    store.mark_completed(run.run_id)

    first = store.get_result(run.run_id, "INS-002")
    assert first.semantic_evaluation is not None
    first.semantic_evaluation.checks.clear()
    second = store.get_result(run.run_id, "INS-002")

    assert second.semantic_evaluation is not None
    assert len(second.semantic_evaluation.checks) == 1


def test_readiness_and_regression_accept_mixed_legacy_and_semantic_results() -> None:
    legacy = ScenarioRunResult.model_validate(LEGACY_RESULT_PAYLOAD)
    modern = semantic_result()
    run_id = uuid4()
    run = RunSummary(
        run_id=run_id,
        pack_id="insurance-v1",
        pack_name="Insurance Reliability Pack v1",
        agent_target=AgentTarget.BUILT_IN_DEMO,
        agent_mode=AgentMode.HEALTHY,
        agent_label="healthy",
        agent_version=None,
        lifecycle_status=LifecycleStatus.COMPLETED,
        aggregate={"total": 2, "passed": 2, "failed": 0, "errors": 0},
        completed_scenarios=2,
        total_scenarios=2,
        is_baseline=False,
        created_at=datetime.now(UTC),
    )

    mixed = [legacy, modern]
    readiness = build_release_readiness(run, mixed, None)
    comparison = build_comparison(
        baseline_run_id=uuid4(),
        current_run_id=run_id,
        pack_id="insurance-v1",
        baseline_results=[legacy, legacy.model_copy(update={"scenario_id": "INS-002"})],
        current_results=mixed,
    )
    trends = build_run_trends(
        "insurance-v1",
        [
            trend_input_from_results(
                run_id=run_id,
                pack_id="insurance-v1",
                agent_label="healthy",
                agent_version=None,
                lifecycle_status=LifecycleStatus.COMPLETED,
                created_at="2026-01-01T00:00:00Z",
                is_baseline=False,
                results=mixed,
            )
        ],
    )

    assert run_score(mixed) == 100
    assert readiness.verdict is not None
    assert comparison.score_delta == 0
    assert trends.points[0].score == 100
