"""PostgreSQL-only migration, RLS and bootstrap coverage for revision 0005.

The suite is destructive and runs only when SINAMA_POSTGRES_SECURITY_DATABASE_URL
points at a disposable PostgreSQL 17 database reachable as a superuser.

The superuser only builds the fixture. Migrations run through a separate LOGIN
connection as a non-superuser migrator with BYPASSRLS (like production's
`postgres`), and auth.users writes run as supabase_auth_admin, mirroring the
production grants captured in the pre-migration dump:

- `auth` is owned by supabase_admin and `auth.users` by supabase_auth_admin,
  with RLS enabled on auth.users;
- the migrator holds TRIGGER/REFERENCES/... on auth.users but not ownership;
- the migrator may SET ROLE to supabase_auth_admin without inheriting it; and
- public-schema default ACLs grant ALL to anon, authenticated and service_role.

It is representative only and does not prove real Supabase behavior.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

TEST_DATABASE_URL = os.environ.get("SINAMA_POSTGRES_SECURITY_DATABASE_URL")
BACKEND_ROOT = os.path.dirname(os.path.dirname(__file__))

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set SINAMA_POSTGRES_SECURITY_DATABASE_URL to a disposable PostgreSQL database.",
)

USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("20000000-0000-0000-0000-000000000002")
USER_C = UUID("30000000-0000-0000-0000-000000000003")
USER_D = UUID("30000000-0000-0000-0000-000000000004")
USER_E = UUID("30000000-0000-0000-0000-000000000005")
PUBLIC_RUN = UUID("40000000-0000-0000-0000-000000000004")
PRIVATE_RUN = UUID("50000000-0000-0000-0000-000000000005")
USER_A_RUN = UUID("60000000-0000-0000-0000-000000000006")
USER_B_RUN = UUID("70000000-0000-0000-0000-000000000007")
LEGACY_RUNTIME_RUN = UUID("90000000-0000-0000-0000-000000000009")
USER_A_PROJECT = UUID("80000000-0000-4000-8000-000000000001")
USER_B_PROJECT = UUID("80000000-0000-4000-8000-000000000002")
PUBLIC_WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000001")
PRIVATE_WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000002")
PUBLIC_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000001")
PRIVATE_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000002")

MIGRATOR_ROLE = "sinama_migrator"
MIGRATOR_PASSWORD = "sinama-migrator-disposable"
AUTH_ADMIN_ROLE = "supabase_auth_admin"
AUTH_ADMIN_PASSWORD = "supabase-auth-admin-disposable"
BOOTSTRAP_TRIGGER = "on_auth_user_created_sinama_bootstrap"


def _alembic_config(connection: Connection) -> Config:
    config = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
    config.attributes["connection"] = connection
    return config


def _role_url(role: str, password: str) -> sa.URL:
    assert TEST_DATABASE_URL is not None
    return make_url(TEST_DATABASE_URL).set(username=role, password=password)


def _psycopg_url(url: sa.URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _superuser_psycopg_url() -> str:
    assert TEST_DATABASE_URL is not None
    return _psycopg_url(make_url(TEST_DATABASE_URL))


@contextmanager
def _role_connection(role: str, password: str) -> Iterator[Connection]:
    engine = create_engine(_role_url(role, password), future=True)
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT session_user").scalar_one() == role
            yield connection
    finally:
        engine.dispose()


def _migrate(direction: str, revision: str) -> None:
    """Run Alembic in a session that logs in as the migrator itself.

    SET ROLE is checked against the session user, so a superuser session with
    SET ROLE would hide missing migrator privileges. A real LOGIN does not.
    """

    with _role_connection(MIGRATOR_ROLE, MIGRATOR_PASSWORD) as connection:
        if direction == "upgrade":
            command.upgrade(_alembic_config(connection), revision)
        else:
            command.downgrade(_alembic_config(connection), revision)


def _insert_auth_user(user_id: UUID, metadata: dict[str, Any] | None = None) -> None:
    with _role_connection(AUTH_ADMIN_ROLE, AUTH_ADMIN_PASSWORD) as connection:
        connection.execute(
            sa.text(
                "INSERT INTO auth.users (id, raw_user_meta_data) "
                "VALUES (:id, CAST(:metadata AS jsonb))"
            ),
            {"id": user_id, "metadata": json.dumps(metadata or {})},
        )


def _delete_auth_user(user_id: UUID) -> None:
    with _role_connection(AUTH_ADMIN_ROLE, AUTH_ADMIN_PASSWORD) as connection:
        connection.execute(sa.text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})


def _ensure_role(connection: Connection, role: str, attributes: str) -> None:
    exists = connection.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).first()
    if exists is None:
        connection.exec_driver_sql(f"CREATE ROLE {role}")
    connection.exec_driver_sql(f"ALTER ROLE {role} {attributes}")


def _install_supabase_auth_shim(connection: Connection) -> None:
    _ensure_role(connection, "anon", "NOLOGIN NOSUPERUSER NOBYPASSRLS")
    _ensure_role(connection, "authenticated", "NOLOGIN NOSUPERUSER NOBYPASSRLS")
    _ensure_role(connection, "service_role", "NOLOGIN NOSUPERUSER BYPASSRLS")
    _ensure_role(connection, "supabase_admin", "NOLOGIN")
    _ensure_role(
        connection,
        AUTH_ADMIN_ROLE,
        f"LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS PASSWORD '{AUTH_ADMIN_PASSWORD}'",
    )
    _ensure_role(
        connection,
        MIGRATOR_ROLE,
        f"LOGIN INHERIT NOSUPERUSER BYPASSRLS PASSWORD '{MIGRATOR_PASSWORD}'",
    )
    connection.exec_driver_sql(f"ALTER ROLE {AUTH_ADMIN_ROLE} SET search_path = auth")
    # Able to act as the auth.users owner, but without inheriting its ownership:
    # upgrade must succeed on explicit grants alone.
    connection.exec_driver_sql(f"REVOKE {AUTH_ADMIN_ROLE} FROM {MIGRATOR_ROLE}")
    connection.exec_driver_sql(
        f"GRANT {AUTH_ADMIN_ROLE} TO {MIGRATOR_ROLE} WITH INHERIT FALSE, SET TRUE"
    )

    database_name = connection.exec_driver_sql("SELECT current_database()").scalar_one()
    quoted_database = connection.dialect.identifier_preparer.quote(database_name)
    connection.exec_driver_sql(f"GRANT CREATE ON DATABASE {quoted_database} TO {MIGRATOR_ROLE}")
    connection.exec_driver_sql(f"ALTER SCHEMA public OWNER TO {MIGRATOR_ROLE}")
    connection.exec_driver_sql(
        "GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role"
    )
    for object_type in ("TABLES", "FUNCTIONS", "SEQUENCES"):
        connection.exec_driver_sql(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR_ROLE} IN SCHEMA public "
            f"GRANT ALL ON {object_type} TO anon, authenticated, service_role"
        )

    connection.exec_driver_sql("CREATE SCHEMA auth AUTHORIZATION supabase_admin")
    connection.exec_driver_sql(
        """
        CREATE TABLE auth.users (
            id uuid PRIMARY KEY,
            raw_user_meta_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE FUNCTION auth.uid()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        AS $$
            SELECT (
                NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
            )::uuid
        $$
        """
    )
    connection.exec_driver_sql(f"ALTER TABLE auth.users OWNER TO {AUTH_ADMIN_ROLE}")
    connection.exec_driver_sql("ALTER TABLE auth.users ENABLE ROW LEVEL SECURITY")
    connection.exec_driver_sql(f"ALTER FUNCTION auth.uid() OWNER TO {AUTH_ADMIN_ROLE}")
    connection.exec_driver_sql(f"GRANT ALL ON SCHEMA auth TO {AUTH_ADMIN_ROLE}")
    connection.exec_driver_sql(
        f"GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role, {MIGRATOR_ROLE}"
    )
    connection.exec_driver_sql(
        "GRANT INSERT, REFERENCES, DELETE, TRIGGER, TRUNCATE, MAINTAIN, UPDATE "
        f"ON TABLE auth.users TO {MIGRATOR_ROLE}"
    )
    connection.exec_driver_sql(
        f"GRANT SELECT ON TABLE auth.users TO {MIGRATOR_ROLE} WITH GRANT OPTION"
    )


def _seed_legacy_evidence(connection: Connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO public.test_runs (
                run_id, pack_id, pack_name, pack_snapshot, agent_target, agent_mode,
                agent_label, lifecycle_status, created_at, started_at, completed_at
            ) VALUES
            (:public_run, 'insurance-v1', 'Insurance', CAST(:public_snapshot AS jsonb),
             'built_in_demo', 'healthy', 'healthy', 'completed',
             '2026-08-01T00:00:00Z', '2026-08-01T00:00:01Z', '2026-08-01T00:00:02Z'),
            (:private_run, 'ajoop-v1', 'AJOOP', CAST(:private_snapshot AS jsonb),
             'external_http', 'healthy', 'AJOOP', 'completed',
             '2026-08-02T00:00:00Z', '2026-08-02T00:00:01Z', '2026-08-02T00:00:02Z')
            """
        ),
        {
            "public_run": PUBLIC_RUN,
            "private_run": PRIVATE_RUN,
            "public_snapshot": json.dumps({"pack": "insurance", "evidence": [1, 2, 3]}),
            "private_snapshot": json.dumps({"pack": "ajoop", "evidence": {"safe": True}}),
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO public.scenario_results (
                run_id, position, scenario_id, status, payload, severity, goal_score,
                critical_failure_keys
            ) VALUES
            (:public_run, 0, 'INS-001', 'pass', CAST(:public_payload AS jsonb),
             'none', 100, CAST('[]' AS jsonb)),
            (:private_run, 0, 'AJOOP-001', 'pass', CAST(:private_payload AS jsonb),
             'none', 100, CAST('[]' AS jsonb))
            """
        ),
        {
            "public_run": PUBLIC_RUN,
            "private_run": PRIVATE_RUN,
            "public_payload": json.dumps({"result": "public", "turns": ["one"]}),
            "private_payload": json.dumps({"result": "private", "turns": ["two"]}),
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO public.run_baselines (pack_id, run_id, updated_at) VALUES
            ('insurance-v1', :public_run, '2026-08-03T00:00:00Z'),
            ('ajoop-v1', :private_run, '2026-08-03T00:00:01Z')
            """
        ),
        {"public_run": PUBLIC_RUN, "private_run": PRIVATE_RUN},
    )


