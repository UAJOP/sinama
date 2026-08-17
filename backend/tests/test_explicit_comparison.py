"""Explicit run-to-run comparison: reference -> current.

Independent of baseline assignment. Exercised against both stores, because the
two backends load records differently and must agree.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import wait_for_api_run
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.db.models import Base
from app.db.sql_run_store import SqlRunStore
from app.main import app
from app.models import AgentMode
from app.regression import RegressionStatus
from app.scenario_packs import ScenarioPackRegistry
from app.test_runs import (
    ExplicitRunComparisonResponse,
    IncompatibleRunComparisonError,
    InMemoryRunStore,
    RunNotCompletedError,
    RunService,
    RunStore,
    run_store,
)
from app.test_runs import TestRunNotFoundError as RunNotFoundError


@pytest.fixture
def client() -> Iterator[TestClient]:
    run_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    run_store.clear()


@pytest.fixture
def sql_store(tmp_path: Path) -> Iterator[SqlRunStore]:
    engine: Engine = create_engine(f"sqlite:///{tmp_path / 'compare.db'}", future=True)
    Base.metadata.create_all(engine)
    yield SqlRunStore(engine)
    engine.dispose()


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest, sql_store: SqlRunStore) -> RunStore:
    """Both backends must produce identical explicit-comparison behavior."""

    return InMemoryRunStore() if request.param == "memory" else sql_store


def pack():  # type: ignore[no-untyped-def]
    return ScenarioPackRegistry().get_pack("insurance-v1")


def execute_pack(store: RunStore, mode: AgentMode, *, agent_version: str | None = None):  # type: ignore[no-untyped-def]
    async def run():  # type: ignore[no-untyped-def]
        service = RunService(store=store)
        created = await service.create_run(
            "insurance-v1", mode, agent_version=agent_version
        )
        return await service.wait_for_completion(created.run_id)

    return asyncio.run(run())


# --- success ------------------------------------------------------------------


def test_compare_runs_detects_regression_from_reference_to_current(store: RunStore) -> None:
    reference = execute_pack(store, AgentMode.HEALTHY, agent_version="v1")
    current = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, agent_version="v2")

    response = store.compare_runs(reference.run_id, current.run_id)

    assert isinstance(response, ExplicitRunComparisonResponse)
    assert response.reference_run.run_id == reference.run_id
    assert response.current_run.run_id == current.run_id
    assert response.reference_run.agent_version == "v1"
    assert response.current_run.agent_version == "v2"
    assert response.comparison.baseline_run_id == reference.run_id
    assert response.comparison.current_run_id == current.run_id
    assert response.comparison.status is RegressionStatus.REGRESSION
    assert response.comparison.score_delta < 0
    assert response.comparison.new_failures


def test_comparison_direction_is_not_symmetric(store: RunStore) -> None:
    """Swapping reference and current must invert the verdict, not repeat it."""

    healthy = execute_pack(store, AgentMode.HEALTHY)
    broken = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    regressed = store.compare_runs(healthy.run_id, broken.run_id).comparison
    improved = store.compare_runs(broken.run_id, healthy.run_id).comparison

    assert regressed.status is RegressionStatus.REGRESSION
    assert improved.status is RegressionStatus.IMPROVED
    assert regressed.score_delta == -improved.score_delta
    # New failures in one direction are the resolved failures in the other.
    assert {entry.scenario_id for entry in regressed.new_failures} == {
        entry.scenario_id for entry in improved.resolved_failures
    }


def test_comparing_two_identical_healthy_runs_is_stable(store: RunStore) -> None:
    first = execute_pack(store, AgentMode.HEALTHY)
    second = execute_pack(store, AgentMode.HEALTHY)

    comparison = store.compare_runs(first.run_id, second.run_id).comparison

    assert comparison.status is RegressionStatus.STABLE
    assert comparison.score_delta == 0
    assert comparison.new_failures == []
    assert comparison.resolved_failures == []


# --- baseline independence ----------------------------------------------------


def test_explicit_comparison_does_not_change_baseline_assignment(store: RunStore) -> None:
    baseline = execute_pack(store, AgentMode.HEALTHY)
    store.set_baseline(baseline.run_id)
    other = execute_pack(store, AgentMode.HEALTHY)
    current = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    store.compare_runs(other.run_id, current.run_id)

    assert store.get_run(baseline.run_id).is_baseline is True
    assert store.get_run(other.run_id).is_baseline is False
    assert store.get_run(current.run_id).is_baseline is False


def test_explicit_comparison_works_without_any_baseline(store: RunStore) -> None:
    reference = execute_pack(store, AgentMode.HEALTHY)
    current = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    response = store.compare_runs(reference.run_id, current.run_id)

    assert response.comparison.status is RegressionStatus.REGRESSION
    assert response.reference_run.is_baseline is False


def test_baseline_comparison_endpoint_behavior_is_unaffected(store: RunStore) -> None:
    baseline = execute_pack(store, AgentMode.HEALTHY)
    store.set_baseline(baseline.run_id)
    current = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)
    before = store.get_comparison(current.run_id)

    store.compare_runs(current.run_id, baseline.run_id)
    after = store.get_comparison(current.run_id)

    assert before.model_dump(mode="json") == after.model_dump(mode="json")


# --- rejection ----------------------------------------------------------------


def test_same_run_comparison_is_rejected(store: RunStore) -> None:
    run = execute_pack(store, AgentMode.HEALTHY)

    with pytest.raises(IncompatibleRunComparisonError, match="itself"):
        store.compare_runs(run.run_id, run.run_id)


def test_missing_run_on_either_side_raises_not_found(store: RunStore) -> None:
    existing = execute_pack(store, AgentMode.HEALTHY)

    with pytest.raises(RunNotFoundError):
        store.compare_runs(uuid4(), existing.run_id)
    with pytest.raises(RunNotFoundError):
        store.compare_runs(existing.run_id, uuid4())


def test_non_completed_run_on_either_side_is_rejected(store: RunStore) -> None:
    completed = execute_pack(store, AgentMode.HEALTHY)
    queued = store.create_run(pack(), AgentMode.HEALTHY)

    with pytest.raises(RunNotCompletedError, match="reference"):
        store.compare_runs(queued.run_id, completed.run_id)
    with pytest.raises(RunNotCompletedError, match="current"):
        store.compare_runs(completed.run_id, queued.run_id)


def test_errored_run_cannot_be_compared(store: RunStore) -> None:
    completed = execute_pack(store, AgentMode.HEALTHY)
    failed = store.create_run(pack(), AgentMode.HEALTHY)
    store.mark_error(failed.run_id, "Safe failure")

    with pytest.raises(RunNotCompletedError):
        store.compare_runs(failed.run_id, completed.run_id)


def test_different_scenario_sets_are_rejected(store: RunStore) -> None:
    full = execute_pack(store, AgentMode.HEALTHY)

    truncated_pack = pack().model_copy(update={"scenarios": pack().scenarios[:5]})
    partial = store.create_run(truncated_pack, AgentMode.HEALTHY)
    store.mark_completed(partial.run_id)

    with pytest.raises(IncompatibleRunComparisonError, match="same set of scenarios"):
        store.compare_runs(full.run_id, partial.run_id)


def test_different_scenario_packs_are_rejected(store: RunStore) -> None:
    same_pack = execute_pack(store, AgentMode.HEALTHY)

    other_pack = pack().model_copy(update={"id": "insurance-v2"})
    other = store.create_run(other_pack, AgentMode.HEALTHY)
    store.mark_completed(other.run_id)

    with pytest.raises(IncompatibleRunComparisonError, match="different scenario packs"):
        store.compare_runs(other.run_id, same_pack.run_id)


# --- persistence --------------------------------------------------------------


def test_explicit_comparison_survives_a_store_restart(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'restart.db'}", future=True)
    Base.metadata.create_all(engine)

    first = SqlRunStore(engine)
    reference = execute_pack(first, AgentMode.HEALTHY, agent_version="v1.0")
    current = execute_pack(first, AgentMode.BROKEN_PREMATURE_SUBMISSION, agent_version="v2.0")
    before = first.compare_runs(reference.run_id, current.run_id)

    restarted = SqlRunStore(engine)
    after = restarted.compare_runs(reference.run_id, current.run_id)

    assert after.model_dump(mode="json") == before.model_dump(mode="json")
    assert after.reference_run.agent_version == "v1.0"
    assert after.current_run.agent_version == "v2.0"
    engine.dispose()


# --- API ----------------------------------------------------------------------


def create_api_run(client: TestClient, mode: str, version: str | None = None) -> dict[str, str]:
    payload: dict[str, object] = {"pack_id": "insurance-v1", "agent_mode": mode}
    if version is not None:
        payload["agent_version"] = version
    created = client.post("/api/runs", json=payload).json()
    wait_for_api_run(client, created["run_id"])
    return created


def test_compare_api_returns_both_runs_and_the_comparison(client: TestClient) -> None:
    reference = create_api_run(client, "healthy", "v1")
    current = create_api_run(client, "broken_premature_submission", "v2")

    response = client.get(f"/api/runs/{current['run_id']}/compare/{reference['run_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reference_run"]["run_id"] == reference["run_id"]
    assert payload["reference_run"]["agent_version"] == "v1"
    assert payload["current_run"]["run_id"] == current["run_id"]
    assert payload["current_run"]["agent_version"] == "v2"
    assert payload["comparison"]["status"] == "regression"
    assert payload["comparison"]["new_failures"]


def test_compare_api_url_direction_is_current_then_reference(client: TestClient) -> None:
    healthy = create_api_run(client, "healthy")
    broken = create_api_run(client, "broken_premature_submission")

    regressed = client.get(f"/api/runs/{broken['run_id']}/compare/{healthy['run_id']}").json()
    improved = client.get(f"/api/runs/{healthy['run_id']}/compare/{broken['run_id']}").json()

    assert regressed["comparison"]["status"] == "regression"
    assert improved["comparison"]["status"] == "improved"


def test_compare_api_rejects_unknown_runs(client: TestClient) -> None:
    existing = create_api_run(client, "healthy")

    assert client.get(f"/api/runs/{existing['run_id']}/compare/{uuid4()}").status_code == 404
    assert client.get(f"/api/runs/{uuid4()}/compare/{existing['run_id']}").status_code == 404


def test_compare_api_rejects_the_same_run(client: TestClient) -> None:
    run = create_api_run(client, "healthy")

    response = client.get(f"/api/runs/{run['run_id']}/compare/{run['run_id']}")

    assert response.status_code == 422
    assert "itself" in response.json()["detail"]


def test_compare_api_rejects_a_non_completed_run(client: TestClient) -> None:
    completed = create_api_run(client, "healthy")
    # Created directly on the store so it stays queued - going through the API
    # would race the executor and make this assertion flaky.
    queued = run_store.create_run(pack(), AgentMode.HEALTHY)

    response = client.get(f"/api/runs/{completed['run_id']}/compare/{queued.run_id}")

    # 409 rather than 404/422: the run exists and the request is well-formed,
    # it is the run's state that makes the comparison impossible.
    assert response.status_code == 409
    assert "completed" in response.json()["detail"].lower()


def test_baseline_endpoint_is_untouched_by_explicit_comparison(client: TestClient) -> None:
    baseline = create_api_run(client, "healthy")
    client.post(f"/api/runs/{baseline['run_id']}/baseline")
    current = create_api_run(client, "broken_premature_submission")
    other = create_api_run(client, "healthy")

    before = client.get(f"/api/runs/{current['run_id']}/comparison").json()
    client.get(f"/api/runs/{current['run_id']}/compare/{other['run_id']}")
    after = client.get(f"/api/runs/{current['run_id']}/comparison").json()

    assert before == after
    assert client.get(f"/api/runs/{baseline['run_id']}").json()["is_baseline"] is True
    assert client.get(f"/api/runs/{other['run_id']}").json()["is_baseline"] is False
