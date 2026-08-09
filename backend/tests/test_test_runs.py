import asyncio
import importlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.agent_adapters import AgentAdapter, DemoAgentAdapter
from app.http_agent import ExternalAgentConfiguration
from app.main import app
from app.models import AgentMode, AgentTarget
from app.scenario_packs import (
    ScenarioPackNotFoundError,
    ScenarioPackRegistry,
)
from app.scenario_runner import RunStatus, ScenarioRunResult, scenario_runner
from app.scenarios import Scenario
from app.test_runs import (
    RunService,
    RunStore,
    ScenarioResultNotFoundError,
    run_store,
)
from app.test_runs import (
    TestRunLifecycleStatus as LifecycleStatus,
)
from app.test_runs import (
    TestRunNotFoundError as RunNotFoundError,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    run_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    run_store.clear()


def wait_for_api_run(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["lifecycle_status"] in {"completed", "error"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("Test run did not reach a terminal lifecycle state")


async def execute_pack(
    mode: AgentMode,
    *,
    runner: object = scenario_runner,
    max_runs: int = 20,
) -> tuple[RunStore, dict[str, object]]:
    store = RunStore(max_runs=max_runs)
    service = RunService(store=store, runner=runner)  # type: ignore[arg-type]
    created = await service.create_run("insurance-v1", mode)
    completed = await service.wait_for_completion(created.run_id)
    return store, completed.model_dump(mode="json")


def test_insurance_pack_exists_with_ten_stably_ordered_scenarios() -> None:
    packs = ScenarioPackRegistry().list_packs()

    assert len(packs) == 1
    pack = packs[0]
    assert pack.id == "insurance-v1"
    assert pack.name == "Insurance Reliability Pack v1"
    assert pack.scenario_count == 10
    assert [scenario.scenario_id for scenario in pack.scenarios] == [
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
    ]


def test_unknown_pack_is_rejected_by_registry() -> None:
    registry = ScenarioPackRegistry()

    with pytest.raises(ScenarioPackNotFoundError):
        registry.get_pack("missing-pack")


def test_run_creation_generates_unique_ids() -> None:
    async def create_two() -> tuple[UUID, UUID]:
        store = RunStore()
        service = RunService(store=store)
        first = await service.create_run("insurance-v1", AgentMode.HEALTHY)
        second = await service.create_run("insurance-v1", AgentMode.HEALTHY)
        await service.wait_for_completion(first.run_id)
        await service.wait_for_completion(second.run_id)
        return first.run_id, second.run_id

    first_id, second_id = asyncio.run(create_two())
    assert first_id != second_id


def test_healthy_pack_executes_all_scenarios_with_actual_aggregate() -> None:
    store, payload = asyncio.run(execute_pack(AgentMode.HEALTHY))
    run_id = UUID(str(payload["run_id"]))
    results = store.get_results(run_id)

    assert payload["lifecycle_status"] == "completed"
    assert payload["aggregate"] == {"total": 10, "passed": 10, "failed": 0, "errors": 0}
    assert [result.scenario_id for result in results.results] == [
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
    ]
    assert all(result.status is RunStatus.PASS for result in results.results)


def test_broken_pack_uses_observed_results_and_preserves_ins_001_evidence() -> None:
    store, payload = asyncio.run(execute_pack(AgentMode.BROKEN_PREMATURE_SUBMISSION))
    run_id = UUID(str(payload["run_id"]))
    summaries = store.get_results(run_id).results
    detail = store.get_result(run_id, "INS-001")

    assert payload["lifecycle_status"] == "completed"
    assert payload["aggregate"] == {"total": 10, "passed": 5, "failed": 5, "errors": 0}
    assert [(item.scenario_id, item.status.value) for item in summaries] == [
        ("INS-001", "fail"),
        ("INS-002", "pass"),
        ("INS-003", "pass"),
        ("INS-004", "pass"),
        ("INS-005", "fail"),
        ("INS-006", "fail"),
        ("INS-007", "pass"),
        ("INS-008", "fail"),
        ("INS-009", "fail"),
        ("INS-010", "pass"),
    ]
    assert detail.status is RunStatus.FAIL
    assert detail.severity is not None and detail.severity.value == "high"
    assert [check.check_id for check in detail.checks if check.status.value == "fail"] == [
        "required_tool:2:request_document",
        "forbidden_tool:1:submit_claim",
    ]
    offending = next(
        check.evidence.offending_event
        for check in detail.checks
        if check.evidence.offending_event is not None
    )
    assert offending.arguments["status"] == "premature"
    assert offending.arguments["missing_requirement"] == "damage_photo"


def test_external_target_uses_same_runner_without_persisting_credentials() -> None:
    secret = "run-only-secret"
    configurations: list[ExternalAgentConfiguration] = []

    def external_factory(configuration: ExternalAgentConfiguration) -> AgentAdapter:
        configurations.append(configuration)
        return DemoAgentAdapter(AgentMode.HEALTHY, configuration_label="external_http")

    async def execute() -> tuple[RunStore, dict[str, object]]:
        store = RunStore()
        service = RunService(store=store, http_adapter_factory=external_factory)
        created = await service.create_run(
            "insurance-v1",
            AgentMode.HEALTHY,
            agent_target=AgentTarget.EXTERNAL_HTTP,
            external_agent=ExternalAgentConfiguration(
                endpoint_url="https://agent.example.com/turn",
                bearer_token=SecretStr(secret),
            ),
        )
        completed = await service.wait_for_completion(created.run_id)
        return store, completed.model_dump(mode="json")

    store, payload = asyncio.run(execute())
    run_id = UUID(str(payload["run_id"]))

    assert payload["agent_target"] == "external_http"
    assert payload["agent_label"] == "external_http"
    assert payload["aggregate"] == {"total": 10, "passed": 10, "failed": 0, "errors": 0}
    assert len(configurations) == 10
    assert secret not in store.get_run(run_id).model_dump_json()
    assert secret not in store.get_results(run_id).model_dump_json()


def test_completed_run_detail_is_returned_as_an_immutable_copy() -> None:
    store, payload = asyncio.run(execute_pack(AgentMode.HEALTHY))
    run_id = UUID(str(payload["run_id"]))

    first = store.get_result(run_id, "INS-001")
    first.transcript.clear()
    first.tool_trace.clear()
    second = store.get_result(run_id, "INS-001")

    assert second.transcript
    assert second.tool_trace


def test_store_supports_lifecycle_states_and_bounded_retention() -> None:
    store = RunStore(max_runs=2)
    pack = ScenarioPackRegistry().get_pack("insurance-v1")
    first = store.create_run(pack, AgentMode.HEALTHY)
    assert first.lifecycle_status is LifecycleStatus.QUEUED
    store.mark_running(first.run_id)
    assert store.get_run(first.run_id).lifecycle_status is LifecycleStatus.RUNNING
    store.mark_completed(first.run_id)
    assert store.get_run(first.run_id).lifecycle_status is LifecycleStatus.COMPLETED

    second = store.create_run(pack, AgentMode.HEALTHY)
    store.mark_error(second.run_id, "Safe failure")
    assert store.get_run(second.run_id).lifecycle_status is LifecycleStatus.ERROR
    third = store.create_run(pack, AgentMode.HEALTHY)

    assert len(store) == 2
    with pytest.raises(RunNotFoundError):
        store.get_run(first.run_id)
    assert store.get_run(third.run_id).lifecycle_status is LifecycleStatus.QUEUED


class ExplodingRunner:
    async def run(
        self,
        scenario: Scenario | None,
        adapter: AgentAdapter,
        *,
        turn_timeout_seconds: float = 5.0,
    ) -> ScenarioRunResult:
        raise RuntimeError("private orchestration details")


def test_orchestration_exception_sets_safe_run_error() -> None:
    store, payload = asyncio.run(
        execute_pack(AgentMode.HEALTHY, runner=ExplodingRunner())
    )
    run_id = UUID(str(payload["run_id"]))
    summary = store.get_run(run_id)

    assert summary.lifecycle_status is LifecycleStatus.ERROR
    assert summary.error is not None
    assert summary.error.category == "run_orchestration_error"
    assert "private orchestration" not in summary.error.reason
    assert summary.completed_scenarios == 0


def test_unknown_run_and_result_are_rejected_by_store() -> None:
    store = RunStore()

    with pytest.raises(RunNotFoundError):
        store.get_run(uuid4())

    pack = ScenarioPackRegistry().get_pack("insurance-v1")
    run = store.create_run(pack, AgentMode.HEALTHY)
    with pytest.raises(ScenarioResultNotFoundError):
        store.get_result(run.run_id, "INS-999")


def test_scenario_pack_api_returns_real_fixture_metadata(client: TestClient) -> None:
    response = client.get("/api/scenario-packs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "insurance-v1"
    assert payload[0]["scenario_count"] == 10
    assert [item["scenario_id"] for item in payload[0]["scenarios"]] == [
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
    ]


def test_all_pack_scenarios_load_with_backend_as_working_directory(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    response = client.get("/api/scenario-packs")

    assert response.status_code == 200
    referenced_ids = [
        scenario["scenario_id"]
        for pack in response.json()
        for scenario in pack["scenarios"]
    ]
    loaded_ids = [
        scenario.id
        for pack in response.json()
        for scenario in ScenarioPackRegistry().load_scenarios(pack["id"])
    ]
    assert loaded_ids == referenced_ids


@pytest.mark.parametrize("mode", ["healthy", "broken_premature_submission"])
def test_run_api_accepts_both_demo_modes(client: TestClient, mode: str) -> None:
    response = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_mode": mode},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["agent_mode"] == mode
    assert payload["agent_target"] == "built_in_demo"
    terminal = wait_for_api_run(client, payload["run_id"])
    assert terminal["lifecycle_status"] == "completed"
    assert terminal["completed_scenarios"] == 10


def test_external_run_api_uses_ephemeral_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "api-run-secret"

    def external_factory(_configuration: ExternalAgentConfiguration) -> AgentAdapter:
        return DemoAgentAdapter(AgentMode.HEALTHY, configuration_label="external_http")

    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(
        main_module,
        "run_service",
        RunService(store=run_store, http_adapter_factory=external_factory),
    )

    response = client.post(
        "/api/runs",
        json={
            "pack_id": "insurance-v1",
            "agent_target": "external_http",
            "external_agent": {
                "endpoint_url": "https://agent.example.com/turn",
                "bearer_token": secret,
            },
        },
    )

    assert response.status_code == 202
    assert response.json()["agent_target"] == "external_http"
    assert secret not in response.text
    terminal = wait_for_api_run(client, response.json()["run_id"])
    assert terminal["aggregate"] == {"total": 10, "passed": 10, "failed": 0, "errors": 0}
    assert secret not in json.dumps(terminal)


def test_run_api_rejects_invalid_mode_and_unknown_pack(client: TestClient) -> None:
    invalid_mode = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_mode": "chaotic"},
    )
    unknown_pack = client.post(
        "/api/runs",
        json={"pack_id": "missing-pack", "agent_mode": "healthy"},
    )
    missing_external_configuration = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_target": "external_http"},
    )

    assert invalid_mode.status_code == 422
    assert unknown_pack.status_code == 404
    assert unknown_pack.json() == {"detail": "Scenario pack not found"}
    assert missing_external_configuration.status_code == 422
    assert missing_external_configuration.json() == {
        "detail": "External HTTP runs require endpoint configuration."
    }


def test_run_result_apis_return_summary_and_full_detail(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_mode": "broken_premature_submission"},
    ).json()
    wait_for_api_run(client, created["run_id"])

    results = client.get(f"/api/runs/{created['run_id']}/results")
    detail = client.get(f"/api/runs/{created['run_id']}/results/INS-001")

    assert results.status_code == 200
    assert len(results.json()["results"]) == 10
    assert results.json()["results"][0]["failed_check_count"] == 2
    assert detail.status_code == 200
    assert detail.json()["status"] == "fail"
    assert detail.json()["checks"]
    assert detail.json()["transcript"]
    assert detail.json()["tool_trace"]
    assert detail.json()["unscored_declared_checks"]


def test_run_api_returns_404_for_unknown_run_and_result(client: TestClient) -> None:
    unknown_run_id = uuid4()
    unknown_run = client.get(f"/api/runs/{unknown_run_id}")

    created = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_mode": "healthy"},
    ).json()
    wait_for_api_run(client, created["run_id"])
    unknown_result = client.get(f"/api/runs/{created['run_id']}/results/INS-999")

    assert unknown_run.status_code == 404
    assert unknown_run.json() == {"detail": "Test run not found"}
    assert unknown_result.status_code == 404
    assert unknown_result.json() == {"detail": "Scenario result not found"}
