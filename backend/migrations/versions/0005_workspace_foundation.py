"""Add workspace tenancy, entitlement metadata, RLS and auth bootstrap.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

This is an expand migration. Existing runtime writes remain valid because the
ownership columns added to run evidence are nullable. Contract enforcement and
the non-owner runtime role transition belong to later checkpoints.

Downgrade refuses to run once customer tenancy state exists. It removes only
0005-owned objects and keeps the tightened access on pre-existing tables: RLS
stays enabled on the evidence tables and alembic_version, and the broad
anon/authenticated grants 0005 revoked are not restored.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_PAYLOAD = sa.JSON().with_variant(JSONB(), "postgresql")
TIMESTAMP = sa.DateTime(timezone=True)

PLAN_CODE_LENGTH = 32
ENTITLEMENT_KEY_LENGTH = 128
LABEL_LENGTH = 128
STATUS_LENGTH = 32

PUBLIC_WORKSPACE_KEY = "sinama-public-demo"
PRIVATE_WORKSPACE_KEY = "sinama-legacy-private"
PUBLIC_WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000001")
PRIVATE_WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000002")
PUBLIC_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000001")
PRIVATE_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000002")
PUBLIC_SUBSCRIPTION_ID = UUID("30000000-0000-4000-8000-000000000001")
PRIVATE_SUBSCRIPTION_ID = UUID("30000000-0000-4000-8000-000000000002")

# Frozen migration-time allow-list. Only this collection supports the built-in
# demo in the revision 0005 application model; inconsistent pairs fail closed.
BUILT_IN_DEMO_COLLECTION_IDS = ("insurance-v1",)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_foundation_tables() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=LABEL_LENGTH), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("system_key", sa.String(length=LABEL_LENGTH), nullable=True),
        sa.Column("personal_owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("kind", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("visibility", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "kind IN ('personal', 'system', 'team')",
            name="ck_workspaces_kind",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_workspaces_visibility",
        ),
        sa.CheckConstraint(
            "visibility <> 'public' OR kind = 'system'",
            name="ck_workspaces_public_requires_system",
        ),
        sa.CheckConstraint(
            "(kind = 'system' AND system_key IS NOT NULL AND personal_owner_id IS NULL) "
            "OR (kind = 'personal' AND system_key IS NULL AND personal_owner_id IS NOT NULL) "
            "OR (kind = 'team' AND system_key IS NULL AND personal_owner_id IS NULL)",
            name="ck_workspaces_identity_anchor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("system_key", name="uq_workspaces_system_key"),
        sa.UniqueConstraint("personal_owner_id", name="uq_workspaces_personal_owner_id"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("status", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'developer', 'reviewer', 'viewer')",
            name="ck_workspace_members_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'removed')",
            name="ck_workspace_members_status",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        "ix_workspace_members_user_status",
        "workspace_members",
        ["user_id", "status"],
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("archived_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_projects_id_workspace"),
    )
    op.create_index(
        "ix_projects_workspace_archived",
        "projects",
        ["workspace_id", "archived_at"],
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=PLAN_CODE_LENGTH), nullable=False),
        sa.Column("display_name", sa.String(length=LABEL_LENGTH), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "plan_entitlements",
        sa.Column("plan_code", sa.String(length=PLAN_CODE_LENGTH), nullable=False),
        sa.Column("key", sa.String(length=ENTITLEMENT_KEY_LENGTH), nullable=False),
        sa.Column("value", JSON_PAYLOAD, nullable=False),
        sa.ForeignKeyConstraint(["plan_code"], ["plans.code"]),
        sa.PrimaryKeyConstraint("plan_code", "key"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_code", sa.String(length=PLAN_CODE_LENGTH), nullable=False),
        sa.Column("status", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("source", sa.String(length=STATUS_LENGTH), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("current_period_start", TIMESTAMP, nullable=True),
        sa.Column("current_period_end", TIMESTAMP, nullable=True),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'trialing', 'past_due', 'canceled', 'expired')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint(
            "source IN ('system', 'manual', 'provider')",
            name="ck_subscriptions_source",
        ),
        sa.ForeignKeyConstraint(["plan_code"], ["plans.code"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscriptions_workspace", "subscriptions", ["workspace_id"])
    op.create_index(
        "uq_subscriptions_one_current_per_workspace",
        "subscriptions",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'trialing', 'past_due')"),
        sqlite_where=sa.text("status IN ('active', 'trialing', 'past_due')"),
    )


def _seed_foundation_rows() -> None:
    connection = op.get_bind()
    now = datetime.now(UTC)
    plans = sa.table(
        "plans",
        sa.column("code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("created_at", TIMESTAMP),
        sa.column("updated_at", TIMESTAMP),
    )
    connection.execute(
        plans.insert(),
        [
            {"code": "free", "display_name": "Free", "created_at": now, "updated_at": now},
            {"code": "plus", "display_name": "Plus", "created_at": now, "updated_at": now},
            {"code": "pro", "display_name": "Pro", "created_at": now, "updated_at": now},
        ],
    )

    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.Uuid()),
        sa.column("system_key", sa.String()),
        sa.column("personal_owner_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("visibility", sa.String()),
        sa.column("created_at", TIMESTAMP),
        sa.column("updated_at", TIMESTAMP),
    )
    connection.execute(
        workspaces.insert(),
        [
            {
                "id": PUBLIC_WORKSPACE_ID,
                "system_key": PUBLIC_WORKSPACE_KEY,
                "personal_owner_id": None,
                "name": "SINAMA Public Demo",
                "kind": "system",
                "visibility": "public",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PRIVATE_WORKSPACE_ID,
                "system_key": PRIVATE_WORKSPACE_KEY,
                "personal_owner_id": None,
                "name": "SINAMA Legacy Private",
                "kind": "system",
                "visibility": "private",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    projects = sa.table(
        "projects",
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", TIMESTAMP),
        sa.column("updated_at", TIMESTAMP),
        sa.column("archived_at", TIMESTAMP),
    )
    connection.execute(
        projects.insert(),
        [
            {
                "id": PUBLIC_PROJECT_ID,
                "workspace_id": PUBLIC_WORKSPACE_ID,
                "name": "Historical public demo runs",
                "description": "Internal system project for migrated built-in demo evidence.",
                "created_at": now,
                "updated_at": now,
                "archived_at": None,
            },
            {
                "id": PRIVATE_PROJECT_ID,
                "workspace_id": PRIVATE_WORKSPACE_ID,
                "name": "Historical private external runs",
                "description": "Internal system project for migrated external-agent evidence.",
                "created_at": now,
                "updated_at": now,
                "archived_at": None,
            },
        ],
    )

    subscriptions = sa.table(
        "subscriptions",
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("plan_code", sa.String()),
        sa.column("status", sa.String()),
        sa.column("source", sa.String()),
        sa.column("started_at", TIMESTAMP),
        sa.column("current_period_start", TIMESTAMP),
        sa.column("current_period_end", TIMESTAMP),
        sa.column("ended_at", TIMESTAMP),
        sa.column("created_at", TIMESTAMP),
        sa.column("updated_at", TIMESTAMP),
    )
    connection.execute(
        subscriptions.insert(),
        [
            {
                "id": PUBLIC_SUBSCRIPTION_ID,
                "workspace_id": PUBLIC_WORKSPACE_ID,
                "plan_code": "free",
                "status": "active",
                "source": "system",
                "started_at": now,
                "current_period_start": None,
                "current_period_end": None,
                "ended_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PRIVATE_SUBSCRIPTION_ID,
                "workspace_id": PRIVATE_WORKSPACE_ID,
                "plan_code": "free",
                "status": "active",
                "source": "system",
                "started_at": now,
                "current_period_start": None,
                "current_period_end": None,
                "ended_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def _add_expand_columns() -> None:
    op.add_column(
        "test_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "test_runs",
        sa.Column("project_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "scenario_results",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "run_baselines",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "run_baselines",
        sa.Column("project_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_test_runs_workspace_created_at",
        "test_runs",
        ["workspace_id", "created_at", "run_id"],
    )
    op.create_index(
        "ix_test_runs_project_created_at",
        "test_runs",
        ["project_id", "created_at", "run_id"],
    )
    op.create_index(
        "ix_scenario_results_workspace",
        "scenario_results",
        ["workspace_id", "run_id"],
    )
    op.create_index("ix_run_baselines_workspace", "run_baselines", ["workspace_id"])
    op.create_index("ix_run_baselines_project", "run_baselines", ["project_id"])


def _add_postgresql_constraints() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE public.test_runs ADD CONSTRAINT uq_test_runs_run_workspace "
        "UNIQUE (run_id, workspace_id)"
    )
    connection.exec_driver_sql(
        "ALTER TABLE public.test_runs ADD CONSTRAINT uq_test_runs_run_workspace_project "
        "UNIQUE (run_id, workspace_id, project_id)"
    )
    statements = (
        "ALTER TABLE public.profiles ADD CONSTRAINT fk_profiles_auth_user "
        "FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE public.workspace_members ADD CONSTRAINT fk_workspace_members_auth_user "
        "FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE public.test_runs ADD CONSTRAINT fk_test_runs_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.test_runs ADD CONSTRAINT ck_test_runs_workspace_project_pair "
        "CHECK ((workspace_id IS NULL) = (project_id IS NULL)) NOT VALID",
        "ALTER TABLE public.test_runs ADD CONSTRAINT fk_test_runs_project_workspace "
        "FOREIGN KEY (project_id, workspace_id) "
        "REFERENCES public.projects(id, workspace_id) MATCH SIMPLE NOT VALID",
        "ALTER TABLE public.scenario_results ADD CONSTRAINT fk_scenario_results_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.scenario_results ADD CONSTRAINT fk_scenario_results_run_workspace "
        "FOREIGN KEY (run_id, workspace_id) "
        "REFERENCES public.test_runs(run_id, workspace_id) MATCH SIMPLE NOT VALID",
        "ALTER TABLE public.run_baselines ADD CONSTRAINT fk_run_baselines_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.run_baselines ADD CONSTRAINT ck_run_baselines_workspace_project_pair "
        "CHECK ((workspace_id IS NULL) = (project_id IS NULL)) NOT VALID",
        "ALTER TABLE public.run_baselines "
        "ADD CONSTRAINT fk_run_baselines_run_workspace_project "
        "FOREIGN KEY (run_id, workspace_id, project_id) "
        "REFERENCES public.test_runs(run_id, workspace_id, project_id) MATCH SIMPLE NOT VALID",
    )
    for statement in statements:
        connection.exec_driver_sql(statement)
    for constraint, table in (
        ("fk_profiles_auth_user", "profiles"),
        ("fk_workspace_members_auth_user", "workspace_members"),
        ("fk_test_runs_workspace", "test_runs"),
        ("ck_test_runs_workspace_project_pair", "test_runs"),
        ("fk_test_runs_project_workspace", "test_runs"),
        ("fk_scenario_results_workspace", "scenario_results"),
        ("fk_scenario_results_run_workspace", "scenario_results"),
        ("fk_run_baselines_workspace", "run_baselines"),
        ("ck_run_baselines_workspace_project_pair", "run_baselines"),
        ("fk_run_baselines_run_workspace_project", "run_baselines"),
    ):
        connection.exec_driver_sql(
            f'ALTER TABLE public."{table}" VALIDATE CONSTRAINT "{constraint}"'
        )


def _create_postgresql_helpers() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("CREATE SCHEMA app_private")
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.is_member(target_workspace_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.workspace_members AS member
                WHERE member.workspace_id = target_workspace_id
                  AND member.user_id = auth.uid()
                  AND member.status = 'active'
            )
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.has_role(target_workspace_id uuid, allowed_roles text[])
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.workspace_members AS member
                WHERE member.workspace_id = target_workspace_id
                  AND member.user_id = auth.uid()
                  AND member.status = 'active'
                  AND member.role = ANY(allowed_roles)
            )
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.is_public_workspace(target_workspace_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.workspaces AS workspace
                WHERE workspace.id = target_workspace_id
                  AND workspace.kind = 'system'
                  AND workspace.visibility = 'public'
            )
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.bootstrap_user(target_user_id uuid, raw_metadata jsonb)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            personal_workspace_id uuid;
            resolved_kind text;
            resolved_visibility text;
            resolved_display_name text := NULLIF(
                pg_catalog.left(
                    COALESCE(raw_metadata ->> 'display_name', raw_metadata ->> 'full_name'),
                    128
                ),
                ''
            );
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(target_user_id::text, 0)
            );

            INSERT INTO public.profiles (id, display_name, created_at, updated_at)
            VALUES (target_user_id, resolved_display_name, pg_catalog.now(), pg_catalog.now())
            ON CONFLICT (id) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                updated_at = pg_catalog.now()
            WHERE public.profiles.display_name IS NULL
              AND EXCLUDED.display_name IS NOT NULL;

            INSERT INTO public.workspaces (
                id, system_key, personal_owner_id, name, kind, visibility,
                created_at, updated_at
            )
            VALUES (
                pg_catalog.gen_random_uuid(),
                NULL,
                target_user_id,
                'Personal workspace',
                'personal',
                'private',
                pg_catalog.now(),
                pg_catalog.now()
            )
            ON CONFLICT (personal_owner_id) DO NOTHING;

            SELECT workspace.id, workspace.kind, workspace.visibility
            INTO personal_workspace_id, resolved_kind, resolved_visibility
            FROM public.workspaces AS workspace
            WHERE workspace.personal_owner_id = target_user_id;

            IF personal_workspace_id IS NULL
               OR resolved_kind IS DISTINCT FROM 'personal'
               OR resolved_visibility IS DISTINCT FROM 'private' THEN
                RAISE EXCEPTION 'Personal workspace identity conflict'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            INSERT INTO public.workspace_members (
                workspace_id, user_id, role, status, created_at
            )
            VALUES (
                personal_workspace_id, target_user_id, 'owner', 'active', pg_catalog.now()
            )
            ON CONFLICT (workspace_id, user_id) DO NOTHING;

            INSERT INTO public.subscriptions (
                id, workspace_id, plan_code, status, source, started_at,
                current_period_start, current_period_end, ended_at, created_at, updated_at
            )
            SELECT
                pg_catalog.gen_random_uuid(),
                personal_workspace_id,
                'free',
                'active',
                'system',
                pg_catalog.now(),
                NULL,
                NULL,
                NULL,
                pg_catalog.now(),
                pg_catalog.now()
            -- Bootstrap only: a workspace whose subscription later ended keeps
            -- that history; repair never mints a replacement subscription.
            WHERE NOT EXISTS (
                SELECT 1
                FROM public.subscriptions AS subscription
                WHERE subscription.workspace_id = personal_workspace_id
            )
            ON CONFLICT DO NOTHING;
        END
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.handle_new_auth_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        BEGIN
            PERFORM app_private.bootstrap_user(
                NEW.id,
                COALESCE(NEW.raw_user_meta_data, '{}'::jsonb)
            );
            RETURN NEW;
        EXCEPTION WHEN OTHERS THEN
            -- SQLSTATE only: never echo user metadata or error detail.
            RAISE WARNING USING MESSAGE =
                'SINAMA account bootstrap deferred (SQLSTATE=' || SQLSTATE || ')';
            RETURN NEW;
        END
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION public.repair_my_account()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            caller_id uuid := auth.uid();
            caller_metadata jsonb;
        BEGIN
            IF caller_id IS NULL THEN
                RAISE EXCEPTION 'Authentication required';
            END IF;
            SELECT users.raw_user_meta_data
            INTO caller_metadata
            FROM auth.users AS users
            WHERE users.id = caller_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Authentication required';
            END IF;
            PERFORM app_private.bootstrap_user(caller_id, COALESCE(caller_metadata, '{}'::jsonb));
        END
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER on_auth_user_created_sinama_bootstrap
        AFTER INSERT ON auth.users
        FOR EACH ROW EXECUTE FUNCTION app_private.handle_new_auth_user()
        """
    )

    connection.exec_driver_sql("REVOKE ALL ON SCHEMA app_private FROM PUBLIC")
    connection.exec_driver_sql("GRANT USAGE ON SCHEMA app_private TO anon, authenticated")
    for function in (
        "app_private.is_member(uuid)",
        "app_private.has_role(uuid,text[])",
        "app_private.is_public_workspace(uuid)",
        "app_private.bootstrap_user(uuid,jsonb)",
        "app_private.handle_new_auth_user()",
        "public.repair_my_account()",
    ):
        connection.exec_driver_sql(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, anon, authenticated, service_role"
        )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.is_member(uuid) TO authenticated"
    )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.has_role(uuid,text[]) TO authenticated"
    )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.is_public_workspace(uuid) TO anon, authenticated"
    )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION public.repair_my_account() TO authenticated"
    )


