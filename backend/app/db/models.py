"""Relational schema for persistent run history.

Design notes:

- Typed Pydantic models stay the authoritative data contract. Result payloads are
  stored as JSON documents rather than being shredded into per-check columns,
  because nothing in the product queries *inside* a result - it reads whole runs.
- The few columns that are duplicated out of those payloads (`scenario_id`,
  `status`) exist to answer real queries without deserializing transcripts: run
  aggregates and single-scenario lookup.
- Column types are declared once here and reused by the Alembic migration so the
  two cannot drift.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on PostgreSQL; portable JSON elsewhere so the same store code can be
# exercised against SQLite in the default test suite.
JsonPayload = JSON().with_variant(JSONB(), "postgresql")

# Timezone-aware everywhere. SQLite cannot store an offset, so reads are
# normalized back to UTC in `app.db.sql_run_store`.
Timestamp = DateTime(timezone=True)

PACK_ID_LENGTH = 128
SCENARIO_ID_LENGTH = 64
LABEL_LENGTH = 128
STATUS_LENGTH = 32


class Base(DeclarativeBase):
    pass


class TestRunRow(Base):
    __tablename__ = "test_runs"

    run_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(PACK_ID_LENGTH), nullable=False)
    pack_name: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    # Snapshot of the pack as executed. Regression compatibility must be judged
    # against what the run actually ran, not against a fixture that a later
    # deployment may have changed.
    pack_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonPayload, nullable=False)
    agent_target: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    agent_mode: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    agent_label: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JsonPayload, nullable=True)

    __table_args__ = (
        # Recent-history listing: newest first, with run_id as a stable tiebreak.
        Index("ix_test_runs_created_at", "created_at", "run_id"),
        # Startup recovery scans for non-terminal runs.
        Index("ix_test_runs_lifecycle_status", "lifecycle_status"),
    )


class ScenarioResultRow(Base):
    __tablename__ = "scenario_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("test_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Execution order within the pack. Explicit so result ordering never depends
    # on primary-key generation or row-return order.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(SCENARIO_ID_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonPayload, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_scenario_results_run_position"),
        Index("ix_scenario_results_run_scenario", "run_id", "scenario_id"),
    )


class RunBaselineRow(Base):
    __tablename__ = "run_baselines"

    # pack_id as the primary key is what enforces "one baseline per pack".
    pack_id: Mapped[str] = mapped_column(String(PACK_ID_LENGTH), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("test_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
