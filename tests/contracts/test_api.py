"""FastAPI skeleton smoke tests (PRD Sections H and acceptance criteria)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app
from app.contracts import VisualizationRequest, VisualizationResponse

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_visualize_returns_valid_response_for_any_valid_request() -> None:
    body = VisualizationRequest(query="distribution of melanoma trials by phase").model_dump(
        mode="json"
    )
    resp = client.post("/visualize", json=body)
    assert resp.status_code == 200
    # Response validates against the frozen contract.
    parsed = VisualizationResponse.model_validate(resp.json())
    assert parsed.visualization.kind == "chart"
    assert parsed.meta.studies_analyzed >= 0


def test_visualize_with_example_bar_fixture() -> None:
    from conftest import FIXTURES_DIR, load_json

    body = load_json(FIXTURES_DIR / "requests" / "example_bar.json")
    resp = client.post("/visualize", json=body)
    assert resp.status_code == 200
    VisualizationResponse.model_validate(resp.json())


def test_visualize_rejects_empty_query() -> None:
    resp = client.post("/visualize", json={"query": ""})
    assert resp.status_code == 422


def test_openapi_schema_is_served() -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "/visualize" in schema["paths"]
    assert "/health" in schema["paths"]
