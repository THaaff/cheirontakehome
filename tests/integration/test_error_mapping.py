"""Error-path tests: every failure uses the contract ErrorResponse shape.

Covers body validation (422), an upstream retrieval failure (502), and a
visualization/validation hard failure (500) — each tagged with the failing stage.
"""

from __future__ import annotations

from _replay_helpers import load_plan, seed_cache

from app.contracts import Settings


def _assert_error_shape(body: dict) -> None:
    assert set(body) == {"request_id", "error"}
    assert isinstance(body["request_id"], str) and body["request_id"]
    error = body["error"]
    assert set(error) >= {"type", "stage", "message"}


def test_malformed_body_returns_422(make_client) -> None:
    """An empty query fails body validation -> 422 ErrorResponse, stage=validation."""
    client = make_client(load_plan("time_trend.json"))

    resp = client.post("/visualize", json={"query": ""})

    assert resp.status_code == 422, resp.text
    body = resp.json()
    _assert_error_shape(body)
    assert body["error"]["stage"] == "validation"
    assert body["error"]["type"] == "invalid_request"


def test_retrieval_miss_returns_502(make_client, replay_settings: Settings) -> None:
    """A replay cache miss surfaces as an upstream failure -> 502, stage=retrieval."""
    plan = load_plan("time_trend.json")
    # Intentionally do NOT seed the cache: replay finds nothing -> RetrievalError.
    client = make_client(plan)

    resp = client.post("/visualize", json={"query": "x", "options": {"mode": "replay"}})

    assert resp.status_code == 502, resp.text
    body = resp.json()
    _assert_error_shape(body)
    assert body["error"]["stage"] == "retrieval"


def test_bad_encoding_field_returns_500(
    make_client, replay_settings: Settings, monkeypatch
) -> None:
    """A spec whose encoding references an absent field -> 500, stage=visualization."""
    import app.api.orchestrator as orchestrator

    plan = load_plan("time_trend.json")
    seed_cache(replay_settings.cache_dir, plan, "studies_pembrolizumab.json")

    real_build_viz = orchestrator.build_viz

    def _bad_build_viz(data: object, plan: object) -> object:
        spec = real_build_viz(data, plan)
        bad_x = spec.encoding.x.model_copy(update={"field": "___nope___"})
        bad_encoding = spec.encoding.model_copy(update={"x": bad_x})
        return spec.model_copy(update={"encoding": bad_encoding})

    monkeypatch.setattr(orchestrator, "build_viz", _bad_build_viz)
    client = make_client(plan)

    resp = client.post("/visualize", json={"query": "x", "options": {"mode": "replay"}})

    assert resp.status_code == 500, resp.text
    body = resp.json()
    _assert_error_shape(body)
    assert body["error"]["stage"] == "visualization"
