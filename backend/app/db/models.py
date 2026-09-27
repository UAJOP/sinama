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
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
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
WORKSPACE_ID_LENGTH = 128
PROJECT_ID_LENGTH = 128
PLAN_CODE_LENGTH = 32
ENTITLEMENT_KEY_LENGTH = 128


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
    workspace_id: Mapped[str | None] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(PROJECT_ID_LENGTH),
        ForeignKey("projects.id"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_test_runs_created_at", "created_at", "run_id"),
        Index("ix_test_runs_lifecycle_status", "lifecycle_status"),
        Index("ix_test_runs_pack_created_at", "pack_id", "created_at", "run_id"),
        Index("ix_test_runs_workspace_created_at", "workspace_id", "created_at", "run_id"),
        Index("ix_test_runs_project_created_at", "project_id", "created_at", "run_id"),
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
    workspace_id: Mapped[str | None] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_scenario_results_run_position"),
        Index("ix_scenario_results_run_scenario", "run_id", "scenario_id"),
        Index("ix_scenario_results_workspace", "workspace_id", "run_id"),
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
    workspace_id: Mapped[str | None] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(PROJECT_ID_LENGTH),
        ForeignKey("projects.id"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_run_baselines_workspace", "workspace_id"),
        Index("ix_run_baselines_project", "project_id"),
    )


class ProfileRow(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(LABEL_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(WORKSPACE_ID_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    kind: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    visibility: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('personal', 'system', 'team')",
            name="ck_workspaces_kind",
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_workspaces_visibility",
        ),
        CheckConstraint(
            "visibility <> 'public' OR kind = 'system'",
            name="ck_workspaces_public_requires_system",
        ),
    )


class WorkspaceMemberRow(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    role: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'developer', 'reviewer', 'viewer')",
            name="ck_workspace_members_role",
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'removed')",
            name="ck_workspace_members_status",
        ),
        Index("ix_workspace_members_user_status", "user_id", "status"),
    )


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(PROJECT_ID_LENGTH), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_projects_id_workspace"),
        Index("ix_projects_workspace_archived", "workspace_id", "archived_at"),
    )


class PlanRow(Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(PLAN_CODE_LENGTH), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(LABEL_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class PlanEntitlementRow(Base):
    __tablename__ = "plan_entitlements"

    plan_code: Mapped[str] = mapped_column(
        String(PLAN_CODE_LENGTH),
        ForeignKey("plans.code"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(String(ENTITLEMENT_KEY_LENGTH), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonPayload, nullable=False)


class SubscriptionRow(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(WORKSPACE_ID_LENGTH), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(WORKSPACE_ID_LENGTH),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    plan_code: Mapped[str] = mapped_column(
        String(PLAN_CODE_LENGTH),
        ForeignKey("plans.code"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    source: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False)
    started_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'trialing', 'past_due', 'canceled', 'expired')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "source IN ('system', 'manual', 'provider')",
            name="ck_subscriptions_source",
        ),
        Index("ix_subscriptions_workspace", "workspace_id"),
        Index(
            "uq_subscriptions_one_current_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'trialing', 'past_due')"),
            sqlite_where=text("status IN ('active', 'trialing', 'past_due')"),
        ),
    )
