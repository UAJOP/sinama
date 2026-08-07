from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SINAMA_",
        extra="ignore",
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
