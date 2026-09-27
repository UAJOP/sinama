"""Add workspace tenancy, entitlement metadata, RLS and auth bootstrap.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

This is an expand migration. Existing runtime writes remain valid because the
ownership columns added to run evidence are nullable. Contract enforcement and
the non-owner runtime role transition belong to later checkpoints.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_PAYLOAD = sa.JSON().with_variant(JSONB(), "postgresql")
TIMESTAMP = sa.DateTime(timezone=True)

WORKSPACE_ID_LENGTH = 128
PROJECT_ID_LENGTH = 128
PLAN_CODE_LENGTH = 32
ENTITLEMENT_KEY_LENGTH = 128
LABEL_LENGTH = 128
STATUS_LENGTH = 32

PUBLIC_WORKSPACE_ID = "sinama-public-demo"
PRIVATE_WORKSPACE_ID = "sinama-legacy-private"
PUBLIC_PROJECT_ID = "system-project-public-demo"
PRIVATE_PROJECT_ID = "system-project-legacy-private"


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
        sa.Column("id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=False),
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
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_members_workspace_user",
        ),
    )
    op.create_index(
        "ix_workspace_members_user_status",
        "workspace_members",
        ["user_id", "status"],
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=PROJECT_ID_LENGTH), nullable=False),
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=False),
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
        sa.Column("id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=False),
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=False),
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
        sa.column("id", sa.String()),
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
                "name": "SINAMA Public Demo",
                "kind": "system",
                "visibility": "public",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PRIVATE_WORKSPACE_ID,
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
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
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
        sa.column("id", sa.String()),
        sa.column("workspace_id", sa.String()),
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
                "id": "system-subscription-public-demo",
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
                "id": "system-subscription-legacy-private",
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
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=True),
    )
    op.add_column(
        "test_runs",
        sa.Column("project_id", sa.String(length=PROJECT_ID_LENGTH), nullable=True),
    )
    op.add_column(
        "scenario_results",
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=True),
    )
    op.add_column(
        "run_baselines",
        sa.Column("workspace_id", sa.String(length=WORKSPACE_ID_LENGTH), nullable=True),
    )
    op.add_column(
        "run_baselines",
        sa.Column("project_id", sa.String(length=PROJECT_ID_LENGTH), nullable=True),
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
    statements = (
        "ALTER TABLE public.profiles ADD CONSTRAINT fk_profiles_auth_user "
        "FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE public.workspace_members ADD CONSTRAINT fk_workspace_members_auth_user "
        "FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE public.test_runs ADD CONSTRAINT fk_test_runs_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.test_runs ADD CONSTRAINT fk_test_runs_project "
        "FOREIGN KEY (project_id) REFERENCES public.projects(id) NOT VALID",
        "ALTER TABLE public.scenario_results ADD CONSTRAINT fk_scenario_results_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.run_baselines ADD CONSTRAINT fk_run_baselines_workspace "
        "FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) NOT VALID",
        "ALTER TABLE public.run_baselines ADD CONSTRAINT fk_run_baselines_project "
        "FOREIGN KEY (project_id) REFERENCES public.projects(id) NOT VALID",
    )
    for statement in statements:
        connection.exec_driver_sql(statement)
    for constraint, table in (
        ("fk_profiles_auth_user", "profiles"),
        ("fk_workspace_members_auth_user", "workspace_members"),
        ("fk_test_runs_workspace", "test_runs"),
        ("fk_test_runs_project", "test_runs"),
        ("fk_scenario_results_workspace", "scenario_results"),
        ("fk_run_baselines_workspace", "run_baselines"),
        ("fk_run_baselines_project", "run_baselines"),
    ):
        connection.exec_driver_sql(
            f'ALTER TABLE public."{table}" VALIDATE CONSTRAINT "{constraint}"'
        )


def _create_postgresql_helpers() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("CREATE SCHEMA app_private")
    connection.exec_driver_sql(
        """
        CREATE FUNCTION app_private.is_member(target_workspace_id text)
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
        CREATE FUNCTION app_private.has_role(target_workspace_id text, allowed_roles text[])
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
        CREATE FUNCTION app_private.is_public_workspace(target_workspace_id text)
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
            personal_workspace_id text := 'personal-' || target_user_id::text;
            personal_subscription_id text := 'personal-subscription-' || target_user_id::text;
            resolved_display_name text := NULLIF(
                pg_catalog.left(
                    COALESCE(raw_metadata ->> 'display_name', raw_metadata ->> 'full_name'),
                    128
                ),
                ''
            );
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(personal_workspace_id, 0)
            );

            INSERT INTO public.profiles (id, display_name, created_at, updated_at)
            VALUES (target_user_id, resolved_display_name, pg_catalog.now(), pg_catalog.now())
            ON CONFLICT (id) DO UPDATE
            SET display_name = COALESCE(public.profiles.display_name, EXCLUDED.display_name),
                updated_at = pg_catalog.now();

            INSERT INTO public.workspaces (
                id, name, kind, visibility, created_at, updated_at
            )
            VALUES (
                personal_workspace_id,
                COALESCE(
                    pg_catalog.left(resolved_display_name, 118) || ' workspace',
                    'Personal workspace'
                ),
                'personal',
                'private',
                pg_catalog.now(),
                pg_catalog.now()
            )
            ON CONFLICT (id) DO NOTHING;

            INSERT INTO public.workspace_members (
                workspace_id, user_id, role, status, created_at
            )
            VALUES (
                personal_workspace_id, target_user_id, 'owner', 'active', pg_catalog.now()
            )
            ON CONFLICT (workspace_id, user_id) DO UPDATE
            SET role = 'owner', status = 'active';

            INSERT INTO public.subscriptions (
                id, workspace_id, plan_code, status, source, started_at,
                current_period_start, current_period_end, ended_at, created_at, updated_at
            )
            SELECT
                personal_subscription_id,
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
            WHERE NOT EXISTS (
                SELECT 1
                FROM public.subscriptions AS subscription
                WHERE subscription.workspace_id = personal_workspace_id
                  AND subscription.status IN ('active', 'trialing', 'past_due')
            )
            ON CONFLICT (id) DO NOTHING;
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
            RAISE WARNING 'SINAMA account bootstrap deferred for lazy repair';
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
        "app_private.is_member(text)",
        "app_private.has_role(text,text[])",
        "app_private.is_public_workspace(text)",
        "app_private.bootstrap_user(uuid,jsonb)",
        "app_private.handle_new_auth_user()",
        "public.repair_my_account()",
    ):
        connection.exec_driver_sql(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.is_member(text) TO authenticated"
    )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.has_role(text,text[]) TO authenticated"
    )
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION app_private.is_public_workspace(text) TO anon, authenticated"
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


