from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.http_agent import ExternalTurnResponse
from app.models import ToolEvent, ToolIdentifier
from app.scenarios import StableScenarioId


def test_external_contract_accepts_domain_specific_tool_names() -> None:
    response = ExternalTurnResponse.model_validate(
        {
            "message": "İade talebi alındı.",
            "tool_events": [
                {
                    "tool": "refund_order",
                    "arguments": {"order_id": "ORD-1001"},
                }
            ],
        }
    )

    assert response.tool_events[0].tool == "refund_order"


def test_tool_event_keeps_generic_tool_identifier() -> None:
    event = ToolEvent(
        id=uuid4(),
        tool="banking.freeze_card",
        arguments={"card_id": "demo-card"},
        timestamp=datetime.now(UTC),
    )

    assert event.tool == "banking.freeze_card"


def test_tool_identifier_rejects_unsafe_or_blank_values() -> None:
    adapter = TypeAdapter(ToolIdentifier)

    with pytest.raises(ValidationError):
        adapter.validate_python("refund order")
    with pytest.raises(ValidationError):
        adapter.validate_python("   ")


def test_scenario_id_allows_future_vertical_prefixes() -> None:
    adapter = TypeAdapter(StableScenarioId)

    assert adapter.validate_python("ECOM-001") == "ECOM-001"
    assert adapter.validate_python("BANK-123") == "BANK-123"

    with pytest.raises(ValidationError):
        adapter.validate_python("unsafe-id")
