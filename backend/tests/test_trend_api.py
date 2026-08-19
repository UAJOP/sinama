import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.models import AgentMode
from app.test_runs import RunService, run_store


def execute(mode: AgentMode, version: str | None):  # type: ignore[no-untyped-def]
    async def run():  # type: ignore[no-untyped-def]
        service = RunService(store=run_store)
        created = await service.create_run("insurance-v1", mode, agent_version=version)
        return await service.wait_for_completion(created.run_id)

    return asyncio.run(run())


def test_trends_endpoint_returns_chronological_version_history() -> None:
    run_store.clear()
    try:
        first = execute(AgentMode.HEALTHY, None)
        second = execute(AgentMode.BROKEN_PREMATURE_SUBMISSION, "v2")

        with TestClient(app) as client:
            response = client.get("/api/scenario-packs/insurance-v1/trends?limit=20")

        assert response.status_code == 200
        payload = response.json()
        assert payload["pack_id"] == "insurance-v1"
        assert [point["run_id"] for point in payload["points"]] == [
            str(first.run_id),
            str(second.run_id),
        ]
        assert payload["points"][0]["agent_version"] is None
        assert payload["points"][0]["score"] == 100
        assert payload["points"][1]["agent_version"] == "v2"
        assert payload["points"][1]["direction"] == "regression"
        assert payload["points"][1]["outcomes"]["failed"] == 5
    finally:
        run_store.clear()


def test_trends_endpoint_rejects_unknown_pack() -> None:
    with TestClient(app) as client:
        response = client.get("/api/scenario-packs/not-a-pack/trends")

    assert response.status_code == 404
    assert response.json() == {"detail": "Scenario pack not found"}


def test_trends_endpoint_validates_limit() -> None:
    with TestClient(app) as client:
        response = client.get("/api/scenario-packs/insurance-v1/trends?limit=0")

    assert response.status_code == 422
