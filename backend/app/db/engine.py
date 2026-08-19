from sqlalchemy import Engine, create_engine

from app.config import Settings

RUN_STORE_RLS_TABLES = ("test_runs", "scenario_results", "run_baselines")


def create_run_store_engine(settings: Settings) -> Engine:
    """Build the production engine from settings.

    `hide_parameters` matters here: statement parameters carry full transcripts
    and tool arguments, so they must never reach logs on error.
    """

    return create_engine(
        settings.sqlalchemy_database_url(),
        # Hosted Postgres providers recycle idle connections; without a pre-ping
        # the first query after an idle period can fail.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        hide_parameters=True,
        future=True,
    )


def enable_run_store_rls(engine: Engine) -> int:
    """Idempotently enable PostgreSQL RLS on SINAMA persistence tables.

    SINAMA accesses these tables only through its trusted server-side database
    connection. Browser/Data API access is not part of the product, so enabling
    RLS without public policies closes accidental direct access while leaving
    the table owner/server connection able to operate normally.

    Returns the number of existing tables hardened. Non-PostgreSQL engines are
    intentionally ignored so local SQLite migration/tests remain unaffected.
    """

    if engine.dialect.name != "postgresql":
        return 0

    hardened = 0
    with engine.begin() as connection:
        for table_name in RUN_STORE_RLS_TABLES:
            existing = connection.exec_driver_sql(
                "SELECT to_regclass(%s)",
                (f"public.{table_name}",),
            ).scalar_one()
            if existing is None:
                continue

            # table_name comes only from the constant tuple above.
            connection.exec_driver_sql(
                f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'
            )
            hardened += 1

    return hardened
