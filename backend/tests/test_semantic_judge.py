import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.agent_adapters import AgentSession, AgentTurnResult, DemoAgentAdapter
from app.config import SemanticJudgeProvider, Settings
from app.models import AgentMode
from app.scenario_runner import RunStatus, ScenarioRunner
from app.scenarios import load_scenario_by_id
from app.semantic_judge import (
    OpenAISemanticJudge,
    SemanticEvaluationReport,
    SemanticEvaluationStatus,
    SemanticJudgeCheck,
    SemanticJudgeError,
    SemanticJudgeRequest,
    SemanticTranscriptTurn,
    SemanticVerdict,
)


class CapturingFailJudge:
    provider = "fake"
    model = "fake-shadow-v1"

    def __init__(self) -> None:
        self.requests: list[SemanticJudgeRequest] = []

    async def evaluate(self, request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        self.requests.append(request)
        expectation = request.expectations[0]
        assistant_turns = [
            turn.sequence for turn in request.transcript if turn.role == "assistant"
        ]
        return SemanticEvaluationReport(
            status=SemanticEvaluationStatus.COMPLETED,
            provider=self.provider,
            model=self.model,
            checks=[
                SemanticJudgeCheck(
                    expectation_id=expectation.id,
                    type=expectation.type,
                    verdict=SemanticVerdict.FAIL,
                    reason="Advisory semantic violation detected.",
                    assistant_turns=assistant_turns[:1],
                )
            ],
            latency_ms=1,
        )


class SlowJudge:
    provider = "fake"
    model = "slow"

    async def evaluate(self, _request: SemanticJudgeRequest) -> SemanticEvaluationReport:
        await asyncio.sleep(0.05)
        return SemanticEvaluationReport(status=SemanticEvaluationStatus.COMPLETED)


class MaskingAdapter:
    @property
    def label(self) -> str:
        return "masking-test"

    async def start_session(self) -> AgentSession:
        return AgentSession(session_id="masking-session")

    async def send_message(self, _session: AgentSession, message: str) -> AgentTurnResult:
        if "Hasar kaydı" in message:
            return AgentTurnResult(
                assistant_message="Hasar talebinizi anladım; poliçe numaranızı paylaşır mısınız?"
            )
        return AgentTurnResult(
            assistant_message="Hangi işlemi yapmak istediğinizi netleştirir misiniz?"
        )


def test_fixture_semantic_expectations_are_explicit_and_narrow() -> None:
    expectations = {
        "INS-002": "unsupported_promise",
        "INS-005": "internal_instruction_disclosure",
        "INS-007": "intent_satisfaction",
    }

    for scenario_id, expectation_type in expectations.items():
        scenario = load_scenario_by_id(scenario_id)
        assert len(scenario.semantic_expectations) == 1
        assert scenario.semantic_expectations[0].type.value == expectation_type

    assert load_scenario_by_id("INS-001").semantic_expectations == []


def test_missing_judge_marks_semantic_as_disabled_without_changing_pass() -> None:
    scenario = load_scenario_by_id("INS-002")
    result = asyncio.run(
        ScenarioRunner().run(scenario, DemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert result.status is RunStatus.PASS
    assert result.failures == []
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.DISABLED
    assert result.semantic_evaluation.advisory_only is True


def test_semantic_fail_is_advisory_and_does_not_change_deterministic_result() -> None:
    judge = CapturingFailJudge()
    scenario = load_scenario_by_id("INS-002")

    result = asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(
            scenario,
            DemoAgentAdapter(AgentMode.HEALTHY),
        )
    )

    assert result.status is RunStatus.PASS
    assert result.severity is None
    assert result.failures == []
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.COMPLETED
    assert result.semantic_evaluation.checks[0].verdict is SemanticVerdict.FAIL


def test_semantic_timeout_is_reported_as_semantic_error_not_agent_error() -> None:
    scenario = load_scenario_by_id("INS-002")

    result = asyncio.run(
        ScenarioRunner(
            semantic_judge=SlowJudge(),
            semantic_timeout_seconds=0.001,
        ).run(scenario, DemoAgentAdapter(AgentMode.HEALTHY))
    )

    assert result.status is RunStatus.PASS
    assert result.error is None
    assert result.semantic_evaluation is not None
    assert result.semantic_evaluation.status is SemanticEvaluationStatus.ERROR
    assert "deadline" in (result.semantic_evaluation.error or "").casefold()


def test_semantic_judge_receives_masked_transcript_only() -> None:
    judge = CapturingFailJudge()
    scenario = load_scenario_by_id("INS-007").model_copy(
        update={
            "scripted_user_turns": [
                "TC kimlik numaram 12345678901, aracımla ilgili bir işlem yapmak istiyorum.",
                "Hasar kaydı açtırmak istiyorum, aracım kaza yaptı.",
            ]
        }
    )

    result = asyncio.run(
        ScenarioRunner(semantic_judge=judge).run(scenario, MaskingAdapter())
    )

    assert result.status is RunStatus.PASS
    assert len(judge.requests) == 1
    serialized = judge.requests[0].model_dump_json()
    assert "12345678901" not in serialized
    assert "123******01" in serialized


def test_openai_adapter_uses_structured_output_and_captures_usage() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "checks": [
                                            {
                                                "expectation_id": (
                                                    "no_unsupported_payment_guarantee"
                                                ),
                                                "verdict": "pass",
                                                "reason": (
                                                    "Coverage remains explicitly subject to "
                                                    "review."
                                                ),
                                                "assistant_turns": [2],
                                            }
                                        ]
                                    }
                                ),
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                },
            },
        )

    scenario = load_scenario_by_id("INS-002")
    request = SemanticJudgeRequest(
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        initial_user_goal=scenario.initial_user_goal,
        expectations=scenario.semantic_expectations,
        transcript=[
            SemanticTranscriptTurn(sequence=1, role="user", content="Kesin ödenecek mi?"),
            SemanticTranscriptTurn(
                sequence=2,
                role="assistant",
                content="Kapsam incelemesi tamamlanmadan ödeme garantisi veremem.",
            ),
        ],
    )
    judge = OpenAISemanticJudge(
        api_key=SecretStr("provider-test-secret"),
        model="gpt-5.4-nano",
        timeout_seconds=2,
        max_input_chars=16_000,
        transport=httpx.MockTransport(handler),
    )

    report = asyncio.run(judge.evaluate(request))

    assert captured["authorization"] == "Bearer provider-test-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert report.status is SemanticEvaluationStatus.COMPLETED
    assert report.checks[0].verdict is SemanticVerdict.PASS
    assert report.usage is not None
    assert report.usage.total_tokens == 150
    assert report.latency_ms is not None


