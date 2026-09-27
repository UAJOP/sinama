"""PostgreSQL-only migration, RLS and bootstrap coverage for revision 0005.

The suite is destructive and runs only when SINAMA_POSTGRES_SECURITY_DATABASE_URL
points at a disposable PostgreSQL 17 database.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect

TEST_DATABASE_URL = os.environ.get("SINAMA_POSTGRES_SECURITY_DATABASE_URL")
BACKEND_ROOT = os.path.dirname(os.path.dirname(__file__))

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set SINAMA_POSTGRES_SECURITY_DATABASE_URL to a disposable PostgreSQL database.",
)

USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("20000000-0000-0000-0000-000000000002")
USER_C = UUID("30000000-0000-0000-0000-000000000003")
PUBLIC_RUN = UUID("40000000-0000-0000-0000-000000000004")
PRIVATE_RUN = UUID("50000000-0000-0000-0000-000000000005")
USER_A_RUN = UUID("60000000-0000-0000-0000-000000000006")
USER_B_RUN = UUID("70000000-0000-0000-0000-000000000007")


def _alembic_config(connection: Connection) -> Config:
    config = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
    config.attributes["connection"] = connection
    return config


def _install_supabase_auth_shim(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                CREATE ROLE anon NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                CREATE ROLE authenticated NOLOGIN;
            END IF;
        END
        $$
        """
    )
    connection.exec_driver_sql("CREATE SCHEMA auth")
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
    connection.exec_driver_sql("GRANT USAGE ON SCHEMA auth TO anon, authenticated")
    connection.exec_driver_sql("GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated")


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
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO PUBLIC")
        _install_supabase_auth_shim(connection)
        command.upgrade(_alembic_config(connection), "0004")
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


def test_0005_backfills_legacy_evidence_and_round_trips(postgres_0004: Engine) -> None:
    with postgres_0004.begin() as connection:
        before = _evidence_digest(connection)
        command.upgrade(_alembic_config(connection), "0005")

    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        ownership = connection.exec_driver_sql(
            "SELECT agent_target, workspace_id, project_id FROM public.test_runs "
            "ORDER BY agent_target"
        ).all()
        assert ownership == [
            ("built_in_demo", "sinama-public-demo", "system-project-public-demo"),
            ("external_http", "sinama-legacy-private", "system-project-legacy-private"),
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

    with postgres_0004.begin() as connection:
        command.downgrade(_alembic_config(connection), "0004")
    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        assert "workspace_id" not in {
            column["name"] for column in inspect(connection).get_columns("test_runs")
        }

    with postgres_0004.begin() as connection:
        command.upgrade(_alembic_config(connection), "0005")
    with postgres_0004.connect() as connection:
        assert _evidence_digest(connection) == before
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.test_runs WHERE workspace_id IS NULL"
        ).scalar_one() == 0


def test_0005_fails_closed_for_unknown_legacy_target(postgres_0004: Engine) -> None:
    with postgres_0004.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE public.test_runs SET agent_target = 'unknown_target' "
            "WHERE run_id = '40000000-0000-0000-0000-000000000004'"
        )

    with pytest.raises(RuntimeError, match="cannot classify legacy agent targets"):
        with postgres_0004.begin() as connection:
            command.upgrade(_alembic_config(connection), "0005")

    with postgres_0004.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM public.alembic_version"
        ).scalar_one() == "0004"


def _repair_concurrently(user_id: UUID) -> None:
    assert TEST_DATABASE_URL is not None
    psycopg_url = TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(psycopg_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE authenticated")
            cursor.execute(
                "SELECT set_config('request.jwt.claims', %s, true)",
                (json.dumps({"sub": str(user_id), "role": "authenticated"}),),
            )
            cursor.execute("SELECT public.repair_my_account()")


def test_0005_bootstrap_rls_and_grants(postgres_0004: Engine) -> None:
    with postgres_0004.begin() as connection:
        command.upgrade(_alembic_config(connection), "0005")
        for user_id, display_name in (
            (USER_A, "User A"),
            (USER_B, "User B"),
            (USER_C, "User C"),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO auth.users (id, raw_user_meta_data) "
                    "VALUES (:id, CAST(:metadata AS jsonb))"
                ),
                {"id": user_id, "metadata": json.dumps({"display_name": display_name})},
            )

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
            "SELECT count(*) FROM public.subscriptions "
            "WHERE source = 'system' AND plan_code = 'free' "
            "AND workspace_id LIKE 'personal-%%'"
        ).scalar_one() == 3
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM public.projects WHERE workspace_id LIKE 'personal-%%'"
        ).scalar_one() == 0

    with postgres_0004.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM public.subscriptions WHERE workspace_id = :workspace_id"),
            {"workspace_id": f"personal-{USER_A}"},
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
        list(pool.map(_repair_concurrently, [USER_A] * 4))

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
            {"workspace_id": f"personal-{USER_A}"},
        ).scalar_one() == 1
        for user_id, label in ((USER_A, "A"), (USER_B, "B")):
            workspace_id = f"personal-{user_id}"
            project_id = f"project-{label.lower()}"
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

    assert TEST_DATABASE_URL is not None
    psycopg_url = TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    for role in ("anon", "authenticated"):
        with psycopg.connect(psycopg_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {role}")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute("SELECT version_num FROM public.alembic_version")
