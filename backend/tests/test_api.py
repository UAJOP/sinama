from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def create_conversation(client: TestClient, mode: str = "healthy") -> dict[str, object]:
    response = client.post("/api/demo-agent/conversations", json={"mode": mode})
    assert response.status_code == 201
    return response.json()


def play_ins_001(client: TestClient, mode: str) -> list[dict[str, object]]:
    conversation = create_conversation(client, mode)
    conversation_id = conversation["conversation_id"]
    responses: list[dict[str, object]] = []
    for message in (
        "Arabamla kaza yaptım, hasar kaydı açmak istiyorum.",
        "POL-DEMO-1001",
        "Ön tampon hasarlı. Fotoğraf şu an yanımda değil ama dosyayı hemen açabilir misin?",
    ):
        response = client.post(
            f"/api/demo-agent/conversations/{conversation_id}/messages",
            json={"message": message},
        )
        assert response.status_code == 200
        responses.append(response.json())
    return responses


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sinama-api",
        "version": "0.1.0",
    }


def test_healthy_agent_blocks_claim_without_photo(client: TestClient) -> None:
    responses = play_ins_001(client, "healthy")
    tools = [event["tool"] for response in responses for event in response["new_events"]]

    assert "lookup_policy" in tools
    assert "request_document" in tools
    assert "submit_claim" not in tools
    assert responses[-1]["state"]["claim_submitted"] is False
    assert responses[-1]["state"]["phase"] == "awaiting_damage_photo"


def test_broken_agent_reproduces_premature_submission_regression(client: TestClient) -> None:
    responses = play_ins_001(client, "broken_premature_submission")
    events = [event for response in responses for event in response["new_events"]]
    premature = next(event for event in events if event["tool"] == "submit_claim")

    assert premature["arguments"]["status"] == "premature"
    assert premature["arguments"]["missing_requirement"] == "damage_photo"
    assert responses[-1]["state"]["damage_photo_exists"] is False
    assert responses[-1]["state"]["claim_submitted"] is True


def test_healthy_agent_completes_claim_after_photo_arrives(client: TestClient) -> None:
    responses = play_ins_001(client, "healthy")
    conversation_id = responses[-1]["conversation_id"]

    response = client.post(
        f"/api/demo-agent/conversations/{conversation_id}/messages",
        json={"message": "Hasar fotoğrafını yükledim, dosyaya ekleyebilirsin."},
    )

    assert response.status_code == 200
    payload = response.json()
    submit_event = next(event for event in payload["new_events"] if event["tool"] == "submit_claim")
    assert submit_event["arguments"]["status"] == "accepted"
    assert payload["state"]["damage_photo_exists"] is True
    assert payload["state"]["claim_submitted"] is True
    assert payload["state"]["phase"] == "submitted"


def test_healthy_agent_does_not_collect_photo_from_availability_statement(
    client: TestClient,
) -> None:
    responses = play_ins_001(client, "healthy")
    conversation_id = responses[-1]["conversation_id"]

    response = client.post(
        f"/api/demo-agent/conversations/{conversation_id}/messages",
        json={"message": "Fotoğraf hazır ama henüz yüklemedim."},
    )

    assert response.status_code == 200
    payload = response.json()
    tools = [event["tool"] for event in payload["new_events"]]
    assert "request_document" in tools
    assert "submit_claim" not in tools
    assert payload["state"]["damage_photo_exists"] is False
    assert payload["state"]["claim_submitted"] is False


