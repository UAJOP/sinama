from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_POSTGRES_DRIVER = "postgresql+psycopg"
_POSTGRES_URL_PREFIXES = ("postgresql://", "postgres://", "postgresql+psycopg://")


class RunStoreBackend(StrEnum):
    MEMORY = "memory"
    POSTGRES = "postgres"


class SemanticJudgeProvider(StrEnum):
    DISABLED = "disabled"
    OPENAI = "openai"


class Settings(BaseSettings):
    """Environment-backed settings for the local SINAMA API."""

    environment: str = "development"
    cors_origins: str = "http://localhost:3000"
    railway_environment_name: str | None = Field(
        default=None,
        validation_alias="RAILWAY_ENVIRONMENT_NAME",
    )
    external_agent_timeout_seconds: float = Field(default=60.0, gt=0, le=60.0)
    external_agent_max_response_bytes: int = Field(
        default=262_144,
        ge=1_024,
        le=1_048_576,
    )
    run_store_backend: RunStoreBackend = RunStoreBackend.MEMORY
    database_url: SecretStr | None = None
    run_history_limit: int = Field(default=20, ge=1, le=100)

    # Semantic evaluation is deliberately opt-in. Deterministic execution remains
    # fully functional with the default `disabled` provider and no API key.
    semantic_judge_provider: SemanticJudgeProvider = SemanticJudgeProvider.DISABLED
    semantic_judge_api_key: SecretStr | None = None
    semantic_judge_model: str = Field(default="gpt-5.4-nano", min_length=1, max_length=128)
    semantic_judge_timeout_seconds: float = Field(default=8.0, gt=0, le=20.0)
    semantic_judge_max_input_chars: int = Field(default=16_000, ge=2_000, le=50_000)
    # Calibration-only. A local CPU model is far slower than a hosted call, so the
    # offline calibration path gets its own budget. Nothing in the production
    # semantic path reads this value.
    semantic_judge_local_timeout_seconds: float = Field(default=180.0, gt=0, le=600.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SINAMA_",
        extra="ignore",
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

    @property
    def uses_semantic_judge(self) -> bool:
        return self.semantic_judge_provider is not SemanticJudgeProvider.DISABLED

    def sqlalchemy_database_url(self) -> str:
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
    def validate_runtime_configuration(self) -> "Settings":
        if self.run_store_backend is RunStoreBackend.POSTGRES:
            if self.database_url is None or not self.database_url.get_secret_value().strip():
                raise ValueError(
                    "SINAMA_RUN_STORE_BACKEND=postgres requires SINAMA_DATABASE_URL to be set."
                )
            if not self.database_url.get_secret_value().strip().startswith(
                _POSTGRES_URL_PREFIXES
            ):
                raise ValueError(
                    "SINAMA_DATABASE_URL must be a PostgreSQL connection string "
                    "(postgresql:// or postgresql+psycopg://)."
                )

        if self.semantic_judge_provider is SemanticJudgeProvider.OPENAI:
            if (
                self.semantic_judge_api_key is None
                or not self.semantic_judge_api_key.get_secret_value().strip()
            ):
                raise ValueError(
                    "SINAMA_SEMANTIC_JUDGE_PROVIDER=openai requires "
                    "SINAMA_SEMANTIC_JUDGE_API_KEY to be set."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
