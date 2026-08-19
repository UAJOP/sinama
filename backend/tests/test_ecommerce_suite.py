import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agent_adapters import AgentAdapter, AgentSession, AgentTurnResult
from app.http_agent import ExternalAgentConfiguration
from app.models import AgentMode, AgentTarget, ToolEvent
from app.scenario_packs import ScenarioPackRegistry, ScenarioPackSummary
from app.scenario_runner import RunStatus, ScenarioRunResult
from app.scenarios import Scenario, load_scenario_by_id
from app.test_runs import InMemoryRunStore, InvalidRunAgentConfigurationError, RunService


def event(tool: str, arguments: dict[str, str | bool | int | float | None]) -> ToolEvent:
    return ToolEvent(
        id=uuid4(),
        tool=tool,
        arguments=arguments,
        timestamp=datetime.now(UTC),
    )


class EcommerceAdapter:
    @property
    def label(self) -> str:
        return "external_http"

    async def start_session(self) -> AgentSession:
        return AgentSession(session_id=str(uuid4()))

    async def send_message(self, _session: AgentSession, message: str) -> AgentTurnResult:
        if "ORD-DEMO-1001" in message:
            return AgentTurnResult(
                assistant_message="Siparişi doğruladım ve iadenizi oluşturdum.",
                tool_events=[
                    event(
                        "lookup_order",
                        {
                            "order_id": "ORD-DEMO-1001",
                            "found": True,
                            "return_eligible": True,
                        },
                    ),
                    event(
                        "refund_order",
                        {"order_id": "ORD-DEMO-1001", "resolution": "refund"},
                    ),
                ],
            )
        if "ORD-YANLIS-9999" in message:
            return AgentTurnResult(
                assistant_message="Bu siparişi bulamadım; numarayı kontrol eder misiniz?",
                tool_events=[
                    event(
                        "lookup_order",
                        {"order_id": "ORD-YANLIS-9999", "found": False},
                    )
                ],
            )
        if "ORD-DEMO-2002" in message:
            return AgentTurnResult(
                assistant_message="Siparişi doğruladım; uzman incelemesine aktarıyorum.",
                tool_events=[
                    event(
                        "lookup_order",
                        {"order_id": "ORD-DEMO-2002", "found": True},
                    ),
                    event(
                        "escalate_return_case",
                        {
                            "order_id": "ORD-DEMO-2002",
                            "reason": "damaged_high_value",
                        },
                    ),
                ],
            )
        if "ORD-DEMO-3003" in message:
            return AgentTurnResult(
                assistant_message="Siparişi doğruladım ve tek iade kaydını oluşturdum.",
                tool_events=[
                    event(
                        "lookup_order",
                        {
                            "order_id": "ORD-DEMO-3003",
                            "found": True,
                            "return_eligible": True,
                        },
                    ),
                    event(
                        "refund_order",
                        {"order_id": "ORD-DEMO-3003", "resolution": "refund"},
                    ),
                ],
            )
        if "bir daha" in message:
            return AgentTurnResult(
                assistant_message=(
                    "Aynı sipariş için mevcut iade kaydını kullanıyorum; ikinci iade açmıyorum."
                )
            )
        return AgentTurnResult(assistant_message="Sipariş numaranızı paylaşır mısınız?")


class RecordingPassingRunner:
    def __init__(self) -> None:
        self.scenario_ids: list[str] = []

    async def run(
        self,
        scenario: Scenario | None,
        adapter: AgentAdapter,
        *,
        turn_timeout_seconds: float = 5.0,
    ) -> ScenarioRunResult:
        assert scenario is not None
        self.scenario_ids.append(scenario.id)
        return ScenarioRunResult(
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            agent_label=adapter.label,
            status=RunStatus.PASS,
            turns_executed=0,
        )


def external_configuration() -> ExternalAgentConfiguration:
    return ExternalAgentConfiguration(
        endpoint_url="https://agent.example.com/turn",
        bearer_token=SecretStr("ephemeral-test-secret"),
    )


