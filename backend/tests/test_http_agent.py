import asyncio
import importlib
import json
import logging
from collections.abc import Sequence

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.http_agent import (
    ConnectionTestStatus,
    ExternalAgentHttpStatusError,
    ExternalAgentResponseTooLargeError,
    HttpAgentAdapter,
    InvalidAgentJsonError,
    InvalidAgentSchemaError,
    UnsafeAgentEndpointError,
    validate_external_agent_endpoint,
)
from app.http_agent import (
    test_http_agent_connection as probe_http_agent_connection,
)
from app.main import app
from app.scenario_runner import ExecutionErrorCategory, ScenarioRunner
from app.scenarios import load_scenario_by_id

PUBLIC_ENDPOINT = "https://93.184.216.34/agent"


async def send_one_turn(adapter: HttpAgentAdapter, message: str = "Merhaba"):
    session = await adapter.start_session()
    return session, await adapter.send_message(session, message)


def test_http_adapter_sends_contract_and_normalizes_tool_events() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": "Poliçeyi buldum.",
                "tool_events": [
                    {
                        "tool": "lookup_policy",
                        "arguments": {"policy_id": "POL-DEMO-1001"},
                    }
                ],
            },
        )

    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        bearer_token=SecretStr("adapter-secret"),
        transport=httpx.MockTransport(handler),
    )

    session, turn = asyncio.run(send_one_turn(adapter, "POL-DEMO-1001"))

    assert captured["authorization"] == "Bearer adapter-secret"
    assert captured["payload"] == {
        "conversation_id": session.session_id,
        "message": "POL-DEMO-1001",
    }
    assert turn.assistant_message == "Poliçeyi buldum."
    assert len(turn.tool_events) == 1
    assert turn.tool_events[0].tool.value == "lookup_policy"
    assert turn.tool_events[0].arguments == {"policy_id": "POL-DEMO-1001"}


def test_http_adapter_timeout_is_reported_by_connection_probe() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"message": "late", "tool_events": []})

    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        timeout_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(probe_http_agent_connection(adapter))

    assert result.status is ConnectionTestStatus.TIMEOUT
    assert result.http_status_code is None


def test_http_adapter_non_2xx_does_not_include_response_body() -> None:
    secret = "never-reflect-this-token"
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        bearer_token=SecretStr(secret),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, text=f"credential={secret}")
        ),
    )

    with pytest.raises(ExternalAgentHttpStatusError) as caught:
        asyncio.run(send_one_turn(adapter))

    assert caught.value.status_code == 401
    assert secret not in str(caught.value)


def test_connection_probe_distinguishes_invalid_json() -> None:
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json")
        ),
    )

    result = asyncio.run(probe_http_agent_connection(adapter))

    assert result.status is ConnectionTestStatus.INVALID_JSON


def test_connection_probe_distinguishes_http_schema_and_blocked_url() -> None:
    http_error = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )
    schema_error = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"message": "ok", "tool_events": "bad"})
        ),
    )
    blocked = HttpAgentAdapter(endpoint_url="http://127.0.0.1/agent")

    http_result = asyncio.run(probe_http_agent_connection(http_error))
    schema_result = asyncio.run(probe_http_agent_connection(schema_error))
    blocked_result = asyncio.run(probe_http_agent_connection(blocked))

    assert http_result.status is ConnectionTestStatus.HTTP_ERROR
    assert http_result.http_status_code == 503
    assert schema_result.status is ConnectionTestStatus.INVALID_RESPONSE_SCHEMA
    assert blocked_result.status is ConnectionTestStatus.BLOCKED_URL


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_events": []},
        {"message": "ok", "tool_events": [{"tool": "unknown", "arguments": {}}]},
        {
            "message": "ok",
            "tool_events": [
                {"tool": "lookup_policy", "arguments": {"policy_id": {"nested": True}}}
            ],
        },
    ],
)
def test_http_adapter_rejects_invalid_response_schema_and_tool_events(
    payload: dict[str, object],
) -> None:
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )

    with pytest.raises(InvalidAgentSchemaError):
        asyncio.run(send_one_turn(adapter))