def _create_postgresql_rls() -> None:
    connection = op.get_bind()
    tenant_tables = (
        "profiles",
        "workspaces",
        "workspace_members",
        "projects",
        "subscriptions",
        "test_runs",
        "scenario_results",
        "run_baselines",
        "plans",
        "plan_entitlements",
    )
    for table in tenant_tables:
        connection.exec_driver_sql(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    connection.exec_driver_sql(
        "ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY"
    )

    policies = (
        "CREATE POLICY profiles_select_self ON public.profiles FOR SELECT TO authenticated "
        "USING (id = auth.uid())",
        "CREATE POLICY workspaces_select_public ON public.workspaces FOR SELECT TO anon "
        "USING (app_private.is_public_workspace(id))",
        "CREATE POLICY workspaces_select_member ON public.workspaces FOR SELECT TO authenticated "
        "USING (app_private.is_public_workspace(id) OR app_private.is_member(id))",
        "CREATE POLICY workspace_members_select_member ON public.workspace_members "
        "FOR SELECT TO authenticated USING (app_private.is_member(workspace_id))",
        "CREATE POLICY projects_select_public ON public.projects FOR SELECT TO anon "
        "USING (app_private.is_public_workspace(workspace_id))",
        "CREATE POLICY projects_select_member ON public.projects "
        "FOR SELECT TO authenticated USING (app_private.is_public_workspace(workspace_id) "
        "OR app_private.is_member(workspace_id))",
        "CREATE POLICY subscriptions_select_member ON public.subscriptions "
        "FOR SELECT TO authenticated "
        "USING (app_private.is_member(workspace_id))",
        "CREATE POLICY test_runs_select_public ON public.test_runs FOR SELECT TO anon "
        "USING (app_private.is_public_workspace(workspace_id))",
        "CREATE POLICY test_runs_select_member ON public.test_runs "
        "FOR SELECT TO authenticated USING (app_private.is_public_workspace(workspace_id) "
        "OR app_private.is_member(workspace_id))",
        "CREATE POLICY scenario_results_select_public ON public.scenario_results "
        "FOR SELECT TO anon "
        "USING (app_private.is_public_workspace(workspace_id))",
        "CREATE POLICY scenario_results_select_member ON public.scenario_results "
        "FOR SELECT TO authenticated USING (app_private.is_public_workspace(workspace_id) "
        "OR app_private.is_member(workspace_id))",
        "CREATE POLICY run_baselines_select_public ON public.run_baselines FOR SELECT TO anon "
        "USING (app_private.is_public_workspace(workspace_id))",
        "CREATE POLICY run_baselines_select_member ON public.run_baselines "
        "FOR SELECT TO authenticated USING (app_private.is_public_workspace(workspace_id) "
        "OR app_private.is_member(workspace_id))",
        "CREATE POLICY plans_select ON public.plans FOR SELECT TO anon, authenticated USING (true)",
        "CREATE POLICY plan_entitlements_select ON public.plan_entitlements "
        "FOR SELECT TO anon, authenticated USING (true)",
    )
    for policy in policies:
        connection.exec_driver_sql(policy)

    customer_tables = (
        "profiles",
        "workspaces",
        "workspace_members",
        "projects",
        "subscriptions",
        "test_runs",
        "scenario_results",
        "run_baselines",
        "plans",
        "plan_entitlements",
    )
    for table in customer_tables:
        connection.exec_driver_sql(
            f'REVOKE ALL ON TABLE public."{table}" FROM anon, authenticated'
        )
    connection.exec_driver_sql(
        "GRANT SELECT ON public.workspaces, public.projects, public.test_runs, "
        "public.scenario_results, public.run_baselines, public.plans, "
        "public.plan_entitlements TO anon"
    )
    connection.exec_driver_sql(
        "GRANT SELECT ON public.profiles, public.workspaces, public.workspace_members, "
        "public.projects, public.subscriptions, public.test_runs, public.scenario_results, "
        "public.run_baselines, public.plans, public.plan_entitlements TO authenticated"
    )
    connection.exec_driver_sql(
        "REVOKE ALL ON TABLE public.alembic_version FROM anon, authenticated"
    )
    connection.exec_driver_sql(
        "REVOKE ALL ON SEQUENCE public.scenario_results_id_seq FROM anon, authenticated"
    )


def _evidence_signatures() -> tuple[int, int, int, str, str, str]:
    connection = op.get_bind()
    run_count = connection.exec_driver_sql("SELECT count(*) FROM public.test_runs").scalar_one()
    result_count = connection.exec_driver_sql(
        "SELECT count(*) FROM public.scenario_results"
    ).scalar_one()
    baseline_count = connection.exec_driver_sql(
        "SELECT count(*) FROM public.run_baselines"
    ).scalar_one()
    run_evidence = connection.exec_driver_sql(
        """
        SELECT md5(COALESCE(string_agg(
            run_id::text || '|' || pack_snapshot::text || '|' || created_at::text,
            E'\n' ORDER BY run_id
        ), ''))
        FROM public.test_runs
        """
    ).scalar_one()
    result_evidence = connection.exec_driver_sql(
        """
        SELECT md5(COALESCE(string_agg(
            id::text || '|' || run_id::text || '|' || payload::text,
            E'\n' ORDER BY id
        ), ''))
        FROM public.scenario_results
        """
    ).scalar_one()
    baseline_evidence = connection.exec_driver_sql(
        """
        SELECT md5(COALESCE(string_agg(
            pack_id || '|' || run_id::text || '|' || updated_at::text,
            E'\n' ORDER BY pack_id
        ), ''))
        FROM public.run_baselines
        """
    ).scalar_one()
    return (
        run_count,
        result_count,
        baseline_count,
        run_evidence,
        result_evidence,
        baseline_evidence,
    )


def _backfill_and_assert() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE public.test_runs, public.scenario_results, public.run_baselines "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    before = _evidence_signatures()
    built_in_collection_sql = ", ".join(
        f"'{collection_id}'" for collection_id in BUILT_IN_DEMO_COLLECTION_IDS
    )
    unknown = connection.exec_driver_sql(
        f"""
        SELECT agent_target, pack_id, count(*)
        FROM public.test_runs
        WHERE agent_target NOT IN ('built_in_demo', 'external_http')
           OR (agent_target = 'built_in_demo' AND pack_id NOT IN ({built_in_collection_sql}))
        GROUP BY agent_target, pack_id
        ORDER BY agent_target, pack_id
        """
    ).all()
    if unknown:
        raise RuntimeError(f"0005 cannot classify legacy agent targets: {unknown!r}")

    connection.exec_driver_sql(
        """
        UPDATE public.test_runs
        SET workspace_id = CASE agent_target
                WHEN 'built_in_demo' THEN '10000000-0000-4000-8000-000000000001'::uuid
                WHEN 'external_http' THEN '10000000-0000-4000-8000-000000000002'::uuid
            END,
            project_id = CASE agent_target
                WHEN 'built_in_demo' THEN '20000000-0000-4000-8000-000000000001'::uuid
                WHEN 'external_http' THEN '20000000-0000-4000-8000-000000000002'::uuid
            END
        WHERE agent_target IN ('built_in_demo', 'external_http')
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE public.scenario_results AS result
        SET workspace_id = run.workspace_id
        FROM public.test_runs AS run
        WHERE run.run_id = result.run_id
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE public.run_baselines AS baseline
        SET workspace_id = run.workspace_id,
            project_id = run.project_id
        FROM public.test_runs AS run
        WHERE run.run_id = baseline.run_id
        """
    )

    after = _evidence_signatures()
    if before != after:
        raise RuntimeError("0005 changed legacy evidence counts or JSON/timestamp signatures")
    if connection.exec_driver_sql(
        "SELECT count(*) FROM public.test_runs "
        "WHERE workspace_id IS NULL OR project_id IS NULL"
    ).scalar_one():
        raise RuntimeError("0005 left historical runs unclassified")
    if connection.exec_driver_sql(
        """
        SELECT count(*)
        FROM public.scenario_results AS result
        LEFT JOIN public.test_runs AS run ON run.run_id = result.run_id
        WHERE run.run_id IS NULL OR result.workspace_id IS DISTINCT FROM run.workspace_id
        """
    ).scalar_one():
        raise RuntimeError("0005 left orphaned or inconsistently owned scenario results")
    if connection.exec_driver_sql(
        """
        SELECT count(*)
        FROM public.run_baselines AS baseline
        LEFT JOIN public.test_runs AS run ON run.run_id = baseline.run_id
        WHERE run.run_id IS NULL
           OR baseline.workspace_id IS DISTINCT FROM run.workspace_id
           OR baseline.project_id IS DISTINCT FROM run.project_id
        """
    ).scalar_one():
        raise RuntimeError("0005 left orphaned or inconsistently owned baselines")


def _guard_postgresql_downgrade() -> None:
    connection = op.get_bind()
    # Hold writers off until commit so a concurrent signup or tenant write cannot
    # slip in between this check and the table drops below.
    connection.exec_driver_sql(
        "LOCK TABLE public.profiles, public.workspaces, public.workspace_members, "
        "public.subscriptions, public.test_runs IN EXCLUSIVE MODE"
    )
    customer_state = connection.exec_driver_sql(
        """
        SELECT EXISTS (
            SELECT 1 FROM public.profiles
            UNION ALL
            SELECT 1 FROM public.workspace_members
            UNION ALL
            SELECT 1 FROM public.workspaces WHERE kind <> 'system'
            UNION ALL
            SELECT 1
            FROM public.subscriptions
            WHERE id NOT IN (
                '30000000-0000-4000-8000-000000000001'::uuid,
                '30000000-0000-4000-8000-000000000002'::uuid
            )
            UNION ALL
            SELECT 1
            FROM public.test_runs
            WHERE workspace_id IS NOT NULL
              AND workspace_id NOT IN (
                  '10000000-0000-4000-8000-000000000001'::uuid,
                  '10000000-0000-4000-8000-000000000002'::uuid
              )
        )
        """
    ).scalar_one()
    if customer_state:
        raise RuntimeError(
            "0005 downgrade blocked: customer tenancy state exists; "
            "use a disposable database instead of removing tenant ownership"
        )


def _drop_auth_bootstrap_trigger() -> None:
    """Drop the auth.users trigger, which PostgreSQL lets only the table owner do.

    Creating the trigger needs just the TRIGGER privilege, but dropping it needs
    ownership of auth.users, which Supabase gives to supabase_auth_admin. Try a
    direct drop first (owner, inherited owner membership or a platform grant),
    then act as the owner when the session may SET ROLE to it, otherwise fail
    before anything else in the downgrade has run.
    """

    connection = op.get_bind()
    drop_trigger = "DROP TRIGGER IF EXISTS on_auth_user_created_sinama_bootstrap ON auth.users"
    try:
        with connection.begin_nested():
            connection.exec_driver_sql(drop_trigger)
        return
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != "42501":
            raise

    owner, previous_role, can_set_owner = connection.exec_driver_sql(
        "SELECT pg_catalog.pg_get_userbyid(relowner), current_user, "
        "pg_catalog.pg_has_role(session_user, relowner, 'SET') "
        "FROM pg_catalog.pg_class WHERE oid = 'auth.users'::regclass"
    ).one()
    if not can_set_owner:
        raise RuntimeError(
            "0005 downgrade cannot drop the auth.users bootstrap trigger: the migration "
            "role must own auth.users or be able to SET ROLE to its owner. "
            "The downgrade was rolled back before any change."
        )
    quote = connection.dialect.identifier_preparer.quote
    connection.exec_driver_sql(f"SET LOCAL ROLE {quote(owner)}")
    connection.exec_driver_sql(drop_trigger)
    connection.exec_driver_sql(f"SET LOCAL ROLE {quote(previous_role)}")


def _drop_postgresql_security() -> None:
    connection = op.get_bind()
    for table, policy in (
        ("profiles", "profiles_select_self"),
        ("workspaces", "workspaces_select_public"),
        ("workspaces", "workspaces_select_member"),
        ("workspace_members", "workspace_members_select_member"),
        ("projects", "projects_select_public"),
        ("projects", "projects_select_member"),
        ("subscriptions", "subscriptions_select_member"),
        ("test_runs", "test_runs_select_public"),
        ("test_runs", "test_runs_select_member"),
        ("scenario_results", "scenario_results_select_public"),
        ("scenario_results", "scenario_results_select_member"),
        ("run_baselines", "run_baselines_select_public"),
        ("run_baselines", "run_baselines_select_member"),
        ("plans", "plans_select"),
        ("plan_entitlements", "plan_entitlements_select"),
    ):
        connection.exec_driver_sql(
            f'DROP POLICY IF EXISTS "{policy}" ON public."{table}"'
        )
    # RLS on the evidence tables belongs to 0003 and must survive this downgrade;
    # alembic_version also stays closed. Only the reads 0005 granted are withdrawn,
    # so the tables return to "RLS on, no customer policy, no customer grant".
    connection.exec_driver_sql(
        "REVOKE ALL ON TABLE public.test_runs, public.scenario_results, "
        "public.run_baselines FROM anon, authenticated"
    )

    connection.exec_driver_sql("DROP FUNCTION IF EXISTS public.repair_my_account()")
    connection.exec_driver_sql(
        "DROP FUNCTION IF EXISTS app_private.handle_new_auth_user()"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION IF EXISTS app_private.bootstrap_user(uuid,jsonb)"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION IF EXISTS app_private.has_role(uuid,text[])"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION IF EXISTS app_private.is_member(uuid)"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION IF EXISTS app_private.is_public_workspace(uuid)"
    )
    connection.exec_driver_sql("DROP SCHEMA IF EXISTS app_private")


def upgrade() -> None:
    if _is_postgresql():
        connection = op.get_bind()
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        if connection.exec_driver_sql("SELECT to_regclass('auth.users')").scalar_one() is None:
            raise RuntimeError("0005 requires Supabase auth.users")
        if connection.exec_driver_sql("SELECT to_regprocedure('auth.uid()')").scalar_one() is None:
            raise RuntimeError("0005 requires Supabase auth.uid()")

    _create_foundation_tables()
    _seed_foundation_rows()
    _add_expand_columns()

    if _is_postgresql():
        _add_postgresql_constraints()
        _create_postgresql_helpers()
        _create_postgresql_rls()
        _backfill_and_assert()


def downgrade() -> None:
    if _is_postgresql():
        connection = op.get_bind()
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        _guard_postgresql_downgrade()
        _drop_auth_bootstrap_trigger()
        _drop_postgresql_security()
        for constraint, table in (
            ("fk_profiles_auth_user", "profiles"),
            ("fk_workspace_members_auth_user", "workspace_members"),
            ("fk_test_runs_workspace", "test_runs"),
            ("ck_test_runs_workspace_project_pair", "test_runs"),
            ("fk_test_runs_project_workspace", "test_runs"),
            ("fk_scenario_results_workspace", "scenario_results"),
            ("fk_scenario_results_run_workspace", "scenario_results"),
            ("fk_run_baselines_workspace", "run_baselines"),
            ("ck_run_baselines_workspace_project_pair", "run_baselines"),
            ("fk_run_baselines_run_workspace_project", "run_baselines"),
            ("uq_test_runs_run_workspace_project", "test_runs"),
            ("uq_test_runs_run_workspace", "test_runs"),
        ):
            connection.exec_driver_sql(
                f'ALTER TABLE public."{table}" DROP CONSTRAINT IF EXISTS "{constraint}"'
            )

    op.drop_index("ix_run_baselines_project", table_name="run_baselines")
    op.drop_index("ix_run_baselines_workspace", table_name="run_baselines")
    op.drop_index("ix_scenario_results_workspace", table_name="scenario_results")
    op.drop_index("ix_test_runs_project_created_at", table_name="test_runs")
    op.drop_index("ix_test_runs_workspace_created_at", table_name="test_runs")
    op.drop_column("run_baselines", "project_id")
    op.drop_column("run_baselines", "workspace_id")
    op.drop_column("scenario_results", "workspace_id")
    op.drop_column("test_runs", "project_id")
    op.drop_column("test_runs", "workspace_id")

    op.drop_index("uq_subscriptions_one_current_per_workspace", table_name="subscriptions")
    op.drop_index("ix_subscriptions_workspace", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plan_entitlements")
    op.drop_table("plans")
    op.drop_index("ix_projects_workspace_archived", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_workspace_members_user_status", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("profiles")