def test_registry_exposes_stable_ecommerce_pack_and_cross_vertical_suite() -> None:
    registry = ScenarioPackRegistry()

    packs = registry.list_packs()
    assert [pack.id for pack in packs] == ["insurance-v1", "ecommerce-v1"]
    ecommerce = packs[1]
    assert ecommerce.scenario_count == 4
    assert ecommerce.allowed_agent_targets == [AgentTarget.EXTERNAL_HTTP]
    assert [scenario.scenario_id for scenario in ecommerce.scenarios] == [
        "ECOM-001",
        "ECOM-002",
        "ECOM-003",
        "ECOM-004",
    ]

    suites = registry.list_suites()
    assert len(suites) == 1
    suite = suites[0]
    assert suite.id == "customer-service-core-v1"
    assert suite.pack_ids == ["insurance-v1", "ecommerce-v1"]
    assert suite.scenario_count == 14
    assert suite.allowed_agent_targets == [AgentTarget.EXTERNAL_HTTP]
    assert [scenario.scenario_id for scenario in suite.scenarios] == [
        "INS-001",
        "INS-002",
        "INS-003",
        "INS-004",
        "INS-005",
        "INS-006",
        "INS-007",
        "INS-008",
        "INS-009",
        "INS-010",
        "ECOM-001",
        "ECOM-002",
        "ECOM-003",
        "ECOM-004",
    ]


def test_historical_pack_snapshot_without_collection_fields_remains_valid() -> None:
    current = ScenarioPackRegistry().get_pack("insurance-v1").model_dump(mode="json")
    current.pop("kind")
    current.pop("included_pack_ids")
    current.pop("allowed_agent_targets")

    restored = ScenarioPackSummary.model_validate(current)

    assert restored.kind == "pack"
    assert restored.included_pack_ids == []
    assert restored.allowed_agent_targets == [
        AgentTarget.BUILT_IN_DEMO,
        AgentTarget.EXTERNAL_HTTP,
    ]


def test_ecommerce_scenarios_use_generic_domain_tools() -> None:
    first = load_scenario_by_id("ECOM-001")
    third = load_scenario_by_id("ECOM-003")

    assert [str(item.name) for item in first.expected_tool_calls] == [
        "lookup_order",
        "refund_order",
    ]
    assert str(third.expected_tool_calls[1].name) == "escalate_return_case"


def test_ecommerce_pack_rejects_the_insurance_built_in_agent() -> None:
    async def create() -> None:
        service = RunService(store=InMemoryRunStore())
        await service.create_run("ecommerce-v1", AgentMode.HEALTHY)

    with pytest.raises(InvalidRunAgentConfigurationError, match="external_http"):
        asyncio.run(create())


def test_real_ecommerce_pack_passes_through_generic_external_adapter() -> None:
    async def execute() -> tuple[InMemoryRunStore, ScenarioRunResult]:
        store = InMemoryRunStore()
        service = RunService(
            store=store,
            http_adapter_factory=lambda _configuration: EcommerceAdapter(),
        )
        created = await service.create_run(
            "ecommerce-v1",
            AgentMode.HEALTHY,
            agent_target=AgentTarget.EXTERNAL_HTTP,
            external_agent=external_configuration(),
        )
        completed = await service.wait_for_completion(created.run_id)
        assert completed.aggregate.passed == 4
        assert completed.aggregate.failed == 0
        assert completed.aggregate.errors == 0
        detail = store.get_result(created.run_id, "ECOM-004")
        return store, detail

    store, detail = asyncio.run(execute())

    assert detail.status is RunStatus.PASS
    assert [event_item.tool for event_item in detail.tool_trace] == [
        "lookup_order",
        "refund_order",
    ]
    assert all(run.pack_id == "ecommerce-v1" for run in store.list_runs())


def test_cross_vertical_suite_uses_one_run_pipeline_and_stable_order() -> None:
    async def execute() -> tuple[list[str], str, int]:
        runner = RecordingPassingRunner()
        store = InMemoryRunStore()
        service = RunService(
            store=store,
            runner=runner,
            http_adapter_factory=lambda _configuration: EcommerceAdapter(),
        )
        created = await service.create_run(
            "customer-service-core-v1",
            AgentMode.HEALTHY,
            agent_target=AgentTarget.EXTERNAL_HTTP,
            external_agent=external_configuration(),
        )
        completed = await service.wait_for_completion(created.run_id)
        return runner.scenario_ids, completed.pack_id, completed.aggregate.passed

    scenario_ids, collection_id, passed = asyncio.run(execute())

    assert collection_id == "customer-service-core-v1"
    assert passed == 14
    assert scenario_ids == [
        "INS-001",
        "INS-002",
        "INS-003",
        "INS-004",
        "INS-005",
        "INS-006",
        "INS-007",
        "INS-008",
        "INS-009",
        "INS-010",
        "ECOM-001",
        "ECOM-002",
        "ECOM-003",
        "ECOM-004",
    ]
