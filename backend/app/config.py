from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_POSTGRES_DRIVER = "postgresql+psycopg"
# Hosted providers (Supabase, Heroku, Railway) hand out `postgres://` URLs, which
# SQLAlchemy rejects outright. Normalize those onto the driver we actually ship.
_POSTGRES_URL_PREFIXES = ("postgresql://", "postgres://", "postgresql+psycopg://")


class RunStoreBackend(StrEnum):
    MEMORY = "memory"
    POSTGRES = "postgres"


class Settings(BaseSettings):
    """Environment-backed settings for the local SINAMA API."""

    environment: str = "development"
    cors_origins: str = "http://localhost:3000"
    railway_environment_name: str | None = Field(
        default=None,
        validation_alias="RAILWAY_ENVIRONMENT_NAME",
    )
    external_agent_timeout_seconds: float = Field(default=4.0, gt=0, le=5.0)
    external_agent_max_response_bytes: int = Field(
        default=262_144,
        ge=1_024,
        le=1_048_576,
    )
    run_store_backend: RunStoreBackend = RunStoreBackend.MEMORY
    # SecretStr so an accidental repr/log of Settings never prints credentials.
    database_url: SecretStr | None = None
    run_history_limit: int = Field(default=20, ge=1, le=100)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SINAMA_",
        extra="ignore",
        # Validation errors would otherwise echo the raw input dict - which holds
        # the database URL, credentials included - into startup tracebacks.
        hide_input_in_errors=True,
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return (
            self.environment.casefold() == "production"
            or self.railway_environment_name is not None
        )

    @property
    def uses_persistent_run_store(self) -> bool:
        return self.run_store_backend is RunStoreBackend.POSTGRES

    def sqlalchemy_database_url(self) -> str:
        """Driver-qualified URL for engine construction.

        Deliberately a method rather than a property: the return value is a live
        credential and must never be treated as a printable attribute.
        """

        if self.database_url is None:
            raise ValueError(
                "SINAMA_DATABASE_URL is required when SINAMA_RUN_STORE_BACKEND=postgres."
            )
        url = self.database_url.get_secret_value().strip()
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return f"{_POSTGRES_DRIVER}://{url[len(prefix):]}"
        raise ValueError("SINAMA_DATABASE_URL must be a PostgreSQL connection string.")

    @model_validator(mode="after")
    def _validate_run_store(self) -> "Settings":
        if self.run_store_backend is not RunStoreBackend.POSTGRES:
            return self
        if self.database_url is None or not self.database_url.get_secret_value().strip():
            raise ValueError(
                "SINAMA_RUN_STORE_BACKEND=postgres requires SINAMA_DATABASE_URL to be set."
            )
        if not self.database_url.get_secret_value().strip().startswith(_POSTGRES_URL_PREFIXES):
            raise ValueError(
                "SINAMA_DATABASE_URL must be a PostgreSQL connection string "
                "(postgresql:// or postgresql+psycopg://)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
