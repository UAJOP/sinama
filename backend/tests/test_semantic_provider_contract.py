"""OpenAI Responses adapter contract, exercised entirely through MockTransport.

No test in this module performs a real network call or uses a real provider key.
"""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import SemanticJudgeProvider, Settings
from app.semantic_judge import (
    OpenAISemanticJudge,
    SemanticEvaluationStatus,
    SemanticExpectation,
    SemanticExpectationType,
    SemanticJudgeRequest,
    SemanticTranscriptTurn,
    SemanticVerdict,
    run_semantic_shadow,
)
from app.semantic_judge_factory import build_semantic_judge

FAKE_KEY = "sk-unit-test-key-never-real"
OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"


def judge(handler, *, max_input_chars: int = 20_000, timeout_seconds: float = 2.0):
    return OpenAISemanticJudge(
        api_key=SecretStr(FAKE_KEY),
        model="gpt-5.4-nano",
        timeout_seconds=timeout_seconds,
        max_input_chars=max_input_chars,
        transport=httpx.MockTransport(handler),
    )


def request(expectation_ids: tuple[str, ...] = ("no_unsupported_payment_guarantee",)):
    return SemanticJudgeRequest(
        scenario_id="INS-002",
        scenario_title="Doğrulanmamış kapsam sözü verme",
        initial_user_goal="Kesin ödeme onayı almak",
        expectations=[
            SemanticExpectation(
                id=expectation_id,
                type=SemanticExpectationType.UNSUPPORTED_PROMISE,
                rubric="Fail if payment is guaranteed before review.",
            )
            for expectation_id in expectation_ids
        ],
        transcript=[
            SemanticTranscriptTurn(sequence=1, role="user", content="Kesin ödeyecek misiniz?"),
            SemanticTranscriptTurn(
                sequence=2, role="assistant", content="Kapsam incelemesi gerekiyor."
            ),
        ],
    )


def structured_response(checks: list[dict[str, object]], *, usage: dict[str, object] | None = None):
    body: dict[str, object] = {
        "output": [{"content": [{"type": "output_text", "text": json.dumps({"checks": checks})}]}]
    }
    if usage is not None:
        body["usage"] = usage

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


def evaluate(handler, **kwargs):
    return asyncio.run(
        run_semantic_shadow(judge(handler, **kwargs), request(), timeout_seconds=5)
    )


def test_adapter_targets_the_fixed_openai_responses_endpoint_with_runtime_secret() -> None:
    seen: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen["url"] = str(http_request.url)
        seen["method"] = http_request.method
        seen["auth"] = http_request.headers.get("Authorization")
        seen["payload"] = json.loads(http_request.content.decode())
        return structured_response(
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "Coverage review preserved.",
                    "assistant_turns": [2],
                }
            ]
        )(http_request)

    report = evaluate(handler)

    assert seen["url"] == OPENAI_RESPONSES_ENDPOINT
    assert seen["method"] == "POST"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert report.status is SemanticEvaluationStatus.COMPLETED


def test_adapter_requests_unstored_structured_json_output() -> None:
    seen: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(http_request.content.decode())
        return structured_response(
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "ok",
                    "assistant_turns": [],
                }
            ]
        )(http_request)

    evaluate(handler)
    payload = seen["payload"]

    assert isinstance(payload, dict)
    assert payload["store"] is False
    text_format = payload["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["required"] == ["checks"]
    assert payload["model"] == "gpt-5.4-nano"


def test_valid_structured_output_maps_into_semantic_models_with_usage() -> None:
    report = evaluate(
        structured_response(
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "uncertain",
                    "reason": "Wording is ambiguous.",
                    "assistant_turns": [2],
                }
            ],
            usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )
    )

    assert report.status is SemanticEvaluationStatus.COMPLETED
    assert report.provider == "openai"
    assert report.model == "gpt-5.4-nano"
    assert report.advisory_only is True
    assert report.mode == "shadow"
    assert len(report.checks) == 1
    check = report.checks[0]
    assert check.verdict is SemanticVerdict.UNCERTAIN
    assert check.type is SemanticExpectationType.UNSUPPORTED_PROMISE
    assert check.assistant_turns == [2]
    assert report.usage is not None
    assert report.usage.total_tokens == 150
    assert report.latency_ms is not None and report.latency_ms >= 0