def _evidence_digest(connection: Connection) -> tuple[str, str, str]:
    run_digest = connection.exec_driver_sql(
        """
        SELECT md5(string_agg(
            run_id::text || '|' || pack_snapshot::text || '|' || created_at::text,
            E'\n' ORDER BY run_id
        )) FROM public.test_runs
        """
    ).scalar_one()
    result_digest = connection.exec_driver_sql(
        """
        SELECT md5(string_agg(
            id::text || '|' || run_id::text || '|' || payload::text,
            E'\n' ORDER BY id
        )) FROM public.scenario_results
        """
    ).scalar_one()
    baseline_digest = connection.exec_driver_sql(
        """
        SELECT md5(string_agg(
            pack_id || '|' || run_id::text || '|' || updated_at::text,
            E'\n' ORDER BY pack_id
        )) FROM public.run_baselines
        """
    ).scalar_one()
    return run_digest, result_digest, baseline_digest


@pytest.fixture
def postgres_0004() -> Iterator[Engine]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS app_private CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS auth CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
        _install_supabase_auth_shim(connection)
    _migrate("upgrade", "0004")
    with _role_connection(MIGRATOR_ROLE, MIGRATOR_PASSWORD) as connection:
        _seed_legacy_evidence(connection)
    yield engine
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS app_private CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS auth CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


