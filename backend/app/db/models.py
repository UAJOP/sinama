"""Relational schema for persistent run history.

Design notes:

- Typed Pydantic models stay the authoritative data contract. Result payloads are
  stored as JSON documents rather than being shredded into per-check columns.
- Columns duplicated out of those payloads exist only for real product queries
  that must not deserialize transcripts: status polling, trend score/severity
  rollups and critical-regression detection.
- This module describes the *current* schema only. Alembic revisions are frozen
  historical snapshots that declare their own column types inline and import
  nothing from here, so editing a model can never retroactively change what an
  old revision builds. Parity between the two is asserted by
  `tests/test_migrations.py`; divergence is resolved by adding a new revision.
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

JsonPayload = JSON().with_variant(JSONB(), "postgresql")
Timestamp = DateTime(timezone=True)

PACK_ID_LENGTH = 128
SCENARIO_ID_LENGTH = 64
LABEL_LENGTH = 128
STATUS_LENGTH = 32
AGENT_VERSION_LENGTH = 64


class Base(DeclarativeBase):
    pass


class TestRunRow(Base):
    __tablename__ = "test_runs"

    run_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(PACK_ID_LENGTH), nullable=False)
    pack_name: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    pack_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonPayload, nullable=False)
    agent_target: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    agent_mode: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    agent_label: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(
        String(AGENT_VERSION_LENGTH), nullable=True
    )
    lifecycle_status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JsonPayload, nullable=True)

    __table_args__ = (
        Index("ix_test_runs_created_at", "created_at", "run_id"),
        Index("ix_test_runs_lifecycle_status", "lifecycle_status"),
        Index("ix_test_runs_pack_created_at", "pack_id", "created_at", "run_id"),
    )


class ScenarioResultRow(Base):
    __tablename__ = "scenario_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("test_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(SCENARIO_ID_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    # Queryable trend metadata, deliberately kept small and derived from the
    # authoritative typed payload when the result is written.
    severity: Mapped[str | None] = mapped_column(String(STATUS_LENGTH), nullable=True)
    goal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critical_failure_keys: Mapped[list[str] | None] = mapped_column(JsonPayload, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonPayload, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_scenario_results_run_position"),
        Index("ix_scenario_results_run_scenario", "run_id", "scenario_id"),
    )


class RunBaselineRow(Base):
    __tablename__ = "run_baselines"

    pack_id: Mapped[str] = mapped_column(String(PACK_ID_LENGTH), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("test_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
