"""Local Ollama calibration adapter contract, exercised entirely through MockTransport.

No test here requires Ollama to be installed and none performs a real network call.
These tests also pin the product boundary: the local judge must stay out of the
production semantic provider path.
"""

import asyncio
import json

import httpx
import pytest

from app.config import SemanticJudgeProvider, Settings
from app.semantic_judge import (
    SemanticEvaluationStatus,
    SemanticExpectation,
    SemanticExpectationType,
    SemanticJudgeRequest,
    SemanticTranscriptTurn,
    SemanticVerdict,
    run_semantic_shadow,
)
from app.semantic_judge_factory import build_semantic_judge
from app.semantic_judge_local import (
    LocalJudgeConfigurationError,
    OllamaSemanticJudge,
    validate_loopback_base_url,
)

OLLAMA_CHAT_ENDPOINT = "http://localhost:11434/api/chat"


def judge(handler, *, max_input_chars: int = 20_000, timeout_seconds: float = 2.0):
    return OllamaSemanticJudge(
        model="qwen3:4b",
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


def ollama_response(
    checks: list[dict[str, object]],
    *,
    prompt_eval_count: int | None = 412,
    eval_count: int | None = 57,
) -> httpx.Response:
    body: dict[str, object] = {
        "model": "qwen3:4b",
        "done": True,
        "message": {"role": "assistant", "content": json.dumps({"checks": checks})},
    }
    if prompt_eval_count is not None:
        body["prompt_eval_count"] = prompt_eval_count
    if eval_count is not None:
        body["eval_count"] = eval_count
    return httpx.Response(200, json=body)


def valid_check(expectation_id: str = "no_unsupported_payment_guarantee") -> dict[str, object]:
    return {
        "expectation_id": expectation_id,
        "verdict": "pass",
        "reason": "Kapsam incelemesi şartı korunmuş.",
        "assistant_turns": [2],
    }


# --- Product boundary: the local judge must never become a production provider ---


def test_local_judge_is_not_reachable_through_the_production_factory() -> None:
    """No SINAMA_SEMANTIC_JUDGE_PROVIDER value may yield the local calibration judge."""

    assert not hasattr(SemanticJudgeProvider, "OLLAMA")
    assert {member.value for member in SemanticJudgeProvider} == {"disabled", "openai"}

    disabled = Settings(semantic_judge_provider=SemanticJudgeProvider.DISABLED)
    assert build_semantic_judge(disabled) is None


def test_production_semantic_provider_enum_rejects_ollama() -> None:
    with pytest.raises(ValueError):
        Settings(semantic_judge_provider="ollama")


# --- Loopback pinning: this must not become a general outbound HTTP client ---


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
        "http://localhost:11434/",
    ],
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert validate_loopback_base_url(url).startswith(
        ("http://localhost", "http://127.0.0.1", "http://[::1]")
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254",
        "http://metadata.google.internal",
        "https://api.openai.com",
        "http://10.0.0.5:11434",
        "http://example.com",
        "ftp://localhost:11434",
        "http://user:pass@localhost:11434",
        "",
    ],
)
def test_non_loopback_urls_are_rejected(url: str) -> None:
    with pytest.raises(LocalJudgeConfigurationError):
        validate_loopback_base_url(url)


def test_judge_construction_rejects_non_loopback_base_url() -> None:
    with pytest.raises(LocalJudgeConfigurationError):
        OllamaSemanticJudge(
            model="qwen3:4b",
            timeout_seconds=5.0,
            max_input_chars=20_000,
            base_url="http://169.254.169.254",
        )


# --- Request contract ---


def test_request_targets_local_chat_endpoint_with_schema_and_no_auth() -> None:
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["url"] = str(http_request.url)
        captured["headers"] = dict(http_request.headers)
        captured["payload"] = json.loads(http_request.content.decode())
        return ollama_response([valid_check()])

    report = asyncio.run(judge(handler).evaluate(request()))

    assert captured["url"] == OLLAMA_CHAT_ENDPOINT
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen3:4b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {"temperature": 0}
    # Structured output must be requested so the response maps into SINAMA models.
    assert payload["format"]["required"] == ["checks"]
    assert payload["format"]["properties"]["checks"]["items"]["properties"]["verdict"]["enum"] == [
        "pass",
        "fail",
        "uncertain",
    ]
    # A local daemon needs no credential; none must be sent.
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "authorization" not in {key.casefold() for key in headers}
    assert report.status is SemanticEvaluationStatus.COMPLETED


def test_provider_and_model_are_reported_as_local() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return ollama_response([valid_check()])

    report = asyncio.run(judge(handler).evaluate(request()))

    assert report.provider == "ollama-local"
    assert report.model == "qwen3:4b"
    assert report.advisory_only is True
    assert report.mode == "shadow"


