import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.models import AgentMode
from app.readiness import ReadinessReasonCode, ReleaseReadinessVerdict
from app.test_runs import RunService, run_store


async def _execute(mode: AgentMode, version: str | None = None):
    service = RunService(store=run_store)
    created = await service.create_run("insurance-v1", mode, agent_version=version)
    return await service.wait_for_completion(created.run_id)


def execute(mode: AgentMode, version: str | None = None):
    return asyncio.run(_execute(mode, version))


def test_readiness_endpoint_returns_warning_without_baseline_then_ready_as_baseline() -> None:
    run_store.clear()
    try:
        run = execute(AgentMode.HEALTHY, "v1")

        with TestClient(app) as client:
            before = client.get(f"/api/runs/{run.run_id}/readiness")

        assert before.status_code == 200
        before_payload = before.json()
        assert before_payload["verdict"] == ReleaseReadinessVerdict.WARNING.value
        assert [reason["code"] for reason in before_payload["reasons"]] == [
            ReadinessReasonCode.NO_BASELINE_COMPARISON.value
        ]

        run_store.set_baseline(run.run_id)
        with TestClient(app) as client:
            after = client.get(f"/api/runs/{run.run_id}/readiness")

        assert after.status_code == 200
        assert after.json()["verdict"] == ReleaseReadinessVerdict.READY.value
        assert after.json()["reasons"] == []
    finally:
        run_store.clear()


def test_readiness_endpoint_blocks_broken_regression() -> None:
    run_store.clear()
    try:
        baseline = execute(AgentMode.HEALTHY, "v1")
        run_store.set_baseline(baseline.run_id)
        broken = execute(AgentMode.BROKEN_PREMATURE_SUBMISSION, "v2")

        with TestClient(app) as client:
            response = client.get(f"/api/runs/{broken.run_id}/readiness")

        assert response.status_code == 200
        payload = response.json()
        assert payload["verdict"] == ReleaseReadinessVerdict.BLOCKED.value
        codes = {reason["code"] for reason in payload["reasons"]}
        assert ReadinessReasonCode.HIGH_FAILURE.value in codes
        assert ReadinessReasonCode.REGRESSION_DETECTED.value in codes
    finally:
        run_store.clear()


def test_readiness_endpoint_returns_404_for_unknown_run() -> None:
    with TestClient(app) as client:
        response = client.get("/api/runs/00000000-0000-0000-0000-000000000000/readiness")

    assert response.status_code == 404
    assert response.json() == {"detail": "Test run not found"}
