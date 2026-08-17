"""Shared test helpers.

Run creation is asynchronous, so API-level tests need a bounded poll to a
terminal lifecycle state. Kept here so the several suites that need it do not
each carry their own copy.
"""

import time

from fastapi.testclient import TestClient


def wait_for_api_run(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(400):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["lifecycle_status"] in {"completed", "error"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("Test run did not reach a terminal lifecycle state")
