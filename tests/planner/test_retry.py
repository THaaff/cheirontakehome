"""One-retry-on-ValidationError: feed the error back, then fail cleanly."""

from __future__ import annotations

import asyncio

import pytest

from app.contracts import Operation, Settings, VisualizationRequest
from app.planner import PlanningError, plan_query

from .conftest import (
    comparison_output,
    install_fake_client,
    invalid_comparison_output,
    make_resp,
)


def test_invalid_then_valid_retries_once_and_succeeds(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    client = install_fake_client(
        monkeypatch,
        [
            make_resp(invalid_comparison_output()),  # fails AnalysisPlan validation
            make_resp(comparison_output()),  # corrected on retry
        ],
    )
    req = VisualizationRequest(query="compare sponsor types for melanoma vs lung cancer")
    plan = asyncio.run(plan_query(req, settings))

    assert plan.operation is Operation.comparison
    assert plan.series is not None
    # exactly one retry -> two calls; the retry carried the correction turns
    assert len(client.responses.calls) == 2
    retry_input = client.responses.calls[1]["input"]
    assert len(retry_input) > len(client.responses.calls[0]["input"])
    assert any("failed validation" in str(m.get("content", "")) for m in retry_input)


def test_invalid_twice_raises_planning_error_after_one_retry(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    client = install_fake_client(
        monkeypatch,
        [
            make_resp(invalid_comparison_output()),
            make_resp(invalid_comparison_output()),
        ],
    )
    req = VisualizationRequest(query="compare sponsor types for melanoma vs lung cancer")
    with pytest.raises(PlanningError) as excinfo:
        asyncio.run(plan_query(req, settings))

    assert excinfo.value.reason == "validation"
    assert excinfo.value.details.get("first_error")
    assert excinfo.value.details.get("second_error")
    # capped at one retry: exactly two calls, never a third
    assert len(client.responses.calls) == 2
