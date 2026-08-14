"""Optional PostgreSQL integration tests.

Skipped unless SINAMA_TEST_DATABASE_URL points at a **disposable** PostgreSQL
database - these tests drop and recreate the schema, so never aim them at a
database holding real run history.

    # PowerShell
    $env:SINAMA_TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/sinama_test"
    pytest tests/test_sql_run_store_postgres.py

The default suite (`pytest`) never needs a database, a Supabase account or
network access; everything else is covered against SQLite in
`tests/test_sql_run_store.py`.
"""

import asyncio
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect

from app.config import Settings
from app.db.models import Base
from app.db.sql_run_store import SqlRunStore
from app.models import AgentMode
from app.regression import ComparisonAvailability, RegressionStatus
from app.test_runs import RunService
from app.test_runs import TestRunLifecycleStatus as LifecycleStatus

TEST_DATABASE_URL = os.environ.get("SINAMA_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set SINAMA_TEST_DATABASE_URL to a disposable PostgreSQL database to run these.",
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    settings = Settings(
        run_store_backend="postgres",  # type: ignore[arg-type]
        database_url=TEST_DATABASE_URL,  # type: ignore[arg-type]
    )
    created = create_engine(settings.sqlalchemy_database_url(), future=True)
    Base.metadata.drop_all(created)
    Base.metadata.create_all(created)
    yield created
    Base.metadata.drop_all(created)
    created.dispose()


def execute_pack(store: SqlRunStore, mode: AgentMode):  # type: ignore[no-untyped-def]
    async def run():  # type: ignore[no-untyped-def]
        service = RunService(store=store)
        created = await service.create_run("insurance-v1", mode)
        return await service.wait_for_completion(created.run_id)

    return asyncio.run(run())


def test_schema_uses_jsonb_on_postgres(engine: Engine) -> None:
    columns = {column["name"]: column for column in inspect(engine).get_columns("test_runs")}

    assert str(columns["pack_snapshot"]["type"]).upper() == "JSONB"


def test_timestamptz_round_trips_with_offset(engine: Engine) -> None:
    store = SqlRunStore(engine)
    summary = execute_pack(store, AgentMode.HEALTHY)

    reread = store.get_run(summary.run_id)

    assert reread.created_at.tzinfo is not None
    assert reread.completed_at is not None and reread.completed_at.tzinfo is not None
    assert reread.created_at == summary.created_at


def test_core_acceptance_flow_on_postgres(engine: Engine) -> None:
    store = SqlRunStore(engine)
    healthy = execute_pack(store, AgentMode.HEALTHY)
    store.set_baseline(healthy.run_id)
    broken = execute_pack(store, AgentMode.BROKEN_PREMATURE_SUBMISSION)

    restarted = SqlRunStore(engine)
    comparison = restarted.get_comparison(broken.run_id)

    assert restarted.get_run(healthy.run_id).is_baseline is True
    assert restarted.get_run(broken.run_id).lifecycle_status is LifecycleStatus.COMPLETED
    assert comparison.status is ComparisonAvailability.AVAILABLE
    assert comparison.comparison is not None
    assert comparison.comparison.status is RegressionStatus.REGRESSION


def test_baseline_foreign_key_and_single_row_per_pack(engine: Engine) -> None:
    store = SqlRunStore(engine)
    first = execute_pack(store, AgentMode.HEALTHY)
    second = execute_pack(store, AgentMode.HEALTHY)

    store.set_baseline(first.run_id)
    store.set_baseline(second.run_id)

    assert sum(summary.is_baseline for summary in store.list_runs()) == 1
