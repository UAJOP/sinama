import pytest
from pydantic import ValidationError

from app.config import Settings
from app.http_agent import HttpAgentAdapter

PUBLIC_ENDPOINT = "https://93.184.216.34/agent"


def test_external_agent_timeout_defaults_to_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SINAMA_EXTERNAL_AGENT_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)
    adapter = HttpAgentAdapter(endpoint_url=PUBLIC_ENDPOINT)

    assert settings.external_agent_timeout_seconds == 60.0
    assert adapter.timeout_seconds == 60.0


def test_external_agent_timeout_accepts_sixty_seconds() -> None:
    adapter = HttpAgentAdapter(endpoint_url=PUBLIC_ENDPOINT, timeout_seconds=60.0)

    assert adapter.timeout_seconds == 60.0


def test_external_agent_timeout_rejects_values_above_sixty_seconds() -> None:
    with pytest.raises(ValueError, match="at most sixty"):
        HttpAgentAdapter(endpoint_url=PUBLIC_ENDPOINT, timeout_seconds=60.01)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, external_agent_timeout_seconds=60.01)
