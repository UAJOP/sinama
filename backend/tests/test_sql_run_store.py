"""Persistence tests for the SQLAlchemy run store.

These run against SQLite so the default suite needs no database service, no
Supabase account and no network. The store code under test is the same code that
runs on PostgreSQL - only the dialect differs (see `app.db.models.JsonPayload`).

`tests/test_sql_run_store_postgres.py` covers the PostgreSQL-specific path and is
skipped unless SINAMA_TEST_DATABASE_URL is provided.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine, create_engine, select

from app.agent_adapters import AgentAdapter, DemoAgentAdapter
from app.config import RunStoreBackend, Settings
from app.db.models import Base, ScenarioResultRow
from app.db.models import TestRunRow as RunRow
from app.db.sql_run_store import SqlRunStore
from app.http_agent import ExternalAgentConfiguration
from app.models import AgentMode, AgentTarget
from app.regression import ComparisonAvailability, RegressionStatus
from app.scenario_packs import ScenarioPackRegistry
from app.scenario_runner import RunStatus
from app.test_runs import (
    RunNotCompletedError,
    RunService,
    ScenarioResultNotFoundError,
)
from app.test_runs import TestRunLifecycleStatus as LifecycleStatus
from app.test_runs import TestRunNotFoundError as RunNotFoundError


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A file-backed SQLite database, so a second store instance can reopen it."""

    created = create_engine(f"sqlite:///{tmp_path / 'runs.db'}", future=True)
    Base.metadata.create_all(created)
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlRunStore:
    return SqlRunStore(engine)


def pack():  # type: ignore[no-untyped-def]
    return ScenarioPackRegistry().get_pack("insurance-v1")


async def _execute_pack(store: SqlRunStore, mode: AgentMode):  # type: ignore[no-untyped-def]
    service = RunService(store=store)
    created = await service.create_run("insurance-v1", mode)
    return await service.wait_for_completion(created.run_id)


def execute_pack(store: SqlRunStore, mode: AgentMode = AgentMode.HEALTHY):  # type: ignore[no-untyped-def]
    return asyncio.run(_execute_pack(store, mode))


# --- store behavior -----------------------------------------------------------


def test_create_run_persists_queued_run_with_pack_snapshot(store: SqlRunStore) -> None:
    created = store.create_run(pack(), AgentMode.HEALTHY)

    reread = store.get_run(created.run_id)
    assert reread.run_id == created.run_id
    assert reread.lifecycle_status is LifecycleStatus.QUEUED
    assert reread.pack_id == "insurance-v1"
    assert reread.total_scenarios == 10
    assert reread.completed_scenarios == 0
    assert reread.aggregate.total == 10
    assert reread.is_baseline is False
    assert reread.created_at.tzinfo is not None


def test_lifecycle_updates_are_persisted(store: SqlRunStore) -> None:
    created = store.create_run(pack(), AgentMode.HEALTHY)

    store.mark_running(created.run_id)
    running = store.get_run(created.run_id)
    store.mark_completed(created.run_id)
    completed = store.get_run(created.run_id)

    assert running.lifecycle_status is LifecycleStatus.RUNNING
    assert running.started_at is not None and running.started_at.tzinfo is not None
    assert completed.lifecycle_status is LifecycleStatus.COMPLETED
    assert completed.completed_at is not None and completed.completed_at.tzinfo is not None


def test_mark_error_persists_safe_reason(store: SqlRunStore) -> None:
    created = store.create_run(pack(), AgentMode.HEALTHY)

    store.mark_error(created.run_id, "Safe failure")
    summary = store.get_run(created.run_id)

    assert summary.lifecycle_status is LifecycleStatus.ERROR
    assert summary.error is not None
    assert summary.error.category == "run_orchestration_error"
    assert summary.error.reason == "Safe failure"