def test_openai_adapter_rejects_invalid_or_incomplete_provider_output() -> None:
    judge = OpenAISemanticJudge(
        api_key=SecretStr("provider-test-secret"),
        model="gpt-5.4-nano",
        timeout_seconds=2,
        max_input_chars=16_000,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"checks": []}',
                                }
                            ],
                        }
                    ]
                },
            )
        ),
    )
    scenario = load_scenario_by_id("INS-002")
    request = SemanticJudgeRequest(
        scenario_id=scenario.id,
        scenario_title=scenario.title,
        initial_user_goal=scenario.initial_user_goal,
        expectations=scenario.semantic_expectations,
        transcript=[
            SemanticTranscriptTurn(sequence=1, role="assistant", content="Review required.")
        ],
    )

    with pytest.raises(SemanticJudgeError, match="rubric set"):
        asyncio.run(judge.evaluate(request))


def test_semantic_provider_is_disabled_by_default_and_openai_requires_key() -> None:
    settings = Settings()
    assert settings.semantic_judge_provider is SemanticJudgeProvider.DISABLED
    assert settings.uses_semantic_judge is False

    with pytest.raises(ValidationError):
        Settings(semantic_judge_provider="openai")

    enabled = Settings(
        semantic_judge_provider="openai",
        semantic_judge_api_key=SecretStr("test-key"),
    )
    assert enabled.uses_semantic_judge is True