def _evidence_signatures() -> tuple[int, int, int, str, str]:
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
    return run_count, result_count, baseline_count, run_evidence, result_evidence


def _backfill_and_assert() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE public.test_runs, public.scenario_results, public.run_baselines "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    before = _evidence_signatures()
    unknown = connection.exec_driver_sql(
        """
        SELECT agent_target, count(*)
        FROM public.test_runs
        WHERE agent_target NOT IN ('built_in_demo', 'external_http')
        GROUP BY agent_target
        ORDER BY agent_target
        """
    ).all()
    if unknown:
        raise RuntimeError(f"0005 cannot classify legacy agent targets: {unknown!r}")

    connection.exec_driver_sql(
        """
        UPDATE public.test_runs
        SET workspace_id = CASE agent_target
                WHEN 'built_in_demo' THEN 'sinama-public-demo'
                WHEN 'external_http' THEN 'sinama-legacy-private'
            END,
            project_id = CASE agent_target
                WHEN 'built_in_demo' THEN 'system-project-public-demo'
                WHEN 'external_http' THEN 'system-project-legacy-private'
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
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS on_auth_user_created_sinama_bootstrap ON auth.users"
        )
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS public.repair_my_account()")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS app_private CASCADE")
        for constraint, table in (
            ("fk_profiles_auth_user", "profiles"),
            ("fk_workspace_members_auth_user", "workspace_members"),
            ("fk_test_runs_workspace", "test_runs"),
            ("fk_test_runs_project", "test_runs"),
            ("fk_scenario_results_workspace", "scenario_results"),
            ("fk_run_baselines_workspace", "run_baselines"),
            ("fk_run_baselines_project", "run_baselines"),
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