def test_lifecycle_updates_on_unknown_run_raise_not_found(store: SqlRunStore) -> None:
    with pytest.raises(RunNotFoundError):
        store.mark_running(uuid4())
    with pytest.raises(RunNotFoundError):
        store.mark_completed(uuid4())
    with pytest.raises(RunNotFoundError):
        store.get_run(uuid4())


def test_completed_run_reconstructs_full_results_in_pack_order(store: SqlRunStore) -> None:
    summary = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    results = store.get_results(summary.run_id)
    detail = store.get_result(summary.run_id, "INS-001")

    assert summary.lifecycle_status is LifecycleStatus.COMPLETED
    assert summary.aggregate.model_dump() == {
        "total": 10,
        "passed": 5,
        "failed": 5,
        "errors": 0,
    }
    assert [item.scenario_id for item in results.results] == [
        f"INS-{index:03d}" for index in range(1, 11)
    ]
    # Full evaluator evidence survives the JSON round trip.
    assert detail.status is RunStatus.FAIL
    assert detail.severity is not None and detail.severity.value == "high"
    assert detail.checks and detail.transcript and detail.tool_trace
    assert detail.metrics and detail.failures
    offending = next(
        check.evidence.offending_event
        for check in detail.checks
        if check.evidence.offending_event is not None
    )
    assert offending.arguments["missing_requirement"] == "damage_photo"


def test_result_ordering_is_position_based_not_insertion_id(store: SqlRunStore) -> None:
    summary = execute_pack(store)

    with store._sessions() as session:  # noqa: SLF001 - asserting the storage contract
        positions = list(
            session.scalars(
                select(ScenarioResultRow.position)
                .where(ScenarioResultRow.run_id == summary.run_id)
                .order_by(ScenarioResultRow.position)
            )
        )
    assert positions == list(range(10))


def test_error_run_reconstruction_preserves_orchestration_error(store: SqlRunStore) -> None:
    class ExplodingRunner:
        async def run(self, scenario, adapter, *, turn_timeout_seconds: float = 5.0):  # type: ignore[no-untyped-def]
            raise RuntimeError("private orchestration details")

    async def execute():  # type: ignore[no-untyped-def]
        service = RunService(store=store, runner=ExplodingRunner())  # type: ignore[arg-type]
        created = await service.create_run("insurance-v1", AgentMode.HEALTHY)
        return await service.wait_for_completion(created.run_id)

    summary = asyncio.run(execute())
    reread = store.get_run(summary.run_id)

    assert reread.lifecycle_status is LifecycleStatus.ERROR
    assert reread.error is not None
    assert "private orchestration" not in reread.error.reason
    assert reread.completed_scenarios == 0


def test_unknown_scenario_result_raises_not_found(store: SqlRunStore) -> None:
    summary = execute_pack(store)

    with pytest.raises(ScenarioResultNotFoundError):
        store.get_result(summary.run_id, "INS-999")


# --- restart persistence ------------------------------------------------------