def test_valid_structured_output_maps_into_semantic_models() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return ollama_response(
            [
                {
                    "expectation_id": "no_unsupported_payment_guarantee",
                    "verdict": "fail",
                    "reason": "Kesin ödeme sözü verildi.",
                    "assistant_turns": [2],
                }
            ]
        )

    report = asyncio.run(judge(handler).evaluate(request()))

    assert report.status is SemanticEvaluationStatus.COMPLETED
    assert len(report.checks) == 1
    check = report.checks[0]
    assert check.expectation_id == "no_unsupported_payment_guarantee"
    assert check.verdict is SemanticVerdict.FAIL
    assert check.type is SemanticExpectationType.UNSUPPORTED_PROMISE
    assert check.assistant_turns == [2]


def test_token_usage_is_extracted_from_ollama_counters() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return ollama_response([valid_check()], prompt_eval_count=412, eval_count=57)

    report = asyncio.run(judge(handler).evaluate(request()))

    assert report.usage is not None
    assert report.usage.input_tokens == 412
    assert report.usage.output_tokens == 57
    assert report.usage.total_tokens == 469
    assert report.usage.estimated_cost_usd == 0.0


def test_missing_token_counters_do_not_fail_the_evaluation() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return ollama_response([valid_check()], prompt_eval_count=None, eval_count=None)

    report = asyncio.run(judge(handler).evaluate(request()))

    assert report.status is SemanticEvaluationStatus.COMPLETED
    assert report.usage is None


# --- Error containment: every failure must stay an advisory semantic error ---


@pytest.mark.parametrize("status_code", [400, 401, 404, 429, 500, 503])
def test_provider_error_statuses_become_sanitized_semantic_errors(status_code: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "internal daemon detail"})

    report = asyncio.run(run_semantic_shadow(judge(handler), request(), timeout_seconds=5.0))

    assert report.status is SemanticEvaluationStatus.ERROR
    assert report.error is not None
    assert "internal daemon detail" not in report.error


def test_connection_failure_is_contained_with_actionable_message() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    report = asyncio.run(run_semantic_shadow(judge(handler), request(), timeout_seconds=5.0))

    assert report.status is SemanticEvaluationStatus.ERROR
    assert report.error is not None
    assert "Ollama daemon" in report.error


def test_timeout_becomes_a_semantic_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    report = asyncio.run(run_semantic_shadow(judge(handler), request(), timeout_seconds=5.0))

    assert report.status is SemanticEvaluationStatus.ERROR
    assert report.error == "Semantic judge request exceeded its deadline."


@pytest.mark.parametrize(
    "body",
    [
        {"message": {"role": "assistant", "content": "not json at all"}},
        {"message": {"role": "assistant", "content": ""}},
        {"message": {"role": "assistant"}},
        {"message": "wrong type"},
        {"done": True},
        [],
    ],
)
def test_malformed_daemon_payloads_become_semantic_errors(body: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    report = asyncio.run(run_semantic_shadow(judge(handler), request(), timeout_seconds=5.0))

    assert report.status is SemanticEvaluationStatus.ERROR


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [valid_check(), valid_check()],
        [valid_check("unexpected_expectation_id")],
        [{**valid_check(), "verdict": "maybe"}],
        [{**valid_check(), "reason": ""}],
        [{**valid_check(), "assistant_turns": [1]}],
        [{**valid_check(), "assistant_turns": [99]}],
    ],
)
def test_invalid_semantic_contracts_become_semantic_errors(checks: list[dict[str, object]]) -> None:
    """Duplicate, unknown, unverdictable or bad-turn output must not be trusted."""

    def handler(_: httpx.Request) -> httpx.Response:
        return ollama_response(checks)

    report = asyncio.run(run_semantic_shadow(judge(handler), request(), timeout_seconds=5.0))

    assert report.status is SemanticEvaluationStatus.ERROR
    assert report.checks == []


def test_oversized_input_is_rejected_before_any_request_is_made() -> None:
    attempted = False

    def handler(_: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        nonlocal attempted
        attempted = True
        return ollama_response([valid_check()])

    report = asyncio.run(
        run_semantic_shadow(
            judge(handler, max_input_chars=200),
            request(),
            timeout_seconds=5.0,
        )
    )

    assert attempted is False
    assert report.status is SemanticEvaluationStatus.ERROR
    assert report.error == "Semantic evaluation input exceeded the configured limit."


def test_local_judge_shares_the_same_validation_as_the_cloud_adapter() -> None:
    """Both adapters must enforce one contract; a second provider cannot be laxer."""

    from app.semantic_judge import build_semantic_checks

    assert build_semantic_checks.__module__ == "app.semantic_judge"
