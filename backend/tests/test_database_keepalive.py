from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.main as main_module
from app.config import RunStoreBackend, Settings
from app.main import app


class _FakeResult:
    def scalar_one(self) -> int:
        return 1


class _FakeConnection:
    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def exec_driver_sql(self, statement: str) -> _FakeResult:
        assert statement == "SELECT 1"
        return _FakeResult()


class _FakeEngine:
    disposed = False

    def connect(self) -> _FakeConnection:
        return _FakeConnection()

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _production_settings(secret: str | None = "test-secret") -> Settings:
    return Settings(
        run_store_backend=RunStoreBackend.POSTGRES,
        database_url=SecretStr("postgresql://user:password@example.com:5432/sinama"),
        keepalive_secret=SecretStr(secret) if secret is not None else None,
    )


def test_database_keepalive_requires_configuration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "settings", Settings())

    response = client.get("/api/system/database-keepalive")

    assert response.status_code == 503


def test_database_keepalive_rejects_invalid_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "settings", _production_settings())

    response = client.get(
        "/api/system/database-keepalive",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_database_keepalive_executes_real_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine = _FakeEngine()
    monkeypatch.setattr(main_module, "settings", _production_settings())
    monkeypatch.setattr(main_module, "create_run_store_engine", lambda _settings: fake_engine)

    response = client.get(
        "/api/system/database-keepalive",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}
    assert fake_engine.disposed is True