def test_completed_run_and_results_survive_a_new_store_instance(engine: Engine) -> None:
    first = SqlRunStore(engine)
    summary = execute_pack(first, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    # A second store over the same database stands in for a restarted process.
    second = SqlRunStore(engine)
    reread = second.get_run(summary.run_id)
    results = second.get_results(summary.run_id)
    detail = second.get_result(summary.run_id, "INS-001")

    assert reread.lifecycle_status is LifecycleStatus.COMPLETED
    assert reread.aggregate.failed == 5
    assert len(results.results) == 10
    assert detail.checks and detail.failures


def test_agent_version_is_persisted_and_reloaded(store: SqlRunStore) -> None:
    versioned = store.create_run(pack(), AgentMode.HEALTHY, agent_version="prod-2026-08-17")
    unversioned = store.create_run(pack(), AgentMode.HEALTHY)

    assert store.get_run(versioned.run_id).agent_version == "prod-2026-08-17"
    # agent_label stays SINAMA-derived and is not displaced by the version.
    assert store.get_run(versioned.run_id).agent_label == "healthy"
    assert store.get_run(unversioned.run_id).agent_version is None


def test_agent_version_survives_a_new_store_instance(engine: Engine) -> None:
    first = SqlRunStore(engine)
    summary = execute_pack(first, AgentMode.HEALTHY)
    versioned = first.create_run(pack(), AgentMode.HEALTHY, agent_version="v9.9")
    first.mark_completed(versioned.run_id)

    second = SqlRunStore(engine)

    assert second.get_run(versioned.run_id).agent_version == "v9.9"
    assert second.get_run(summary.run_id).agent_version is None
    by_id = {item.run_id: item for item in second.list_runs()}
    assert by_id[versioned.run_id].agent_version == "v9.9"
    assert second.get_results(versioned.run_id).run.agent_version == "v9.9"


def test_baseline_survives_a_new_store_instance(engine: Engine) -> None:
    first = SqlRunStore(engine)
    baseline = execute_pack(first, AgentMode.HEALTHY)
    first.set_baseline(baseline.run_id)

    second = SqlRunStore(engine)

    assert second.get_run(baseline.run_id).is_baseline is True
    assert second.get_comparison(baseline.run_id).status is ComparisonAvailability.IS_BASELINE


def test_core_acceptance_flow_regression_still_works_after_restart(engine: Engine) -> None:
    """Healthy run -> baseline -> broken run -> restart -> same regression."""

    first = SqlRunStore(engine)
    healthy = execute_pack(first, AgentMode.HEALTHY)
    first.set_baseline(healthy.run_id)
    broken = execute_pack(first, AgentMode.BROKEN_PREMATURE_SUBMISSION)
    before = first.get_comparison(broken.run_id)

    restarted = SqlRunStore(engine)
    after = restarted.get_comparison(broken.run_id)

    assert before.status is ComparisonAvailability.AVAILABLE
    assert after.status is ComparisonAvailability.AVAILABLE
    assert after.comparison is not None and before.comparison is not None
    assert after.comparison.status is RegressionStatus.REGRESSION
    assert after.comparison.baseline_run_id == healthy.run_id
    assert after.comparison.current_run_id == broken.run_id
    # Identical verdict and evidence before and after the simulated restart.
    assert after.comparison.model_dump(mode="json") == before.comparison.model_dump(mode="json")
    assert {entry.scenario_id for entry in after.comparison.new_failures}
    assert restarted.get_run(healthy.run_id).is_baseline is True


# --- baseline -----------------------------------------------------------------


def test_only_completed_run_can_become_baseline(store: SqlRunStore) -> None:
    created = store.create_run(pack(), AgentMode.HEALTHY)

    with pytest.raises(RunNotCompletedError):
        store.set_baseline(created.run_id)

    with pytest.raises(RunNotFoundError):
        store.set_baseline(uuid4())


def test_reassigning_baseline_replaces_the_previous_one(store: SqlRunStore) -> None:
    first = execute_pack(store)
    second = execute_pack(store)

    store.set_baseline(first.run_id)
    assert store.get_run(first.run_id).is_baseline is True

    store.set_baseline(second.run_id)

    assert store.get_run(second.run_id).is_baseline is True
    assert store.get_run(first.run_id).is_baseline is False
    assert sum(summary.is_baseline for summary in store.list_runs()) == 1


def test_comparison_states_match_the_in_memory_semantics(store: SqlRunStore) -> None:
    current = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)
    assert store.get_comparison(current.run_id).status is ComparisonAvailability.NO_BASELINE

    baseline = execute_pack(store, AgentMode.HEALTHY)
    store.set_baseline(baseline.run_id)

    assert store.get_comparison(baseline.run_id).status is ComparisonAvailability.IS_BASELINE
    available = store.get_comparison(current.run_id)
    assert available.status is ComparisonAvailability.AVAILABLE
    assert available.comparison is not None
    assert available.comparison.status is RegressionStatus.REGRESSION
    assert available.comparison.score_delta < 0


