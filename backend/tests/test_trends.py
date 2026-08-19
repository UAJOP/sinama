import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, select

from app.db.models import Base, ScenarioResultRow
from app.db.sql_run_store import SqlRunStore
from app.models import AgentMode
from app.regression import RegressionStatus
from app.scenario_runner import RunStatus
from app.scenarios import Severity
from app.test_runs import RunService
from app.trends import TrendRunInput, build_run_trends


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    created = create_engine(f"sqlite:///{tmp_path / 'trends.db'}", future=True)
    Base.metadata.create_all(created)
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlRunStore:
    return SqlRunStore(engine)


def trend_input(
    *,
    score: int | None,
    version: str | None,
    critical_keys: set[str] | None = None,
    scenario_ids: tuple[str, ...] = ("INS-001",),
    lifecycle: str = "completed",
    created_at: str = "2026-08-19T10:00:00+00:00",
) -> TrendRunInput:
    return TrendRunInput(
        run_id=uuid4(),
        pack_id="insurance-v1",
        agent_label="healthy",
        agent_version=version,
        lifecycle_status="completed" if lifecycle == "completed" else "error",
        created_at=created_at,
        is_baseline=False,
        scenario_ids=scenario_ids,
        statuses=(RunStatus.PASS,) if score is not None else (),
        goal_scores=(score,) if score is not None else (),
        severities=(),
        critical_failure_keys=frozenset(critical_keys or set()),
    )


def test_trend_uses_existing_regression_thresholds() -> None:
    baseline = trend_input(score=80, version="v1")
    improved = trend_input(
        score=85,
        version="v2",
        created_at="2026-08-19T11:00:00+00:00",
    )

    response = build_run_trends("insurance-v1", [improved, baseline])

    assert [point.agent_version for point in response.points] == ["v1", "v2"]
    assert response.points[0].direction is None
    assert response.points[1].reference_run_id == baseline.run_id
    assert response.points[1].score_delta == 5
    assert response.points[1].direction is RegressionStatus.IMPROVED


def test_new_critical_failure_forces_trend_regression_even_when_score_improves() -> None:
    baseline = trend_input(score=80, version="v1")
    current = trend_input(
        score=95,
        version="v2",
        critical_keys={"INS-001:forbidden_tool_call:Critical leak"},
        created_at="2026-08-19T11:00:00+00:00",
    )

    response = build_run_trends("insurance-v1", [baseline, current])

    assert response.points[1].score_delta == 15
    assert response.points[1].direction is RegressionStatus.REGRESSION


def test_persistent_critical_failure_does_not_force_override() -> None:
    shared = {"INS-001:forbidden_tool_call:Same critical"}
    baseline = trend_input(score=80, version="v1", critical_keys=shared)
    current = trend_input(
        score=82,
        version="v2",
        critical_keys=shared,
        created_at="2026-08-19T11:00:00+00:00",
    )

    response = build_run_trends("insurance-v1", [baseline, current])

    assert response.points[1].direction is RegressionStatus.STABLE


def test_error_run_has_no_score_and_does_not_replace_completed_reference() -> None:
    first = trend_input(score=80, version="v1")
    errored = trend_input(
        score=None,
        version="v2",
        lifecycle="error",
        created_at="2026-08-19T11:00:00+00:00",
    )
    current = trend_input(
        score=70,
        version="v3",
        created_at="2026-08-19T12:00:00+00:00",
    )

    response = build_run_trends("insurance-v1", [first, errored, current])

    assert response.points[1].score is None
    assert response.points[1].direction is None
    assert response.points[2].reference_run_id == first.run_id
    assert response.points[2].direction is RegressionStatus.REGRESSION


def test_incompatible_scenario_sets_are_not_compared() -> None:
    previous = trend_input(score=80, version="v1", scenario_ids=("INS-001",))
    changed_pack = trend_input(
        score=90,
        version="v2",
        scenario_ids=("INS-001", "INS-002"),
        created_at="2026-08-19T11:00:00+00:00",
    )

    response = build_run_trends("insurance-v1", [previous, changed_pack])

    assert response.points[1].reference_run_id is None
    assert response.points[1].score_delta is None
    assert response.points[1].direction is None


def test_unversioned_run_stays_explicitly_unversioned() -> None:
    response = build_run_trends("insurance-v1", [trend_input(score=100, version=None)])

    assert response.points[0].agent_version is None


async def _execute_pack(
    store: SqlRunStore,
    mode: AgentMode,
    version: str | None,
):
    service = RunService(store=store)
    created = await service.create_run("insurance-v1", mode, agent_version=version)
    return await service.wait_for_completion(created.run_id)


def execute_pack(
    store: SqlRunStore,
    mode: AgentMode,
    version: str | None,
):
    return asyncio.run(_execute_pack(store, mode, version))


def test_sql_store_persists_small_trend_metadata(store: SqlRunStore) -> None:
    run = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, "v-broken")

    with store._sessions() as session:  # noqa: SLF001 - asserting storage contract
        rows = list(
            session.scalars(
                select(ScenarioResultRow).where(ScenarioResultRow.run_id == run.run_id)
            )
        )

    assert len(rows) == 10
    assert all(row.goal_score is not None for row in rows)
    assert any(row.severity == Severity.HIGH.value for row in rows)
    assert all(isinstance(row.critical_failure_keys, list) for row in rows)


def test_sql_trends_do_not_deserialize_full_result_payloads(
    store: SqlRunStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = execute_pack(store, AgentMode.HEALTHY, "v1")
    broken = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION, "v2")
    store.set_baseline(healthy.run_id)

    def fail_if_payload_is_loaded(_payload):  # type: ignore[no-untyped-def]
        raise AssertionError("trend listing must not deserialize scenario payloads")

    monkeypatch.setattr(store, "_load_result", fail_if_payload_is_loaded)

    response = store.list_trends("insurance-v1")

    assert [point.agent_version for point in response.points] == ["v1", "v2"]
    assert response.points[0].is_baseline is True
    assert response.points[0].score == 100
    assert response.points[1].reference_run_id == healthy.run_id
    assert response.points[1].score is not None and response.points[1].score < 100
    assert response.points[1].direction is RegressionStatus.REGRESSION
    assert response.points[1].outcomes.failed == 5
    assert broken.run_id == response.points[1].run_id


def test_sql_trends_limit_is_applied_with_chronological_output(store: SqlRunStore) -> None:
    execute_pack(store, AgentMode.HEALTHY, "v1")
    second = execute_pack(store, AgentMode.HEALTHY, "v2")
    third = execute_pack(store, AgentMode.HEALTHY, "v3")

    response = store.list_trends("insurance-v1", limit=2)

    assert [point.run_id for point in response.points] == [second.run_id, third.run_id]


def test_unknown_pack_has_empty_sql_store_trend_history(store: SqlRunStore) -> None:
    response = store.list_trends("unknown-pack")

    assert response.pack_id == "unknown-pack"
    assert response.points == []
