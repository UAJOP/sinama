from sqlalchemy import Engine, create_engine

from app.config import Settings


def create_run_store_engine(settings: Settings) -> Engine:
    """Build the production engine from settings.

    `hide_parameters` matters here: statement parameters carry full transcripts
    and tool arguments, so they must never reach logs on error.
    """

    return create_engine(
        settings.sqlalchemy_database_url(),
        # Hosted Postgres (Supabase/Railway) recycles idle connections; without a
        # pre-ping the first query after an idle period fails.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        hide_parameters=True,
        future=True,
    )