def test_comparison_is_incompatible_when_persisted_pack_snapshot_differs(
    store: SqlRunStore,
) -> None:
    full_pack = pack()
    truncated = full_pack.model_copy(update={"scenarios": full_pack.scenarios[:5]})

    baseline = store.create_run(full_pack, AgentMode.HEALTHY)
    store.mark_completed(baseline.run_id)
    store.set_baseline(baseline.run_id)

    current = store.create_run(truncated, AgentMode.HEALTHY)
    store.mark_completed(current.run_id)

    assert store.get_comparison(current.run_id).status is ComparisonAvailability.INCOMPATIBLE


def test_improvement_is_detected_from_broken_baseline_to_healthy_current(
    store: SqlRunStore,
) -> None:
    baseline = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)
    store.set_baseline(baseline.run_id)
    current = execute_pack(store, AgentMode.HEALTHY)

    response = store.get_comparison(current.run_id)

    assert response.comparison is not None
    assert response.comparison.status is RegressionStatus.IMPROVED
    assert response.comparison.resolved_failures


# --- history ------------------------------------------------------------------


def test_list_runs_is_newest_first_and_bounded(store: SqlRunStore) -> None:
    created = [store.create_run(pack(), AgentMode.HEALTHY) for _ in range(5)]

    recent = store.list_runs(limit=3)

    assert [summary.run_id for summary in recent] == [
        item.run_id for item in reversed(created[-3:])
    ]
    assert store.list_runs(limit=0) == []


def test_history_beyond_the_recent_limit_is_retained_not_deleted(store: SqlRunStore) -> None:
    created = [store.create_run(pack(), AgentMode.HEALTHY) for _ in range(25)]
    for summary in created:
        store.mark_completed(summary.run_id)

    recent = store.list_runs(limit=20)

    assert len(recent) == 20
    with store._sessions() as session:  # noqa: SLF001 - asserting the storage contract
        assert session.scalar(select(RunRow.run_id).where(RunRow.run_id == created[0].run_id))
    # The oldest run is outside the recent window but still readable by id.
    assert store.get_run(created[0].run_id).run_id == created[0].run_id


def test_list_runs_reports_persisted_baseline(store: SqlRunStore) -> None:
    first = execute_pack(store)
    second = execute_pack(store)
    store.set_baseline(first.run_id)

    by_id = {summary.run_id: summary for summary in store.list_runs()}

    assert by_id[first.run_id].is_baseline is True
    assert by_id[second.run_id].is_baseline is False


# --- restart recovery ---------------------------------------------------------


def test_orphaned_runs_are_retired_on_restart(engine: Engine) -> None:
    first = SqlRunStore(engine)
    queued = first.create_run(pack(), AgentMode.HEALTHY)
    running = first.create_run(pack(), AgentMode.HEALTHY)
    first.mark_running(running.run_id)
    finished = first.create_run(pack(), AgentMode.HEALTHY)
    first.mark_completed(finished.run_id)

    restarted = SqlRunStore(engine)
    recovered = restarted.recover_interrupted_runs()

    assert recovered == 2
    for run_id in (queued.run_id, running.run_id):
        summary = restarted.get_run(run_id)
        assert summary.lifecycle_status is LifecycleStatus.ERROR
        assert summary.error is not None
        assert "restart" in summary.error.reason.lower()
        assert summary.completed_at is not None
    # A finished run must not be touched by recovery.
    assert restarted.get_run(finished.run_id).lifecycle_status is LifecycleStatus.COMPLETED
    assert restarted.recover_interrupted_runs() == 0


# --- security -----------------------------------------------------------------