def _set_local_principal(connection: Connection, role: str, user_id: UUID | None) -> None:
    connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
    claims = {} if user_id is None else {"sub": str(user_id), "role": role}
    connection.execute(
        sa.text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(claims)},
    )


def _as_authenticated(cursor: psycopg.Cursor[Any], user_id: UUID) -> None:
    cursor.execute("SET LOCAL ROLE authenticated")
    cursor.execute(
        "SELECT set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(user_id), "role": "authenticated"}),),
    )


def _repair_as(user_id: UUID) -> None:
    with psycopg.connect(_superuser_psycopg_url()) as connection:
        with connection.cursor() as cursor:
            _as_authenticated(cursor, user_id)
            cursor.execute("SELECT public.repair_my_account()")


def _personal_workspace_id(connection: Connection, user_id: UUID) -> UUID:
    return connection.execute(
        sa.text(
            "SELECT id FROM public.workspaces "
            "WHERE personal_owner_id = :user_id AND kind = 'personal' AND visibility = 'private'"
        ),
        {"user_id": user_id},
    ).scalar_one()


def _bootstrap_trigger_count(connection: Connection) -> int:
    return connection.execute(
        sa.text(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgrelid = 'auth.users'::regclass AND tgname = :name"
        ),
        {"name": BOOTSTRAP_TRIGGER},
    ).scalar_one()


def test_0005_backfills_legacy_evidence_and_round_trips(postgres_0004: Engine) -> None:
    with postgres_0004.connect() as connection:
        before = _evidence_digest(connection)
    _migrate("upgrade", "0005")

    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        ownership = connection.exec_driver_sql(
            "SELECT agent_target, workspace_id, project_id FROM public.test_runs "
            "ORDER BY agent_target"
        ).all()
        assert ownership == [
            ("built_in_demo", PUBLIC_WORKSPACE_ID, PUBLIC_PROJECT_ID),
            ("external_http", PRIVATE_WORKSPACE_ID, PRIVATE_PROJECT_ID),
        ]
        inherited = connection.exec_driver_sql(
            """
            SELECT count(*)
            FROM public.scenario_results AS result
            JOIN public.test_runs AS run ON run.run_id = result.run_id
            WHERE result.workspace_id = run.workspace_id
            """
        ).scalar_one()
        assert inherited == 2
        baseline_packs = connection.exec_driver_sql(
            "SELECT pack_id FROM public.run_baselines ORDER BY pack_id"
        ).scalars().all()
        assert baseline_packs == ["ajoop-v1", "insurance-v1"]
        assert _bootstrap_trigger_count(connection) == 1

    _migrate("downgrade", "0004")
    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        assert "workspace_id" not in {
            column["name"] for column in inspect(connection).get_columns("test_runs")
        }
        assert _bootstrap_trigger_count(connection) == 0
        assert connection.exec_driver_sql(
            "SELECT to_regnamespace('app_private')"
        ).scalar_one() is None
        assert connection.exec_driver_sql(
            "SELECT to_regprocedure('public.repair_my_account()')"
        ).scalar_one() is None
        # Downgrade must not reopen what 0003/0005 closed.
        for table in ("test_runs", "scenario_results", "run_baselines", "alembic_version"):
            assert connection.exec_driver_sql(
                f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{table}'::regclass"
            ).scalar_one(), f"downgrade disabled RLS on {table}"
            for role in ("anon", "authenticated"):
                assert not connection.execute(
                    sa.text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                    {"role": role, "table": f"public.{table}"},
                ).scalar_one(), f"downgrade left {role} able to read {table}"

    _migrate("upgrade", "0005")
    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.test_runs WHERE workspace_id IS NULL"
        ).scalar_one() == 0
        assert _bootstrap_trigger_count(connection) == 1


