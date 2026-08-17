"""Optional agent_version metadata.

`agent_version` is user-supplied and purely descriptive. It must never displace
`agent_label` (which SINAMA derives from the executed agent/mode/target), and
clients that predate it must keep working unchanged.
"""

import asyncio
from collections.abc import Iterator

import pytest
from conftest import wait_for_api_run
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import AgentMode
from app.scenario_packs import ScenarioPackRegistry
from app.test_runs import (
    AGENT_VERSION_MAX_LENGTH,
    CreateTestRunRequest,
    InMemoryRunStore,
    RunService,
    run_store,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    run_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    run_store.clear()


def pack():  # type: ignore[no-untyped-def]
    return ScenarioPackRegistry().get_pack("insurance-v1")


# --- request model backwards compatibility ------------------------------------


def test_create_request_without_agent_version_still_validates() -> None:
    request = CreateTestRunRequest(pack_id="insurance-v1")

    assert request.agent_version is None


def test_create_request_accepts_an_agent_version() -> None:
    request = CreateTestRunRequest(pack_id="insurance-v1", agent_version="v1.4")

    assert request.agent_version == "v1.4"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_agent_version_normalizes_to_none(raw: str) -> None:
    assert CreateTestRunRequest(pack_id="insurance-v1", agent_version=raw).agent_version is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  v1.4  ", "v1.4"),
        ("prod-2026-08-17", "prod-2026-08-17"),
        ("claude-sonnet-4.5", "claude-sonnet-4.5"),
    ],
)
def test_agent_version_is_trimmed_but_otherwise_preserved(raw: str, expected: str) -> None:
    assert CreateTestRunRequest(pack_id="insurance-v1", agent_version=raw).agent_version == expected


def test_agent_version_longer_than_the_bound_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateTestRunRequest(
            pack_id="insurance-v1",
            agent_version="v" * (AGENT_VERSION_MAX_LENGTH + 1),
        )

    at_limit = "v" * AGENT_VERSION_MAX_LENGTH
    assert CreateTestRunRequest(pack_id="insurance-v1", agent_version=at_limit).agent_version


# --- memory store persistence and projection ----------------------------------


def test_memory_store_projects_agent_version_without_touching_agent_label() -> None:
    store = InMemoryRunStore()

    versioned = store.create_run(pack(), AgentMode.HEALTHY, agent_version="v2.0")
    unversioned = store.create_run(pack(), AgentMode.HEALTHY)

    assert versioned.agent_version == "v2.0"
    # agent_label keeps identifying the executed agent/mode, unchanged.
    assert versioned.agent_label == "healthy"
    assert unversioned.agent_version is None
    assert unversioned.agent_label == "healthy"


def test_memory_store_returns_agent_version_from_every_read_path() -> None:
    store = InMemoryRunStore()
    created = store.create_run(pack(), AgentMode.HEALTHY, agent_version="v3.1")
    store.mark_completed(created.run_id)

    assert store.get_run(created.run_id).agent_version == "v3.1"
    assert store.get_results(created.run_id).run.agent_version == "v3.1"
    assert store.list_runs()[0].agent_version == "v3.1"
    assert store.set_baseline(created.run_id).agent_version == "v3.1"


def test_run_service_forwards_agent_version_to_the_store() -> None:
    async def execute():  # type: ignore[no-untyped-def]
        store = InMemoryRunStore()
        service = RunService(store=store)
        created = await service.create_run(
            "insurance-v1",
            AgentMode.HEALTHY,
            agent_version="release-42",
        )
        return await service.wait_for_completion(created.run_id)

    summary = asyncio.run(execute())

    assert summary.agent_version == "release-42"
    assert summary.agent_label == "healthy"


# --- API ----------------------------------------------------------------------


def test_create_run_api_without_agent_version_is_unchanged(client: TestClient) -> None:
    response = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_mode": "healthy"},
    )

    assert response.status_code == 202
    assert response.json()["agent_version"] is None


def test_create_run_api_accepts_and_echoes_agent_version(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={
            "pack_id": "insurance-v1",
            "agent_mode": "healthy",
            "agent_version": "  v1.4  ",
        },
    )

    assert created.status_code == 202
    assert created.json()["agent_version"] == "v1.4"

    run_id = created.json()["run_id"]
    wait_for_api_run(client, run_id)

    assert client.get(f"/api/runs/{run_id}").json()["agent_version"] == "v1.4"
    assert client.get(f"/api/runs/{run_id}/results").json()["run"]["agent_version"] == "v1.4"
    assert client.get("/api/runs").json()[0]["agent_version"] == "v1.4"


def test_create_run_api_rejects_an_over_long_agent_version(client: TestClient) -> None:
    response = client.post(
        "/api/runs",
        json={
            "pack_id": "insurance-v1",
            "agent_version": "v" * (AGENT_VERSION_MAX_LENGTH + 1),
        },
    )

    assert response.status_code == 422


def test_blank_agent_version_from_the_api_is_stored_as_null(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={"pack_id": "insurance-v1", "agent_version": "   "},
    )

    assert created.status_code == 202
    assert created.json()["agent_version"] is None
