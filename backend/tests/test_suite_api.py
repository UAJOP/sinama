from fastapi.testclient import TestClient

from app.main import app


def test_collection_selector_api_exposes_packs_and_suite() -> None:
    with TestClient(app) as client:
        response = client.get("/api/scenario-packs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [
        "insurance-v1",
        "ecommerce-v1",
        "customer-service-core-v1",
    ]
    assert [item["kind"] for item in payload] == ["pack", "pack", "suite"]
    assert payload[1]["allowed_agent_targets"] == ["external_http"]
    assert payload[2]["included_pack_ids"] == ["insurance-v1", "ecommerce-v1"]
    assert payload[2]["scenario_count"] == 14


def test_typed_test_suite_api_exposes_pack_composition() -> None:
    with TestClient(app) as client:
        response = client.get("/api/test-suites")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "customer-service-core-v1",
            "name": "Customer Service Core Suite v1",
            "description": (
                "Cross-vertical suite composing the insurance and e-commerce reliability packs "
                "for agents that intentionally support both workflows. Requires an external "
                "HTTP agent."
            ),
            "pack_ids": ["insurance-v1", "ecommerce-v1"],
            "scenario_count": 14,
            "scenarios": response.json()[0]["scenarios"],
            "allowed_agent_targets": ["external_http"],
        }
    ]


def test_external_only_collections_reject_built_in_demo_runs() -> None:
    with TestClient(app) as client:
        ecommerce = client.post(
            "/api/runs",
            json={"pack_id": "ecommerce-v1", "agent_target": "built_in_demo"},
        )
        suite = client.post(
            "/api/runs",
            json={"pack_id": "customer-service-core-v1", "agent_target": "built_in_demo"},
        )

    assert ecommerce.status_code == 422
    assert "external_http" in ecommerce.json()["detail"]
    assert suite.status_code == 422
    assert "external_http" in suite.json()["detail"]


def test_suite_trends_has_a_first_class_route() -> None:
    with TestClient(app) as client:
        response = client.get("/api/test-suites/customer-service-core-v1/trends")
        missing = client.get("/api/test-suites/missing-suite/trends")

    assert response.status_code == 200
    assert response.json() == {"pack_id": "customer-service-core-v1", "points": []}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Test suite not found"}
