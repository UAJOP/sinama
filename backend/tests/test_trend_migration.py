import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def config(connection: object) -> Config:
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    alembic.attributes["connection"] = connection
    return alembic


def test_0004_adds_and_backfills_trend_metadata(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'trend-migration.db'}", future=True)
    try:
        with engine.begin() as connection:
            command.upgrade(config(connection), "0003")
            connection.exec_driver_sql(
                "INSERT INTO test_runs (run_id, pack_id, pack_name, pack_snapshot, agent_target,"
                " agent_mode, agent_label, agent_version, lifecycle_status, created_at)"
                " VALUES ('11111111111111111111111111111111', 'insurance-v1', 'Pack', '{}',"
                " 'built_in_demo', 'healthy', 'healthy', 'v1', 'completed',"
                " '2026-08-19 10:00:00')"
            )
            payload = json.dumps(
                {
                    "scenario_id": "INS-001",
                    "severity": "high",
                    "metrics": [
                        {
                            "dimension": "goal_completion",
                            "score": 73,
                            "status": "warning",
                            "reason": "x",
                        }
                    ],
                    "failures": [
                        {
                            "type": "forbidden_tool_call",
                            "severity": "critical",
                            "title": "Critical leak",
                        }
                    ],
                }
            )
            connection.exec_driver_sql(
                "INSERT INTO scenario_results (run_id, position, scenario_id, status, payload)"
                " VALUES ('11111111111111111111111111111111', 0, 'INS-001', 'fail', ?)",
                (payload,),
            )

        with engine.begin() as connection:
            command.upgrade(config(connection), "0004")

        columns = {column["name"] for column in inspect(engine).get_columns("scenario_results")}
        assert {"severity", "goal_score", "critical_failure_keys"} <= columns
        indexes = {index["name"] for index in inspect(engine).get_indexes("test_runs")}
        assert "ix_test_runs_pack_created_at" in indexes

        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT severity, goal_score, critical_failure_keys FROM scenario_results"
            ).one()

        assert row.severity == "high"
        assert row.goal_score == 73
        critical_keys = json.loads(row.critical_failure_keys)
        assert critical_keys == ["INS-001:forbidden_tool_call:Critical leak"]
    finally:
        engine.dispose()


def test_0004_downgrade_removes_only_trend_metadata(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'trend-downgrade.db'}", future=True)
    try:
        with engine.begin() as connection:
            command.upgrade(config(connection), "head")
        at_head = {column["name"] for column in inspect(engine).get_columns("scenario_results")}

        with engine.begin() as connection:
            command.downgrade(config(connection), "0003")
        after = {column["name"] for column in inspect(engine).get_columns("scenario_results")}

        assert at_head - after == {"severity", "goal_score", "critical_failure_keys"}
        assert {"test_runs", "scenario_results", "run_baselines"} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
