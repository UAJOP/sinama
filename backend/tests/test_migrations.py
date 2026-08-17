"""Guards on the Alembic migrations.

Two independent concerns:

1. Migrations are frozen historical snapshots and must not import live
   application models - otherwise editing an ORM model would retroactively
   change what an old revision builds.
2. Because of (1), the migrated schema can genuinely drift from the current
   models, so parity is asserted here. A model change that never reaches a
   migration fails these tests rather than a deploy.

Parity runs on SQLite and compares structure (tables, columns, nullability,
keys, constraints), not PostgreSQL-specific column types.
"""

import ast
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect

from app.db.models import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_ROOT / "migrations" / "versions"
MIGRATION_FILES = sorted(VERSIONS_DIR.glob("*.py"))


def _alembic_config(connection: object) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def empty_database(tmp_path: Path) -> Engine:
    """A genuinely empty database - no create_all, no pre-seeded metadata."""

    return create_engine(f"sqlite:///{tmp_path / 'empty.db'}", future=True)


@pytest.fixture
def migrated_engine(empty_database: Engine) -> Engine:
    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")
    return empty_database


# --- migrations must not depend on live application models --------------------


@pytest.mark.parametrize("migration", MIGRATION_FILES, ids=lambda path: path.name)
def test_migration_does_not_import_application_modules(migration: Path) -> None:
    """A revision must be self-contained.

    Importing `app.db.models` (or anything else from `app`) would let a later
    edit to a live model silently change what this historical revision creates.
    """

    tree = ast.parse(migration.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offending = [name for name in imported if name == "app" or name.startswith("app.")]
    assert offending == [], (
        f"{migration.name} imports live application modules {offending}; "
        "declare the required types inline instead."
    )


def test_migration_revisions_exist() -> None:
    # Guards the parametrized test above against silently collecting nothing.
    assert MIGRATION_FILES, "expected at least one Alembic revision"


# --- an empty database can be built and torn down -----------------------------


def test_empty_database_upgrades_from_base_to_head(empty_database: Engine) -> None:
    assert set(inspect(empty_database).get_table_names()) == set()

    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")

    tables = set(inspect(empty_database).get_table_names())
    assert {"test_runs", "scenario_results", "run_baselines"} <= tables


def test_migration_is_reversible(empty_database: Engine) -> None:
    with empty_database.begin() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "head")
        command.downgrade(config, "base")

    remaining = set(inspect(empty_database).get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_agent_version_is_added_by_0002_not_0001(empty_database: Engine) -> None:
    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "0001")
    at_0001 = {column["name"] for column in inspect(empty_database).get_columns("test_runs")}

    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "0002")
    at_0002 = {column["name"] for column in inspect(empty_database).get_columns("test_runs")}

    assert "agent_version" not in at_0001
    assert at_0002 - at_0001 == {"agent_version"}


def test_0002_keeps_rows_written_before_it_valid(empty_database: Engine) -> None:
    """A production row that predates agent versioning must survive the upgrade."""

    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "0001")
        connection.exec_driver_sql(
            "INSERT INTO test_runs (run_id, pack_id, pack_name, pack_snapshot, agent_target,"
            " agent_mode, agent_label, lifecycle_status, created_at)"
            " VALUES ('legacy-run', 'insurance-v1', 'Pack', '{}', 'built_in_demo',"
            " 'healthy', 'healthy', 'completed', '2026-08-01 00:00:00')"
        )

    with empty_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "0002")

    with empty_database.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT agent_label, agent_version FROM test_runs WHERE run_id = 'legacy-run'"
        ).one()

    # Pre-existing data is preserved and simply reports no version.
    assert row.agent_label == "healthy"
    assert row.agent_version is None


def test_0002_downgrade_removes_only_agent_version(empty_database: Engine) -> None:
    with empty_database.begin() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "head")
    at_head = {column["name"] for column in inspect(empty_database).get_columns("test_runs")}

    with empty_database.begin() as connection:
        command.downgrade(_alembic_config(connection), "0001")
    after = {column["name"] for column in inspect(empty_database).get_columns("test_runs")}

    assert at_head - after == {"agent_version"}


def test_upgrade_downgrade_upgrade_round_trips(empty_database: Engine) -> None:
    with empty_database.begin() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")

    assert {"test_runs", "scenario_results", "run_baselines"} <= set(
        inspect(empty_database).get_table_names()
    )


# --- parity between the migrated schema and the current models ----------------


def test_migration_creates_every_table_declared_by_the_models(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())

    assert set(Base.metadata.tables) <= tables


def test_migration_columns_match_the_models(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    for name, table in Base.metadata.tables.items():
        migrated = {column["name"] for column in inspector.get_columns(name)}
        assert migrated == set(table.columns.keys()), f"column drift in {name}"


def test_migration_nullability_matches_the_models(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    for name, table in Base.metadata.tables.items():
        migrated = {column["name"]: column["nullable"] for column in inspector.get_columns(name)}
        expected = {column.name: column.nullable for column in table.columns}
        assert migrated == expected, f"nullability drift in {name}"


def test_migration_primary_keys_match_the_models(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    for name, table in Base.metadata.tables.items():
        migrated = inspector.get_pk_constraint(name)["constrained_columns"]
        expected = [column.name for column in table.primary_key.columns]
        assert sorted(migrated) == sorted(expected), f"primary key drift in {name}"


def test_migration_enforces_one_baseline_per_pack(migrated_engine: Engine) -> None:
    primary_key = inspect(migrated_engine).get_pk_constraint("run_baselines")

    assert primary_key["constrained_columns"] == ["pack_id"]


def test_migration_preserves_scenario_result_ordering_constraint(migrated_engine: Engine) -> None:
    unique = inspect(migrated_engine).get_unique_constraints("scenario_results")

    assert any(
        constraint["column_names"] == ["run_id", "position"] for constraint in unique
    ), "scenario results must stay uniquely ordered within a run"


def test_migration_cascades_results_and_baselines_from_their_run(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)

    for table in ("scenario_results", "run_baselines"):
        keys = inspector.get_foreign_keys(table)
        assert keys, f"{table} must reference its run"
        assert keys[0]["referred_table"] == "test_runs"
        assert keys[0]["options"].get("ondelete") == "CASCADE"
