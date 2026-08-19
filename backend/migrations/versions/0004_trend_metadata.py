"""Add queryable reliability-trend metadata.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-19

The canonical scenario-result payload stays intact. This revision duplicates only
small fields required by the version-trend surface so PostgreSQL can aggregate
history without deserializing transcripts/check evidence in application code.
Existing rows are backfilled from their persisted JSON payload once during the
migration.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonPayload = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _as_mapping(payload: object) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _goal_score(payload: dict[str, Any]) -> int:
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return 0
    for metric in metrics:
        if not isinstance(metric, dict) or metric.get("dimension") != "goal_completion":
            continue
        score = metric.get("score")
        if isinstance(score, bool) or not isinstance(score, int):
            return 0
        return max(0, min(100, score))
    return 0


def _critical_failure_keys(scenario_id: str, payload: dict[str, Any]) -> list[str]:
    failures = payload.get("failures")
    if not isinstance(failures, list):
        return []
    keys: list[str] = []
    for failure in failures:
        if not isinstance(failure, dict) or failure.get("severity") != "critical":
            continue
        check_type = failure.get("type")
        title = failure.get("title")
        if isinstance(check_type, str) and isinstance(title, str):
            keys.append(f"{scenario_id}:{check_type}:{title}")
    return keys


def upgrade() -> None:
    op.add_column(
        "scenario_results",
        sa.Column("severity", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "scenario_results",
        sa.Column("goal_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scenario_results",
        sa.Column("critical_failure_keys", JsonPayload, nullable=True),
    )
    op.create_index(
        "ix_test_runs_pack_created_at",
        "test_runs",
        ["pack_id", "created_at", "run_id"],
        unique=False,
    )

    results = sa.table(
        "scenario_results",
        sa.column("id", sa.Integer()),
        sa.column("scenario_id", sa.String(length=64)),
        sa.column("payload", JsonPayload),
        sa.column("severity", sa.String(length=32)),
        sa.column("goal_score", sa.Integer()),
        sa.column("critical_failure_keys", JsonPayload),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(results.c.id, results.c.scenario_id, results.c.payload)
    ).all()
    for row_id, scenario_id, raw_payload in rows:
        payload = _as_mapping(raw_payload)
        severity = payload.get("severity")
        connection.execute(
            results.update()
            .where(results.c.id == row_id)
            .values(
                severity=severity if isinstance(severity, str) else None,
                goal_score=_goal_score(payload),
                critical_failure_keys=_critical_failure_keys(str(scenario_id), payload),
            )
        )


def downgrade() -> None:
    op.drop_index("ix_test_runs_pack_created_at", table_name="test_runs")
    op.drop_column("scenario_results", "critical_failure_keys")
    op.drop_column("scenario_results", "goal_score")
    op.drop_column("scenario_results", "severity")
