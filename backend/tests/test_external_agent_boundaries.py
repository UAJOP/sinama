"""External HTTP agent execution boundaries, driven entirely by MockTransport.

No test here contacts a real external server, and none relaxes the SSRF policy:
every request still goes through validate_external_agent_endpoint.
"""

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.http_agent import (
    HttpAgentAdapter,
    UnsafeAgentEndpointError,
    validate_external_agent_endpoint,
)
from app.scenario_packs import ScenarioPackRegistry
from app.scenario_runner import ExecutionErrorCategory, RunStatus, ScenarioRunner
from app.scenarios import load_scenario_by_id

PUBLIC_ENDPOINT = "https://agent.example.com/turn"
BEARER = "external-run-only-secret"


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    """Deterministic resolver returning a globally routable address.

    The SSRF policy is deliberately not relaxed for tests: this address must satisfy
    the same `is_global` check production traffic does, and no request leaves the
    process because every adapter is wired to an httpx.MockTransport.
    """

    return ("93.184.216.34",)


def adapter(handler, *, timeout_seconds: float = 2.0) -> HttpAgentAdapter:
    return HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        bearer_token=SecretStr(BEARER),
        timeout_seconds=timeout_seconds,
        max_response_bytes=262_144,
        production=False,
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    )


def insurance_handler(request: httpx.Request) -> httpx.Response:
    message = request.content.decode()
    if "POL-DEMO-1001" in message:
        return httpx.Response(
            200,
            json={
                "message": "Poliçeyi doğruladım. Hasar fotoğrafı gerekiyor.",
                "tool_events": [
                    {
                        "tool": "lookup_policy",
                        "arguments": {"policy_id": "POL-DEMO-1001", "found": True},
                    },
                    {
                        "tool": "request_document",
                        "arguments": {
                            "document_type": "damage_photo",
                            "required_before": "submit_claim",
                        },
                    },
                ],
            },
        )
    return httpx.Response(200, json={"message": "Poliçe numaranızı paylaşır mısınız?"})


def ecommerce_handler(request: httpx.Request) -> httpx.Response:
    message = request.content.decode()
    if "ORD-DEMO-1001" in message:
        return httpx.Response(
            200,
            json={
                "message": "Siparişi doğruladım ve iadenizi oluşturdum.",
                "tool_events": [
                    {
                        "tool": "lookup_order",
                        "arguments": {
                            "order_id": "ORD-DEMO-1001",
                            "found": True,
                            "return_eligible": True,
                        },
                    },
                    {
                        "tool": "refund_order",
                        "arguments": {"order_id": "ORD-DEMO-1001", "resolution": "refund"},
                    },
                ],
            },
        )
    return httpx.Response(200, json={"message": "Sipariş numaranızı paylaşır mısınız?"})


def test_external_agent_executes_a_representative_insurance_scenario() -> None:
    scenario = load_scenario_by_id("INS-001")

    result = asyncio.run(ScenarioRunner().run(scenario, adapter(insurance_handler)))

    assert result.error is None
    assert result.status is RunStatus.PASS
    assert result.agent_label == "external_http"
    assert [event.tool for event in result.tool_trace] == [
        "lookup_policy",
        "request_document",
    ]


def test_external_agent_executes_a_representative_ecommerce_scenario() -> None:
    scenario = load_scenario_by_id("ECOM-001")

    result = asyncio.run(ScenarioRunner().run(scenario, adapter(ecommerce_handler)))

    assert result.error is None
    assert result.status is RunStatus.PASS
    assert {event.tool for event in result.tool_trace} == {"lookup_order", "refund_order"}


