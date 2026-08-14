"""Alembic environment.

The connection URL comes from SINAMA settings (SINAMA_DATABASE_URL), never from
alembic.ini, so no credential is ever committed. Tests may inject an already
configured engine through `config.attributes["connection"]`.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, Engine

from app.config import Settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_engine() -> Engine:
    from app.db.engine import create_run_store_engine

    return create_run_store_engine(Settings(run_store_backend="postgres"))  # type: ignore[arg-type]


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting - useful for reviewing a change."""

    context.configure(
        url=Settings(run_store_backend="postgres").sqlalchemy_database_url(),  # type: ignore[arg-type]
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    injected = config.attributes.get("connection")
    if isinstance(injected, Connection):
        _run_migrations(injected)
        return

    engine = _resolve_engine()
    with engine.connect() as connection:
        _run_migrations(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