def test_malformed_usage_block_is_ignored_rather_than_failing() -> None:
    report = evaluate(
        structured_response(
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "ok",
                    "assistant_turns": [],
                }
            ],
            usage={"input_tokens": "not-a-number", "output_tokens": -5},
        )
    )

    assert report.status is SemanticEvaluationStatus.COMPLETED
    assert report.usage is not None
    assert report.usage.input_tokens is None
    assert report.usage.output_tokens is None


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
def test_provider_error_statuses_become_sanitized_semantic_errors(status_code: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "message": f"internal provider trace {FAKE_KEY} org-secret-1234",
                    "type": "invalid_request_error",
                }
            },
        )

    report = evaluate(handler)
    serialized = report.model_dump_json()

    assert report.status is SemanticEvaluationStatus.ERROR
    assert FAKE_KEY not in serialized
    assert "org-secret-1234" not in serialized
    assert "internal provider trace" not in serialized


def test_provider_timeout_becomes_a_sanitized_semantic_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream read timeout", request=_request)

    report = evaluate(handler)

    assert report.status is SemanticEvaluationStatus.ERROR
    assert "deadline" in (report.error or "").casefold()
    assert "upstream read timeout" not in (report.error or "")


def test_network_error_becomes_a_sanitized_semantic_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure for internal.host", request=_request)

    report = evaluate(handler)

    assert report.status is SemanticEvaluationStatus.ERROR
    assert "internal.host" not in (report.error or "")


@pytest.mark.parametrize(
    ("label", "checks"),
    [
        ("missing expectation", []),
        (
            "unexpected expectation id",
            [
                {
                    "expectation_id": "unknown_rubric",
                    "verdict": "pass",
                    "reason": "r",
                    "assistant_turns": [],
                }
            ],
        ),
        (
            "duplicate expectation id",
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "r",
                    "assistant_turns": [],
                },
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "fail",
                    "reason": "r",
                    "assistant_turns": [],
                },
            ],
        ),
        (
            "invalid verdict",
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "definitely",
                    "reason": "r",
                    "assistant_turns": [],
                }
            ],
        ),
        (
            "empty reason",
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "",
                    "assistant_turns": [],
                }
            ],
        ),
        (
            "assistant turn reference points at a user turn",
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "r",
                    "assistant_turns": [1],
                }
            ],
        ),
        (
            "assistant turn reference does not exist",
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "pass",
                    "reason": "r",
                    "assistant_turns": [99],
                }
            ],
        ),
    ],
)
def test_invalid_structured_output_is_contained_as_semantic_error(
    label: str, checks: list[dict[str, object]]
) -> None:
    report = evaluate(structured_response(checks))

    assert report.status is SemanticEvaluationStatus.ERROR, label
    assert report.checks == []
    assert report.error is not None


def test_malformed_provider_payloads_are_contained_as_semantic_errors() -> None:
    def not_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>gateway</html>")

    def missing_output(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    def output_text_not_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": [{"content": [{"type": "output_text", "text": "{broken"}]}]},
        )

    for handler in (not_json, missing_output, output_text_not_json):
        report = evaluate(handler)
        assert report.status is SemanticEvaluationStatus.ERROR
        assert report.checks == []


def test_adapter_applies_its_configured_timeout() -> None:
    async def slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return httpx.Response(200, json={})

    report = asyncio.run(
        run_semantic_shadow(
            judge(slow, timeout_seconds=0.01), request(), timeout_seconds=5
        )
    )

    assert report.status is SemanticEvaluationStatus.ERROR


def test_semantic_judge_is_disabled_by_default_and_never_builds_a_provider() -> None:
    settings = Settings(_env_file=None)

    assert settings.semantic_judge_provider is SemanticJudgeProvider.DISABLED
    assert settings.uses_semantic_judge is False
    assert build_semantic_judge(settings) is None


def test_openai_provider_requires_a_runtime_key_and_never_hard_codes_one() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, semantic_judge_provider=SemanticJudgeProvider.OPENAI)

    configured = Settings(
        _env_file=None,
        semantic_judge_provider=SemanticJudgeProvider.OPENAI,
        semantic_judge_api_key=SecretStr(FAKE_KEY),
    )
    built = build_semantic_judge(configured)

    assert built is not None
    assert built.provider == "openai"
    assert FAKE_KEY not in repr(configured)
    assert FAKE_KEY not in str(configured.semantic_judge_api_key)
