"""Semantic input bounds and PII masking must hold before any provider call.

Bounds regressions here previously escaped as a pydantic ValidationError and failed
the whole deterministic run, so each bound is asserted end-to-end through
ScenarioRunner rather than against the request model alone.
"""

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.agent_adapters import AgentSession, AgentTurnResult, DemoAgentAdapter
from app.models import AgentMode
from app.scenario_runner import RunStatus, ScenarioRunner
from app.scenarios import load_scenario_by_id
from app.semantic_judge import (
    SEMANTIC_JUDGE_MAX_EXPECTATIONS,
    OpenAISemanticJudge,
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticExpectation,
    SemanticExpectationType,
    SemanticJudgeRequest,
)

TC_KIMLIK = "12345678901"
TURKISH_MOBILE = "5321234567"
CARD_NUMBER = "4111 1111 1111 1111"
CARD_DIGITS = "4111111111111111"


class CapturingJudge:
    """Records the exact request a provider would have received."""

    provider = "fake"
    model = "fake-judge-1"

    def __init__(self) -> None:
        self.request: SemanticJudgeRequest | None = None

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        self.request = request
        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
        )


class ScriptedAdapter:
    """Agent adapter returning a fixed assistant message for every turn."""

    def __init__(self, message: str) -> None:
        self.label = "scripted"
        self._message = message

    async def start_session(self) -> AgentSession:
        return AgentSession(session_id="scripted-session")

    async def send_message(self, session: AgentSession, message: str) -> AgentTurnResult:
        return AgentTurnResult(assistant_message=self._message, tool_events=[])


def run_with(
    judge: object,
    scenario_update: dict[str, object] | None = None,
    adapter: object = None,
):
    scenario = load_scenario_by_id("INS-002")
    if scenario_update:
        scenario = scenario.model_copy(update=scenario_update)
    return asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(  # type: ignore[arg-type]
            scenario,
            adapter or DemoAgentAdapter(AgentMode.HEALTHY),  # type: ignore[arg-type]
        )
    )


def test_assistant_responses_are_bounded_by_the_agent_turn_contract() -> None:
    """Oversized assistant content cannot reach semantic input in the first place."""

    with pytest.raises(ValueError):
        AgentTurnResult(assistant_message="çok uzun yanıt " * 2_000, tool_events=[])


def test_extremely_long_conversation_turn_does_not_fail_the_run() -> None:
    judge = CapturingJudge()
    scenario = load_scenario_by_id("INS-002")
    turns = list(scenario.scripted_user_turns)
    turns[0] = "çok uzun müşteri mesajı " * 400

    result = run_with(judge, {"scripted_user_turns": turns})

    assert result.error is None
    assert result.status in {RunStatus.PASS, RunStatus.FAIL}
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert judge.request is None


def test_oversized_initial_user_goal_does_not_fail_the_run() -> None:
    judge = CapturingJudge()

    result = run_with(judge, {"initial_user_goal": "çok uzun hedef " * 400})

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert judge.request is None


def test_transcript_turn_count_beyond_the_semantic_cap_does_not_fail_the_run() -> None:
    judge = CapturingJudge()
    scenario = load_scenario_by_id("INS-002")
    many_turns = ["Kapsam durumu nedir?"] * 30

    result = run_with(
        judge,
        {"scripted_user_turns": many_turns, "max_turns": len(many_turns)},
        adapter=ScriptedAdapter("Kapsam incelemesi sürüyor."),
    )

    # Deterministic status may legitimately differ for this synthetic conversation;
    # what must hold is that the run completed and semantic input was contained.
    assert result.error is None
    assert result.status in {RunStatus.PASS, RunStatus.FAIL}
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert judge.request is None
    assert scenario.max_turns < len(many_turns)


def test_semantic_expectation_cap_is_enforced_at_fixture_validation() -> None:
    scenario = load_scenario_by_id("INS-002")
    payload = scenario.model_dump(mode="json")
    payload["semantic_expectations"] = [
        {"id": f"e{index}", "type": "unsupported_promise", "rubric": "r"}
        for index in range(SEMANTIC_JUDGE_MAX_EXPECTATIONS + 1)
    ]

    with pytest.raises(ValueError):
        type(scenario).model_validate(payload)


def test_oversized_serialized_request_is_rejected_before_the_provider_is_called() -> None:
    def should_not_call(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Provider must not be called for oversized semantic input")

    judge = OpenAISemanticJudge(
        api_key=SecretStr("sk-test-not-real"),
        model="gpt-5.4-nano",
        timeout_seconds=2,
        max_input_chars=400,
        transport=httpx.MockTransport(should_not_call),
    )

    result = run_with(judge)

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert "exceeded" in (result.semantic_evaluation.error or "").casefold()


def test_semantic_request_never_carries_raw_sensitive_values() -> None:
    judge = CapturingJudge()
    scenario = load_scenario_by_id("INS-002")
    turns = list(scenario.scripted_user_turns)
    turns[0] = (
        f"{turns[0]} TC kimlik {TC_KIMLIK}, telefon {TURKISH_MOBILE}, kart {CARD_NUMBER}"
    )

    result = run_with(
        judge,
        {
            "scripted_user_turns": turns,
            "initial_user_goal": f"Hedef TC {TC_KIMLIK} telefon {TURKISH_MOBILE}",
            "title": f"Başlık TC {TC_KIMLIK}",
        },
    )

    assert judge.request is not None
    serialized = judge.request.model_dump_json()
    for raw in (TC_KIMLIK, TURKISH_MOBILE, CARD_NUMBER, CARD_DIGITS):
        assert raw not in serialized, f"{raw} leaked into the semantic request"

    # The masked forms must still be present, proving content was carried, not dropped.
    assert "123******01" in serialized
    assert result.status is RunStatus.PASS


def test_masking_covers_every_semantic_serialization_field() -> None:
    judge = CapturingJudge()

    run_with(
        judge,
        {
            "initial_user_goal": f"Hedef {TC_KIMLIK}",
            "title": f"Başlık {TC_KIMLIK}",
        },
    )

    assert judge.request is not None
    assert TC_KIMLIK not in judge.request.initial_user_goal
    assert TC_KIMLIK not in judge.request.scenario_title
    for turn in judge.request.transcript:
        assert TC_KIMLIK not in turn.content


def test_semantic_expectations_reject_duplicate_ids_at_load_time() -> None:
    scenario = load_scenario_by_id("INS-002")
    payload = scenario.model_dump(mode="json")
    payload["semantic_expectations"] = [
        {"id": "shared_id", "type": "unsupported_promise", "rubric": "first"},
        {"id": "shared_id", "type": "intent_satisfaction", "rubric": "second"},
    ]

    with pytest.raises(ValueError, match="unique expectation ids"):
        type(scenario).model_validate(payload)


def test_unique_semantic_expectation_ids_remain_valid() -> None:
    scenario = load_scenario_by_id("INS-002")
    payload = scenario.model_dump(mode="json")
    payload["semantic_expectations"] = [
        {"id": "first_rubric", "type": "unsupported_promise", "rubric": "first"},
        {"id": "second_rubric", "type": "intent_satisfaction", "rubric": "second"},
    ]

    revalidated = type(scenario).model_validate(payload)

    assert [item.id for item in revalidated.semantic_expectations] == [
        "first_rubric",
        "second_rubric",
    ]


def test_expectation_ids_are_constrained_to_a_stable_slug_format() -> None:
    with pytest.raises(ValueError):
        SemanticExpectation(
            id="Not A Slug",
            type=SemanticExpectationType.UNSUPPORTED_PROMISE,
            rubric="r",
        )