@pytest.mark.parametrize(
    ("agent_target", "pack_id"),
    [
        ("unknown_target", "insurance-v1"),
        ("built_in_demo", "ecommerce-v1"),
    ],
)
def test_0005_fails_closed_for_unknown_or_inconsistent_legacy_target(
    postgres_0004: Engine,
    agent_target: str,
    pack_id: str,
) -> None:
    with postgres_0004.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE public.test_runs SET agent_target = :agent_target, pack_id = :pack_id "
                "WHERE run_id = :run_id"
            ),
            {"agent_target": agent_target, "pack_id": pack_id, "run_id": PUBLIC_RUN},
        )

    with pytest.raises(RuntimeError, match="cannot classify legacy agent targets"):
        _migrate("upgrade", "0005")

    with postgres_0004.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM public.alembic_version"
        ).scalar_one() == "0004"


def test_0005_composite_ownership_constraints_fail_closed(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")

    with pytest.raises(IntegrityError):
        with postgres_0004.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE public.scenario_results SET workspace_id = :public_workspace "
                    "WHERE run_id = :private_run"
                ),
                {"public_workspace": PUBLIC_WORKSPACE_ID, "private_run": PRIVATE_RUN},
            )

    with pytest.raises(IntegrityError):
        with postgres_0004.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE public.test_runs SET project_id = :public_project "
                    "WHERE run_id = :private_run"
                ),
                {"public_project": PUBLIC_PROJECT_ID, "private_run": PRIVATE_RUN},
            )

    with pytest.raises(IntegrityError):
        with postgres_0004.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE public.run_baselines "
                    "SET workspace_id = :public_workspace, project_id = :public_project "
                    "WHERE pack_id = 'ajoop-v1'"
                ),
                {
                    "public_workspace": PUBLIC_WORKSPACE_ID,
                    "public_project": PUBLIC_PROJECT_ID,
                },
            )

    with pytest.raises(IntegrityError):
        with postgres_0004.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE public.test_runs SET project_id = NULL WHERE run_id = :private_run"
                ),
                {"private_run": PRIVATE_RUN},
            )

    with postgres_0004.begin() as connection:
        _set_local_principal(connection, "anon", None)
        assert set(
            connection.exec_driver_sql("SELECT run_id FROM public.scenario_results").scalars()
        ) == {PUBLIC_RUN}

    # The unchanged runtime keeps writing unstamped NULL/NULL rows as the table
    # owner. They stay valid, stay invisible to customer roles, and a child
    # cannot claim a workspace while its parent run is unstamped.
    with _role_connection(MIGRATOR_ROLE, MIGRATOR_PASSWORD) as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO public.test_runs (
                    run_id, pack_id, pack_name, pack_snapshot, agent_target, agent_mode,
                    agent_label, lifecycle_status, created_at
                ) VALUES (
                    :run_id, 'insurance-v1', 'Insurance', '{}'::jsonb, 'built_in_demo',
                    'healthy', 'healthy', 'completed', now()
                )
                """
            ),
            {"run_id": LEGACY_RUNTIME_RUN},
        )
        connection.execute(
            sa.text(
                "INSERT INTO public.scenario_results (run_id, position, scenario_id, status, "
                "payload) VALUES (:run_id, 0, 'INS-001', 'pass', '{}'::jsonb)"
            ),
            {"run_id": LEGACY_RUNTIME_RUN},
        )
        connection.exec_driver_sql(
            "DELETE FROM public.run_baselines WHERE pack_id = 'insurance-v1'"
        )
        connection.execute(
            sa.text(
                "INSERT INTO public.run_baselines (pack_id, run_id, updated_at) "
                "VALUES ('insurance-v1', :run_id, now())"
            ),
            {"run_id": LEGACY_RUNTIME_RUN},
        )

    with postgres_0004.begin() as connection:
        _set_local_principal(connection, "anon", None)
        assert set(connection.exec_driver_sql("SELECT run_id FROM public.test_runs").scalars()) == {
            PUBLIC_RUN
        }
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.run_baselines"
        ).scalar_one() == 0

    with pytest.raises(IntegrityError):
        with postgres_0004.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE public.scenario_results SET workspace_id = :public_workspace "
                    "WHERE run_id = :run_id"
                ),
                {"public_workspace": PUBLIC_WORKSPACE_ID, "run_id": LEGACY_RUNTIME_RUN},
            )


def test_0005_repair_preserves_suspended_and_removed_memberships(
    postgres_0004: Engine,
) -> None:
    _migrate("upgrade", "0005")
    for user_id in (USER_D, USER_E):
        _insert_auth_user(user_id)
    with postgres_0004.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE public.workspace_members SET role = 'developer', status = 'suspended' "
                "WHERE user_id = :user_id"
            ),
            {"user_id": USER_D},
        )
        connection.execute(
            sa.text(
                "UPDATE public.workspace_members SET role = 'viewer', status = 'removed' "
                "WHERE user_id = :user_id"
            ),
            {"user_id": USER_E},
        )
        connection.execute(
            sa.text("DELETE FROM public.profiles WHERE id IN (:user_d, :user_e)"),
            {"user_d": USER_D, "user_e": USER_E},
        )
        connection.execute(
            sa.text(
                "DELETE FROM public.subscriptions WHERE workspace_id IN "
                "(SELECT id FROM public.workspaces WHERE personal_owner_id IN (:user_d, :user_e))"
            ),
            {"user_d": USER_D, "user_e": USER_E},
        )

    _repair_as(USER_D)
    _repair_as(USER_E)

    with postgres_0004.connect() as connection:
        memberships = connection.execute(
            sa.text(
                "SELECT user_id, role, status FROM public.workspace_members "
                "WHERE user_id IN (:user_d, :user_e) ORDER BY user_id"
            ),
            {"user_d": USER_D, "user_e": USER_E},
        ).all()
        assert memberships == [
            (USER_D, "developer", "suspended"),
            (USER_E, "viewer", "removed"),
        ]
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.profiles WHERE id IN (:user_d, :user_e)"),
            {"user_d": USER_D, "user_e": USER_E},
        ).scalar_one() == 2
        assert connection.execute(
            sa.text(
                "SELECT count(*) FROM public.subscriptions AS subscription "
                "JOIN public.workspaces AS workspace ON workspace.id = subscription.workspace_id "
                "WHERE workspace.personal_owner_id IN (:user_d, :user_e)"
            ),
            {"user_d": USER_D, "user_e": USER_E},
        ).scalar_one() == 2


def test_0005_repair_never_replaces_an_ended_subscription(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    _insert_auth_user(USER_D)
    with postgres_0004.begin() as connection:
        workspace_id = _personal_workspace_id(connection, USER_D)
        connection.execute(
            sa.text(
                "UPDATE public.subscriptions SET status = 'canceled', ended_at = now() "
                "WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        )

    _repair_as(USER_D)

    with postgres_0004.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT status FROM public.subscriptions WHERE workspace_id = :workspace_id"
            ),
            {"workspace_id": workspace_id},
        ).scalars().all() == ["canceled"]


def test_0005_trigger_failure_is_observable_and_lazy_repair_succeeds(
    postgres_0004: Engine,
) -> None:
    _migrate("upgrade", "0005")
    with postgres_0004.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE FUNCTION public.fail_sinama_profile_bootstrap()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'forced bootstrap failure' USING ERRCODE = 'check_violation';
            END
            $$
            """
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_sinama_profile_bootstrap "
            "BEFORE INSERT ON public.profiles FOR EACH ROW "
            "EXECUTE FUNCTION public.fail_sinama_profile_bootstrap()"
        )

    warnings: list[str] = []
    auth_admin_url = _psycopg_url(_role_url(AUTH_ADMIN_ROLE, AUTH_ADMIN_PASSWORD))
    with psycopg.connect(auth_admin_url) as auth_connection:
        auth_connection.add_notice_handler(
            lambda diagnostic: warnings.append(diagnostic.message_primary or "")
        )
        with auth_connection.cursor() as cursor:
            cursor.execute("INSERT INTO auth.users (id) VALUES (%s)", (USER_D,))
    assert "SINAMA account bootstrap deferred (SQLSTATE=23514)" in warnings

    with postgres_0004.connect() as connection:
        assert connection.execute(
            sa.text("SELECT count(*) FROM auth.users WHERE id = :id"), {"id": USER_D}
        ).scalar_one() == 1
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.profiles WHERE id = :id"), {"id": USER_D}
        ).scalar_one() == 0
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.workspaces WHERE personal_owner_id = :id"),
            {"id": USER_D},
        ).scalar_one() == 0

    with postgres_0004.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER fail_sinama_profile_bootstrap ON public.profiles"
        )
        connection.exec_driver_sql("DROP FUNCTION public.fail_sinama_profile_bootstrap()")

    _repair_as(USER_D)

    with postgres_0004.connect() as connection:
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.profiles WHERE id = :id"), {"id": USER_D}
        ).scalar_one() == 1
        workspace_id = _personal_workspace_id(connection, USER_D)
        assert connection.execute(
            sa.text(
                "SELECT count(*) FROM public.workspace_members "
                "WHERE workspace_id = :workspace_id AND user_id = :user_id "
                "AND role = 'owner' AND status = 'active'"
            ),
            {"workspace_id": workspace_id, "user_id": USER_D},
        ).scalar_one() == 1
        assert connection.execute(
            sa.text(
                "SELECT count(*) FROM public.subscriptions "
                "WHERE workspace_id = :workspace_id AND plan_code = 'free' AND status = 'active'"
            ),
            {"workspace_id": workspace_id},
        ).scalar_one() == 1