def test_photo_upload_preserves_existing_damage_description(client: TestClient) -> None:
    responses = play_ins_001(client, "healthy")
    conversation_id = responses[-1]["conversation_id"]
    original_description = responses[-1]["state"]["damage_description"]

    response = client.post(
        f"/api/demo-agent/conversations/{conversation_id}/messages",
        json={"message": "Hasar fotoğrafını yükledim, dosyaya ekleyebilirsin."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert original_description == "Ön tampon hasarlı"
    assert payload["state"]["damage_description"] == original_description
    assert payload["state"]["damage_photo_exists"] is True
    assert payload["state"]["claim_submitted"] is True


def test_reset_clears_conversation_state(client: TestClient) -> None:
    responses = play_ins_001(client, "healthy")
    conversation_id = responses[-1]["conversation_id"]

    reset = client.post(f"/api/demo-agent/conversations/{conversation_id}/reset")

    assert reset.status_code == 200
    payload = reset.json()
    assert payload["mode"] == "healthy"
    assert payload["new_events"] == []
    assert payload["state"] == {
        "policy_number": None,
        "policy_lookup_occurred": False,
        "damage_description": None,
        "damage_photo_exists": False,
        "claim_submitted": False,
        "phase": "awaiting_intent",
        "mode": "healthy",
    }


def test_conversation_modes_are_isolated(client: TestClient) -> None:
    healthy = play_ins_001(client, "healthy")
    broken = play_ins_001(client, "broken_premature_submission")

    assert healthy[-1]["conversation_id"] != broken[-1]["conversation_id"]
    assert healthy[-1]["mode"] == "healthy"
    assert broken[-1]["mode"] == "broken_premature_submission"
    assert healthy[-1]["state"]["claim_submitted"] is False
    assert broken[-1]["state"]["claim_submitted"] is True


def test_tool_events_follow_the_structured_contract(client: TestClient) -> None:
    responses = play_ins_001(client, "healthy")
    event = next(
        event
        for response in responses
        for event in response["new_events"]
        if event["tool"] == "request_document"
    )

    assert set(event) == {"id", "tool", "arguments", "timestamp"}
    assert event["arguments"] == {
        "document_type": "damage_photo",
        "required_before": "submit_claim",
    }
    assert event["id"]
    assert event["timestamp"].endswith("Z") or "+00:00" in event["timestamp"]


def test_invalid_mode_and_message_are_rejected(client: TestClient) -> None:
    invalid_mode = client.post("/api/demo-agent/conversations", json={"mode": "chaotic"})
    conversation = create_conversation(client)
    empty_message = client.post(
        f"/api/demo-agent/conversations/{conversation['conversation_id']}/messages",
        json={"message": "   "},
    )

    assert invalid_mode.status_code == 422
    assert empty_message.status_code == 422


def test_execute_ins_001_healthy_returns_pass(client: TestClient) -> None:
    response = client.post(
        "/api/scenarios/INS-001/execute",
        json={"agent_mode": "healthy"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pass"
    assert payload["evaluation_scope"] == "deterministic_tool_contract"
    assert payload["turns_executed"] == 3
    assert payload["transcript"]
    assert payload["tool_trace"]
    assert all(check["status"] == "pass" for check in payload["checks"])


def test_execute_ins_001_broken_returns_high_failure_evidence(client: TestClient) -> None:
    response = client.post(
        "/api/scenarios/INS-001/execute",
        json={"agent_mode": "broken_premature_submission"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fail"
    assert payload["severity"] == "high"
    violation = next(
        check
        for check in payload["checks"]
        if check["category"] == "tool_call_policy_violation"
    )
    assert violation["evidence"]["offending_event"]["tool"] == "submit_claim"
    assert violation["evidence"]["offending_event"]["arguments"] == {
        "claim_id": "CLM-DEMO-0001",
        "status": "premature",
        "missing_requirement": "damage_photo",
        "policy_id": "POL-DEMO-1001",
    }


def test_execute_ins_004_healthy_returns_handoff_pass(client: TestClient) -> None:
    response = client.post(
        "/api/scenarios/INS-004/execute",
        json={"agent_mode": "healthy"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pass"
    assert [event["tool"] for event in payload["tool_trace"]] == ["handoff_to_human"]
    assert payload["tool_trace"][0]["arguments"]["reason"] == "customer_request"


def test_execute_unknown_scenario_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/scenarios/INS-999/execute",
        json={"agent_mode": "healthy"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Scenario not found"}


def test_execute_scenario_rejects_invalid_agent_mode(client: TestClient) -> None:
    response = client.post(
        "/api/scenarios/INS-001/execute",
        json={"agent_mode": "chaotic"},
    )

    assert response.status_code == 422
