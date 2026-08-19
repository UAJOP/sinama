"""Enable Row Level Security on SINAMA persistence tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

SINAMA persists run history in Supabase/PostgreSQL through a trusted backend
connection. These tables live in Supabase's exposed `public` schema, so RLS must
be enabled even though the browser never talks to them directly.

No policies are created intentionally: anon/authenticated access through the
Supabase Data API should be denied. The trusted direct PostgreSQL backend keeps
working with its privileged database role.

SQLite is used by the local migration test suite, where PostgreSQL RLS syntax is
not available, so this revision is a no-op on non-PostgreSQL databases.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
    "test_runs",
    "scenario_results",
    "run_baselines",
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():
        return

    for table in RLS_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    if not _is_postgresql():
        return

    for table in reversed(RLS_TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
