"""Add optional agent_version metadata to test_runs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-17

Nullable and with no default, so every row written before this revision stays
valid and simply reports no version. Like every revision, this file is a frozen
historical snapshot and imports nothing from `app.*`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_VERSION_LENGTH = 64


def upgrade() -> None:
    op.add_column(
        "test_runs",
        sa.Column("agent_version", sa.String(length=AGENT_VERSION_LENGTH), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_runs", "agent_version")