def _advisory_lock_waiters(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        ).scalar_one()


def test_0005_concurrent_repair_serializes_on_the_user_lock(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    _insert_auth_user(USER_A)
    with postgres_0004.begin() as connection:
        workspace_id = _personal_workspace_id(connection, USER_A)
        for statement in (
            "DELETE FROM public.subscriptions WHERE workspace_id = :workspace_id",
            "DELETE FROM public.workspace_members WHERE workspace_id = :workspace_id",
            "DELETE FROM public.workspaces WHERE id = :workspace_id",
        ):
            connection.execute(sa.text(statement), {"workspace_id": workspace_id})
        connection.execute(sa.text("DELETE FROM public.profiles WHERE id = :id"), {"id": USER_A})

    # The holder rebuilds every row but does not commit, so the others must queue
    # on the per-user advisory lock and then find the committed rows.
    with psycopg.connect(_superuser_psycopg_url()) as holder:
        with holder.cursor() as cursor:
            _as_authenticated(cursor, USER_A)
            cursor.execute("SELECT public.repair_my_account()")
        with ThreadPoolExecutor(max_workers=3) as pool:
            waiters = [pool.submit(_repair_as, USER_A) for _ in range(3)]
            try:
                deadline = time.monotonic() + 15
                while _advisory_lock_waiters(postgres_0004) < 3:
                    assert not any(waiter.done() for waiter in waiters), "repair did not queue"
                    assert time.monotonic() < deadline, "concurrent repairs never queued"
                    time.sleep(0.05)
                assert not any(waiter.done() for waiter in waiters)
            except BaseException:
                # Release the waiters before the pool joins them, or a failure hangs.
                holder.rollback()
                raise
            holder.commit()
            for waiter in waiters:
                waiter.result(timeout=15)

    with postgres_0004.connect() as connection:
        workspace_id = _personal_workspace_id(connection, USER_A)
        for statement, expected in (
            ("SELECT count(*) FROM public.profiles WHERE id = :user_id", 1),
            ("SELECT count(*) FROM public.workspaces WHERE personal_owner_id = :user_id", 1),
            ("SELECT count(*) FROM public.workspace_members WHERE user_id = :user_id", 1),
        ):
            assert connection.execute(
                sa.text(statement), {"user_id": USER_A}
            ).scalar_one() == expected
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.subscriptions WHERE workspace_id = :id"),
            {"id": workspace_id},
        ).scalar_one() == 1