def test_external_agent_bearer_token_is_never_persisted(store: SqlRunStore, engine: Engine) -> None:
    secret = "persisted-run-secret"

    def external_factory(_configuration: ExternalAgentConfiguration) -> AgentAdapter:
        return DemoAgentAdapter(AgentMode.HEALTHY, configuration_label="external_http")

    async def execute():  # type: ignore[no-untyped-def]
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
        return await service.wait_for_completion(created.run_id)

    summary = asyncio.run(execute())

    assert summary.agent_target is AgentTarget.EXTERNAL_HTTP
    assert secret not in store.get_run(summary.run_id).model_dump_json()
    assert secret not in store.get_results(summary.run_id).model_dump_json()
    # Nothing anywhere in the raw database rows either.
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT pack_snapshot, agent_label, error FROM test_runs"
        ).fetchall()
        payloads = connection.exec_driver_sql("SELECT payload FROM scenario_results").fetchall()
    dumped = str(rows) + str(payloads)
    assert secret not in dumped
    assert "agent.example.com" not in dumped
    assert "bearer" not in dumped.casefold()


def test_database_url_is_never_exposed_in_settings_output() -> None:
    settings = Settings(
        run_store_backend="postgres",  # type: ignore[arg-type]
        database_url="postgresql://sinama:top-secret@db.example.com:5432/sinama",  # type: ignore[arg-type]
    )

    # SecretStr keeps the credential out of every incidental string rendering.
    assert "top-secret" not in repr(settings)
    assert "top-secret" not in str(settings)
    assert "top-secret" not in settings.model_dump_json()
    # It is still available to the engine factory, with the driver normalized.
    assert settings.sqlalchemy_database_url().startswith("postgresql+psycopg://")
    assert "top-secret" in settings.sqlalchemy_database_url()


def test_invalid_postgres_settings_fail_without_echoing_the_url() -> None:
    secret = "top-secret-password"

    with pytest.raises(ValidationError) as missing_url:
        Settings(_env_file=None, run_store_backend="postgres")  # type: ignore[arg-type]
    assert "SINAMA_DATABASE_URL" in str(missing_url.value)

    # A rejected URL must never be echoed back through the validation error,
    # which would otherwise put credentials into a startup traceback.
    with pytest.raises(ValidationError) as wrong_scheme:
        Settings(
            _env_file=None,
            run_store_backend="postgres",  # type: ignore[arg-type]
            database_url=f"mysql://user:{secret}@db.example.com/sinama",  # type: ignore[arg-type]
        )
    assert secret not in str(wrong_scheme.value)

    # An unrelated field failing must not leak an otherwise valid URL either.
    with pytest.raises(ValidationError) as unrelated:
        Settings(
            _env_file=None,
            run_store_backend="postgres",  # type: ignore[arg-type]
            database_url=f"postgresql://user:{secret}@db.example.com/sinama",  # type: ignore[arg-type]
            external_agent_timeout_seconds=99,
        )
    assert secret not in str(unrelated.value)


def test_memory_backend_is_the_default_and_never_silently_falls_back() -> None:
    assert Settings(_env_file=None).uses_persistent_run_store is False
    assert Settings(_env_file=None).run_store_backend is RunStoreBackend.MEMORY


def test_clear_removes_runs_results_and_baselines(store: SqlRunStore) -> None:
    summary = execute_pack(store)
    store.set_baseline(summary.run_id)

    store.clear()

    assert store.list_runs() == []
    with pytest.raises(RunNotFoundError):
        store.get_run(summary.run_id)


def test_naive_stored_timestamps_are_returned_as_utc(store: SqlRunStore, engine: Engine) -> None:
    created = store.create_run(pack(), AgentMode.HEALTHY)

    naive = datetime(2026, 8, 14, 12, 30, tzinfo=UTC).replace(tzinfo=None)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE test_runs SET created_at = ?",
            (naive.isoformat(sep=" "),),
        )

    summary = store.get_run(created.run_id)

    assert summary.created_at.tzinfo is not None
    assert summary.created_at == datetime(2026, 8, 14, 12, 30, tzinfo=UTC)
