"""Persistent run history: test_runs, scenario_results, run_baselines.

Revision ID: 0001
Revises:
Create Date: 2026-08-14

This migration is a frozen historical snapshot. It deliberately imports nothing
from `app.db.models` (or any other live application module): every column type
and length is declared inline, so editing an ORM model can never retroactively
change what this revision builds. Divergence between this schema and the current
models is caught by `tests/test_migrations.py`, and is fixed by adding a *new*
revision - never by editing this one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on PostgreSQL, portable JSON elsewhere.
JSON_PAYLOAD = sa.JSON().with_variant(JSONB(), "postgresql")
# Timezone-aware everywhere; reads are normalized back to UTC in the run store.
TIMESTAMP = sa.DateTime(timezone=True)

PACK_ID_LENGTH = 128
SCENARIO_ID_LENGTH = 64
LABEL_LENGTH = 128
STATUS_LENGTH = 32


def upgrade() -> None:
    op.create_table(
        "test_runs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.String(length=PACK_ID_LENGTH), nullable=False),
        sa.Column("pack_name", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("pack_snapshot", JSON_PAYLOAD, nullable=False),
        sa.Column("agent_target", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("agent_mode", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("agent_label", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=True),
        sa.Column("completed_at", TIMESTAMP, nullable=True),
        sa.Column("error", JSON_PAYLOAD, nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_test_runs_created_at", "test_runs", ["created_at", "run_id"])
    op.create_index("ix_test_runs_lifecycle_status", "test_runs", ["lifecycle_status"])

    op.create_table(
        "scenario_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.String(length=SCENARIO_ID_LENGTH), nullable=False),
        sa.Column("status", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("payload", JSON_PAYLOAD, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "position", name="uq_scenario_results_run_position"),
    )
    op.create_index(
        "ix_scenario_results_run_scenario",
        "scenario_results",
        ["run_id", "scenario_id"],
    )

    op.create_table(
        "run_baselines",
        sa.Column("pack_id", sa.String(length=PACK_ID_LENGTH), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.run_id"], ondelete="CASCADE"),
        # pack_id as the primary key is what enforces one baseline per pack.
        sa.PrimaryKeyConstraint("pack_id"),
    )


def downgrade() -> None:
    op.drop_table("run_baselines")
    op.drop_index("ix_scenario_results_run_scenario", table_name="scenario_results")
    op.drop_table("scenario_results")
    op.drop_index("ix_test_runs_lifecycle_status", table_name="test_runs")
    op.drop_index("ix_test_runs_created_at", table_name="test_runs")
    op.drop_table("test_runs")