def test_0005_user_deletion_keeps_workspace_evidence(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    _insert_auth_user(USER_D, {"display_name": "Deleted User"})
    with postgres_0004.begin() as connection:
        workspace_id = _personal_workspace_id(connection, USER_D)
        connection.execute(
            sa.text(
                "INSERT INTO public.projects (id, workspace_id, name, created_at, updated_at) "
                "VALUES (:id, :workspace_id, 'Kept', now(), now())"
            ),
            {"id": USER_A_PROJECT, "workspace_id": workspace_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO public.test_runs (
                    run_id, pack_id, pack_name, pack_snapshot, agent_target, agent_mode,
                    agent_label, lifecycle_status, created_at, workspace_id, project_id
                ) VALUES (
                    :run_id, 'kept', 'Kept', '{}'::jsonb, 'external_http', 'healthy',
                    'external_http', 'completed', now(), :workspace_id, :project_id
                )
                """
            ),
            {"run_id": USER_A_RUN, "workspace_id": workspace_id, "project_id": USER_A_PROJECT},
        )

    _delete_auth_user(USER_D)

    with postgres_0004.connect() as connection:
        for statement in (
            "SELECT count(*) FROM public.profiles WHERE id = :user_id",
            "SELECT count(*) FROM public.workspace_members WHERE user_id = :user_id",
        ):
            assert connection.execute(sa.text(statement), {"user_id": USER_D}).scalar_one() == 0
        workspace = connection.execute(
            sa.text("SELECT name, personal_owner_id FROM public.workspaces WHERE id = :id"),
            {"id": workspace_id},
        ).one()
        assert workspace == ("Personal workspace", USER_D)
        for statement in (
            "SELECT count(*) FROM public.subscriptions WHERE workspace_id = :id",
            "SELECT count(*) FROM public.test_runs WHERE workspace_id = :id",
        ):
            assert connection.execute(sa.text(statement), {"id": workspace_id}).scalar_one() == 1


def test_0005_downgrade_blocks_customer_tenancy(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    _insert_auth_user(USER_D)

    with pytest.raises(RuntimeError, match="downgrade blocked: customer tenancy state exists"):
        _migrate("downgrade", "0004")

    with postgres_0004.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM public.alembic_version"
        ).scalar_one() == "0005"
        assert _bootstrap_trigger_count(connection) == 1


def test_0005_downgrade_fails_closed_without_auth_owner_access(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    with postgres_0004.begin() as connection:
        connection.exec_driver_sql(f"REVOKE {AUTH_ADMIN_ROLE} FROM {MIGRATOR_ROLE}")

    with pytest.raises(RuntimeError, match="cannot drop the auth.users bootstrap trigger"):
        _migrate("downgrade", "0004")

    with postgres_0004.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM public.alembic_version"
        ).scalar_one() == "0005"
        assert _bootstrap_trigger_count(connection) == 1
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.workspaces WHERE kind = 'system'"
        ).scalar_one() == 2


def test_0005_bootstrap_rls_and_grants(postgres_0004: Engine) -> None:
    _migrate("upgrade", "0005")
    for user_id, display_name in (
        (USER_A, "User A"),
        (USER_B, "User B"),
        (USER_C, "User C"),
    ):
        _insert_auth_user(user_id, {"display_name": display_name})

    with postgres_0004.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM public.profiles").scalar_one() == 3
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.workspaces WHERE kind = 'personal'"
        ).scalar_one() == 3
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.workspace_members "
            "WHERE role = 'owner' AND status = 'active'"
        ).scalar_one() == 3
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.subscriptions AS subscription "
            "JOIN public.workspaces AS workspace ON workspace.id = subscription.workspace_id "
            "WHERE subscription.source = 'system' AND subscription.plan_code = 'free' "
            "AND workspace.personal_owner_id IS NOT NULL"
        ).scalar_one() == 3
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.projects AS project "
            "JOIN public.workspaces AS workspace ON workspace.id = project.workspace_id "
            "WHERE workspace.personal_owner_id IS NOT NULL"
        ).scalar_one() == 0
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.workspaces "
            "WHERE name <> 'Personal workspace' AND personal_owner_id IS NOT NULL"
        ).scalar_one() == 0

    with postgres_0004.begin() as connection:
        user_a_workspace = _personal_workspace_id(connection, USER_A)
        connection.execute(
            sa.text("DELETE FROM public.subscriptions WHERE workspace_id = :workspace_id"),
            {"workspace_id": user_a_workspace},
        )
        connection.execute(
            sa.text("DELETE FROM public.workspace_members WHERE user_id = :user_id"),
            {"user_id": USER_A},
        )
        connection.execute(
            sa.text("DELETE FROM public.profiles WHERE id = :user_id"),
            {"user_id": USER_A},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_repair_as, [USER_A] * 4))

    with postgres_0004.begin() as connection:
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.profiles WHERE id = :user_id"),
            {"user_id": USER_A},
        ).scalar_one() == 1
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.workspace_members WHERE user_id = :user_id"),
            {"user_id": USER_A},
        ).scalar_one() == 1
        assert connection.execute(
            sa.text("SELECT count(*) FROM public.subscriptions WHERE workspace_id = :workspace_id"),
            {"workspace_id": _personal_workspace_id(connection, USER_A)},
        ).scalar_one() == 1
        for user_id, label in ((USER_A, "A"), (USER_B, "B")):
            workspace_id = _personal_workspace_id(connection, user_id)
            project_id = USER_A_PROJECT if user_id == USER_A else USER_B_PROJECT
            pack_id = f"private-{label.lower()}"
            run_id = USER_A_RUN if user_id == USER_A else USER_B_RUN
            connection.execute(
                sa.text(
                    "INSERT INTO public.projects "
                    "(id, workspace_id, name, created_at, updated_at) "
                    "VALUES (:id, :workspace_id, :name, now(), now())"
                ),
                {"id": project_id, "workspace_id": workspace_id, "name": f"Private {label}"},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO public.test_runs (
                        run_id, pack_id, pack_name, pack_snapshot, agent_target,
                        agent_mode, agent_label, lifecycle_status, created_at,
                        workspace_id, project_id
                    ) VALUES (
                        :run_id, :pack_id, 'Private', '{}'::jsonb,
                        'built_in_demo', 'healthy', 'healthy', 'completed', now(),
                        :workspace_id, :project_id
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "pack_id": pack_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO public.scenario_results (
                        run_id, position, scenario_id, status, payload, workspace_id
                    ) VALUES (
                        :run_id, 0, :scenario_id, 'pass', '{}'::jsonb, :workspace_id
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "scenario_id": f"PRIVATE-{label}",
                    "workspace_id": workspace_id,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO public.run_baselines (
                        pack_id, run_id, updated_at, workspace_id, project_id
                    ) VALUES (:pack_id, :run_id, now(), :workspace_id, :project_id)
                    """
                ),
                {
                    "pack_id": pack_id,
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )

    with postgres_0004.begin() as connection:
        _set_local_principal(connection, "anon", None)
        anon_runs = set(connection.exec_driver_sql("SELECT run_id FROM public.test_runs").scalars())
        assert anon_runs == {PUBLIC_RUN}
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.workspaces"
        ).scalar_one() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM public.projects").scalar_one() == 1
        assert not connection.exec_driver_sql(
            "SELECT has_table_privilege('anon', 'public.workspace_members', 'SELECT')"
        ).scalar_one()
        assert not connection.exec_driver_sql(
            "SELECT has_table_privilege('anon', 'public.subscriptions', 'SELECT')"
        ).scalar_one()
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.scenario_results"
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.run_baselines"
        ).scalar_one() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM public.plans").scalar_one() == 3

    for user_id, own_suffix, other_suffix in ((USER_A, "6", "7"), (USER_B, "7", "6")):
        with postgres_0004.begin() as connection:
            _set_local_principal(connection, "authenticated", user_id)
            visible = {str(value) for value in connection.exec_driver_sql(
                "SELECT run_id FROM public.test_runs"
            ).scalars()}
            assert str(PUBLIC_RUN) in visible
            assert any(value.startswith(own_suffix) for value in visible)
            assert not any(value.startswith(other_suffix) for value in visible)
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.profiles"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.workspaces"
            ).scalar_one() == 2
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.workspace_members"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.projects"
            ).scalar_one() == 2
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.subscriptions"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.scenario_results"
            ).scalar_one() == 2
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM public.run_baselines"
            ).scalar_one() == 2

    with postgres_0004.begin() as connection:
        _set_local_principal(connection, "authenticated", USER_C)
        assert set(connection.exec_driver_sql("SELECT run_id FROM public.test_runs").scalars()) == {
            PUBLIC_RUN
        }
        assert connection.exec_driver_sql("SELECT count(*) FROM public.projects").scalar_one() == 1
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.scenario_results"
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.run_baselines"
        ).scalar_one() == 1

    tenant_tables = (
        "profiles",
        "workspaces",
        "workspace_members",
        "projects",
        "subscriptions",
        "test_runs",
        "scenario_results",
        "run_baselines",
    )
    with postgres_0004.connect() as connection:
        # The shim's default ACL granted ALL on every public table to these roles,
        # so these checks only pass because 0005 revoked it.
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM pg_default_acl WHERE defaclnamespace = 'public'::regnamespace"
        ).scalar_one() >= 3
        for role in ("anon", "authenticated"):
            for table in tenant_tables:
                for privilege in (
                    "DELETE",
                    "INSERT",
                    "REFERENCES",
                    "TRIGGER",
                    "TRUNCATE",
                    "UPDATE",
                ):
                    assert not connection.execute(
                        sa.text("SELECT has_table_privilege(:role, :table, :privilege)"),
                        {
                            "role": role,
                            "table": f"public.{table}",
                            "privilege": privilege,
                        },
                    ).scalar_one()
            assert not connection.execute(
                sa.text("SELECT has_table_privilege(:role, 'public.alembic_version', 'SELECT')"),
                {"role": role},
            ).scalar_one()
            for privilege in ("SELECT", "UPDATE", "USAGE"):
                assert not connection.execute(
                    sa.text(
                        "SELECT has_sequence_privilege("
                        ":role, 'public.scenario_results_id_seq', :privilege)"
                    ),
                    {"role": role, "privilege": privilege},
                ).scalar_one()

        function_matrix = {
            "app_private.is_member(uuid)": {
                "anon": False,
                "authenticated": True,
                "service_role": False,
            },
            "app_private.has_role(uuid,text[])": {
                "anon": False,
                "authenticated": True,
                "service_role": False,
            },
            "app_private.is_public_workspace(uuid)": {
                "anon": True,
                "authenticated": True,
                "service_role": False,
            },
            "app_private.bootstrap_user(uuid,jsonb)": {
                "anon": False,
                "authenticated": False,
                "service_role": False,
            },
            "app_private.handle_new_auth_user()": {
                "anon": False,
                "authenticated": False,
                "service_role": False,
            },
            "public.repair_my_account()": {
                "anon": False,
                "authenticated": True,
                "service_role": False,
            },
        }
        for function, expectations in function_matrix.items():
            for role, expected in expectations.items():
                assert connection.execute(
                    sa.text("SELECT has_function_privilege(:role, :function, 'EXECUTE')"),
                    {"role": role, "function": function},
                ).scalar_one() is expected, f"{role} EXECUTE on {function}"
        assert not connection.exec_driver_sql(
            "SELECT bool_or(grantee = 0) FROM pg_proc, aclexplode(proacl) "
            "WHERE oid = 'public.repair_my_account()'::regprocedure"
        ).scalar_one()

        assert connection.exec_driver_sql(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid = 'public.alembic_version'::regclass"
        ).scalar_one()
        assert connection.exec_driver_sql(
            "SELECT pg_get_userbyid(relowner) FROM pg_class "
            "WHERE oid = 'auth.users'::regclass"
        ).scalar_one() == AUTH_ADMIN_ROLE
        # Production's migration/definer role: not a superuser, but BYPASSRLS. The
        # repair function reads RLS-enabled auth.users and depends on that.
        migrator = connection.exec_driver_sql(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'sinama_migrator'"
        ).one()
        assert migrator == (False, True)
        assert connection.exec_driver_sql(
            "SELECT relrowsecurity FROM pg_class WHERE oid = 'auth.users'::regclass"
        ).scalar_one()
        # CREATE TRIGGER succeeded on the TRIGGER grant alone: the migrator never
        # inherits the auth.users owner's privileges.
        assert not connection.exec_driver_sql(
            f"SELECT pg_has_role('{MIGRATOR_ROLE}', '{AUTH_ADMIN_ROLE}', 'USAGE')"
        ).scalar_one()
        assert _bootstrap_trigger_count(connection) == 1

    for role in ("anon", "authenticated"):
        with psycopg.connect(_superuser_psycopg_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {role}")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute("SELECT version_num FROM public.alembic_version")
