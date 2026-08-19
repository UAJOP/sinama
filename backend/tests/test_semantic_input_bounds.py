import asyncio

import httpx
from pydantic import SecretStr

from app.agent_adapters import DemoAgentAdapter
from app.models import AgentMode
from app.scenario_runner import RunStatus, ScenarioRunner
from app.scenarios import load_scenario_by_id
from app.semantic_judge import OpenAISemanticJudge, SemanticEvaluationStatus


def test_oversized_semantic_input_cannot_fail_the_agent_run() -> None:
    def should_not_call_provider(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Provider must not be called when semantic input exceeds the limit")

    scenario = load_scenario_by_id("INS-002").model_copy(
        update={"initial_user_goal": "çok uzun semantik hedef " * 200}
    )
    judge = OpenAISemanticJudge(
        api_key=SecretStr("provider-test-secret"),
        model="gpt-5.4-nano",
        timeout_seconds=2,
        max_input_chars=500,
        transport=httpx.MockTransport(should_not_call_provider),
    )

    result = asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(
            scenario,
            DemoAgentAdapter(AgentMode.HEALTHY),
        )
    )

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert "input exceeded" in (result.semantic_evaluation.error or "").casefold()