def test_http_adapter_invalid_json_raises_typed_error() -> None:
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"{")
        ),
    )

    with pytest.raises(InvalidAgentJsonError):
        asyncio.run(send_one_turn(adapter))


def test_http_adapter_enforces_maximum_response_size() -> None:
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        max_response_bytes=1_024,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"x" * 1_025)
        ),
    )

    with pytest.raises(ExternalAgentResponseTooLargeError):
        asyncio.run(send_one_turn(adapter))


def test_http_adapter_does_not_follow_redirects() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(307, headers={"Location": "http://169.254.169.254/latest"})

    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ExternalAgentHttpStatusError) as caught:
        asyncio.run(send_one_turn(adapter))

    assert caught.value.status_code == 307
    assert requests == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost/agent",
        "https://service.localhost/agent",
        "https://127.0.0.1/agent",
        "https://[::1]/agent",
        "https://10.0.0.1/agent",
        "https://172.16.0.1/agent",
        "https://192.168.1.1/agent",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/computeMetadata/v1",
        "file:///etc/passwd",
        "https://user:password@93.184.216.34/agent",
        "https://93.184.216.34:0/agent",
    ],
)
def test_ssrf_policy_blocks_local_private_metadata_and_credential_urls(endpoint: str) -> None:
    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(validate_external_agent_endpoint(endpoint, production=False))


def test_ssrf_policy_blocks_hostname_resolving_to_private_address() -> None:
    async def private_resolver(_host: str, _port: int) -> Sequence[str]:
        return ["10.10.10.10"]

    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(
            validate_external_agent_endpoint(
                "https://agent.example.com/turn",
                production=True,
                resolver=private_resolver,
            )
        )


def test_production_requires_https_but_development_allows_public_http() -> None:
    with pytest.raises(UnsafeAgentEndpointError):
        asyncio.run(
            validate_external_agent_endpoint(
                "http://93.184.216.34/agent",
                production=True,
            )
        )

    asyncio.run(
        validate_external_agent_endpoint(
            "http://93.184.216.34/agent",
            production=False,
        )
    )


def test_transport_exception_and_runner_logs_redact_authorization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "top-secret-bearer-value"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Bearer {secret}", request=request)

    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        bearer_token=SecretStr(secret),
        transport=httpx.MockTransport(handler),
    )
    caplog.set_level(logging.ERROR)

    result = asyncio.run(ScenarioRunner().run(load_scenario_by_id("INS-004"), adapter))

    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.ADAPTER_ERROR
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_unexpected_transport_exception_is_sanitized_without_logging_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "unexpected-transport-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        raise ValueError(secret)

    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        bearer_token=SecretStr(secret),
        transport=httpx.MockTransport(handler),
    )
    caplog.set_level(logging.ERROR)

    result = asyncio.run(ScenarioRunner().run(load_scenario_by_id("INS-004"), adapter))

    assert result.error is not None
    assert result.error.category is ExecutionErrorCategory.ADAPTER_ERROR
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_validation_error_does_not_reflect_bearer_token() -> None:
    secret = "validation-secret-value"

    with TestClient(app) as client:
        response = client.post(
            "/api/agents/external/test-connection",
            json={"bearer_token": secret},
        )

    assert response.status_code == 422
    assert secret not in response.text


def test_bearer_control_characters_are_rejected_without_reflection() -> None:
    secret = "line-one\nline-two"

    with TestClient(app) as client:
        response = client.post(
            "/api/agents/external/test-connection",
            json={"endpoint_url": PUBLIC_ENDPOINT, "bearer_token": secret},
        )

    assert response.status_code == 422
    assert "line-one" not in response.text
    assert "line-two" not in response.text


def test_connection_test_endpoint_returns_typed_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = HttpAgentAdapter(
        endpoint_url=PUBLIC_ENDPOINT,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"message": "ready", "tool_events": []},
            )
        ),
    )
    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(main_module, "build_http_agent_adapter", lambda _request: adapter)

    with TestClient(app) as client:
        response = client.post(
            "/api/agents/external/test-connection",
            json={"endpoint_url": PUBLIC_ENDPOINT, "bearer_token": "ephemeral"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "External agent connection succeeded.",
        "http_status_code": None,
        "observed_tool_events": 0,
    }