def test_external_turn_requests_carry_a_stable_conversation_id_and_user_messages() -> None:
    seen: list[dict[str, str]] = []

    def recording(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.append(_json.loads(request.content.decode()))
        return insurance_handler(request)

    scenario = load_scenario_by_id("INS-001")
    asyncio.run(ScenarioRunner().run(scenario, adapter(recording)))

    assert len(seen) == len(scenario.scripted_user_turns)
    conversation_ids = {payload["conversation_id"] for payload in seen}
    assert len(conversation_ids) == 1, "conversation id must be stable across the run"
    assert [payload["message"] for payload in seen] == list(scenario.scripted_user_turns)


def test_external_agent_custom_tool_events_are_carried_through_generically() -> None:
    def custom_tools(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": "İşlemi tamamladım.",
                "tool_events": [
                    {"tool": "verify_membership_tier", "arguments": {"tier": "gold"}},
                    {"tool": "issue_store_credit", "arguments": {"amount": 250}},
                ],
            },
        )

    scenario = load_scenario_by_id("ECOM-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(custom_tools)))

    assert result.error is None
    assert [event.tool for event in result.tool_trace][:2] == [
        "verify_membership_tier",
        "issue_store_credit",
    ]


def test_malformed_external_response_is_a_typed_scenario_error() -> None:
    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_field": "no message key"})

    scenario = load_scenario_by_id("INS-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(malformed)))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.MALFORMED_AGENT_RESPONSE


def test_invalid_json_from_external_agent_is_contained() -> None:
    def not_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>bad gateway</html>")

    scenario = load_scenario_by_id("INS-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(not_json)))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.MALFORMED_AGENT_RESPONSE


def test_external_agent_timeout_is_a_typed_scenario_error() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timed out", request=request)

    scenario = load_scenario_by_id("INS-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(slow)))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.AGENT_TIMEOUT
    assert "upstream timed out" not in result.error.reason


def test_external_connection_failure_is_contained_without_leaking_details() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused by 10.1.2.3", request=request)

    scenario = load_scenario_by_id("INS-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(refused)))

    assert result.status is RunStatus.ERROR
    assert result.error is not None
    assert "10.1.2.3" not in result.error.reason


def test_external_agent_errors_never_leak_the_bearer_token() -> None:
    def failing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": f"token was {BEARER}"})

    scenario = load_scenario_by_id("INS-001")
    result = asyncio.run(ScenarioRunner().run(scenario, adapter(failing)))

    assert BEARER not in result.model_dump_json()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:8000/turn",
        "https://127.0.0.1/turn",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/turn",
        "https://agent.internal/turn",
        "file:///etc/passwd",
    ],
)
def test_ssrf_protections_remain_in_force(endpoint: str) -> None:
    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(
            validate_external_agent_endpoint(
                endpoint, production=False, resolver=public_resolver
            )
        )


def test_private_dns_resolution_is_still_rejected() -> None:
    async def private_resolver(host: str, port: int) -> tuple[str, ...]:
        return ("10.0.0.5",)

    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(
            validate_external_agent_endpoint(
                PUBLIC_ENDPOINT, production=False, resolver=private_resolver
            )
        )


def test_cross_vertical_suite_keeps_a_stable_fourteen_scenario_order() -> None:
    registry = ScenarioPackRegistry()
    scenarios = registry.load_scenarios("customer-service-core-v1")

    scenario_ids = [scenario.id for scenario in scenarios]

    assert len(scenario_ids) == 14
    assert scenario_ids[:10] == [f"INS-{index:03d}" for index in range(1, 11)]
    assert scenario_ids[10:] == [f"ECOM-{index:03d}" for index in range(1, 5)]
    # Ordering must be reproducible run to run, not incidentally stable.
    assert [scenario.id for scenario in registry.load_scenarios("customer-service-core-v1")] == (
        scenario_ids
    )


def test_semantic_expectations_remain_insurance_only_and_explicitly_opted_in() -> None:
    registry = ScenarioPackRegistry()
    marked: dict[str, list[str]] = {}
    for pack_id in ("insurance-v1", "ecommerce-v1"):
        for scenario in registry.load_scenarios(pack_id):
            if scenario.semantic_expectations:
                marked[scenario.id] = [item.id for item in scenario.semantic_expectations]

    assert set(marked) == {"INS-002", "INS-005", "INS-007"}
    for expectation_ids in marked.values():
        assert len(expectation_ids) == len(set(expectation_ids))


def test_deterministic_evaluator_has_no_domain_specific_branching() -> None:
    from pathlib import Path

    evaluator_source = (
        Path(__file__).resolve().parents[1] / "app" / "evaluator.py"
    ).read_text(encoding="utf-8")

    for domain_token in (
        "lookup_policy",
        "damage_photo",
        "lookup_order",
        "refund_order",
        "insurance",
        "ecommerce",
    ):
        assert domain_token not in evaluator_source, (
            f"deterministic evaluator must stay generic, found {domain_token!r}"
        )
