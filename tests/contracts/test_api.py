"""FastAPI contract-surface smoke tests (routes, schema, input validation).

The two former stub-behavior tests ("any valid request -> 200 chart") tested the
Phase 0 hardcoded stub, which the integration worktree replaced with the real
pipeline. End-to-end endpoint behavior across every operation is now covered
deterministically in ``tests/integration`` (replay mode, no key, no network).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_visualize_rejects_empty_query() -> None:
    resp = client.post("/visualize", json={"query": ""})
    assert resp.status_code == 422


def test_openapi_schema_is_served() -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "/visualize" in schema["paths"]
    assert "/health" in schema["paths"]
