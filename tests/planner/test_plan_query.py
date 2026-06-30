"""plan_query end-to-end against a mocked client (happy path + key guard)."""

from __future__ import annotations

import asyncio

import pytest

from app.contracts import CategoricalField, Operation, Settings, VisualizationRequest
from app.planner import PlanningError, plan_query

from .conftest import (
    comparison_output,
    install_fake_client,
    make_resp,
    time_trend_output,
)


def test_plan_query_happy_path_time_trend(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    client = install_fake_client(monkeypatch, [make_resp(time_trend_output())])
    req = VisualizationRequest(
        query="trials for pembrolizumab per year since 2018",
        drug_name="pembrolizumab",
        start_year=2018,
    )
    plan = asyncio.run(plan_query(req, settings))

    assert plan.operation is Operation.time_trend
    assert plan.entities.drug is not None and "pembrolizumab" in plan.entities.drug.lower()
    assert plan.filters.start_year == 2018
    # exactly one model call, made with temperature 0 and the right model
    assert len(client.responses.calls) == 1
    assert client.responses.calls[0]["temperature"] == 0
    assert client.responses.calls[0]["model"] == "gpt-4.1"


def test_plan_query_happy_path_comparison(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    install_fake_client(monkeypatch, [make_resp(comparison_output())])
    req = VisualizationRequest(query="compare sponsor types for melanoma vs lung cancer")
    plan = asyncio.run(plan_query(req, settings))

    assert plan.operation is Operation.comparison
    assert plan.group_by is CategoricalField.lead_sponsor_class
    assert plan.series is not None and len(plan.series.values) == 2


def test_plan_query_missing_key_raises_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If a client were built, this fake would error; we assert it is never reached.
    client = install_fake_client(monkeypatch, [])
    settings = Settings(openai_api_key=None)
    req = VisualizationRequest(query="anything")

    with pytest.raises(PlanningError) as excinfo:
        asyncio.run(plan_query(req, settings))

    assert excinfo.value.reason == "missing_api_key"
    assert client.responses.calls == []


def test_empty_string_key_also_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(monkeypatch, [])
    settings = Settings(openai_api_key="")
    with pytest.raises(PlanningError) as excinfo:
        asyncio.run(plan_query(VisualizationRequest(query="q"), settings))
    assert excinfo.value.reason == "missing_api_key"
