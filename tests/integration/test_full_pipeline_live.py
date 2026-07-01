"""Opt-in full-pipeline test: real planner + live retrieval.

Skipped unless ``OPENAI_API_KEY`` is set. Unlike the replay tests, this exercises
the LLM planner end to end and hits the CT.gov network, so it is not part of the
deterministic CI gate.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="requires OPENAI_API_KEY and network (opt-in full-pipeline test)",
)
def test_full_pipeline_time_trend_live() -> None:
    from app.api.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/visualize",
            json={
                "query": "How has the number of pembrolizumab trials changed per year since 2018?",
                "options": {"mode": "live"},
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visualization"]["type"] == "time_series"
    assert body["meta"]["studies_analyzed"] >= 0
