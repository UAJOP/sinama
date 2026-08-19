import asyncio

from app.agent_adapters import DemoAgentAdapter
from app.models import AgentMode
from app.readiness import ReleaseReadinessVerdict, build_release_readiness
from app.regression import ComparisonAvailability
from app.scenario_packs import scenario_pack_registry
from app.scenario_runner import RunStatus, ScenarioRunner
from app.scenarios import load_scenario_by_id
from app.semantic_judge import (
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticJudgeCheck,
    SemanticJudgeRequest,
    SemanticVerdict,
)
from app.test_runs import InMemoryRunStore


class AdvisoryFailJudge:
    provider = "fake"
    model = "fake-shadow"

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        expectation = request.expectations[0]
        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
            checks=[
                SemanticJudgeCheck(
                    expectation_id=expectation.id,
                    type=expectation.type,
                    verdict=SemanticVerdict.FAIL,
                    reason="Advisory semantic failure for readiness isolation test.",
                )
            ],
        )


def test_semantic_fail_cannot_change_ready_baseline_verdict() -> None:
    scenario = load_scenario_by_id("INS-002")
    result = asyncio.run(
        ScenarioRunner(semantic_judge=AdvisoryFailJudge()).run(
            scenario,
            DemoAgentAdapter(AgentMode.HEALTHY),
        )
    )
    assert result.status is RunStatus.PASS
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.checks[0].verdict is SemanticVerdict.FAIL

    store = InMemoryRunStore()
    pack = scenario_pack_registry.get_pack("insurance-v1")
    created = store.create_run(pack, AgentMode.HEALTHY)
    store.mark_running(created.run_id)
    store.add_result(created.run_id, result)
    store.mark_completed(created.run_id)
    run = store.set_baseline(created.run_id)

    readiness = build_release_readiness(
        run,
        [store.get_result(created.run_id, "INS-002")],
        store.get_comparison(created.run_id),
    )

    assert readiness.comparison_status is ComparisonAvailability.IS_BASELINE
    assert readiness.verdict is ReleaseReadinessVerdict.READY
    assert readiness.reasons == []
