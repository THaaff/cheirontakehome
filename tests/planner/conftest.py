"""Shared fakes for the planner test suite.

All planner tests run **offline**: the real ``AsyncOpenAI`` client is never
constructed. We monkeypatch ``app.planner.client._get_client`` to return a
``FakeClient`` whose ``responses.parse`` yields pre-canned fake responses (or
raises pre-canned exceptions). Fake responses are ``SimpleNamespace`` objects
shaped exactly like the bits of the Responses API the client inspects
(``status``, ``incomplete_details``, ``output[].content[]``, ``output_parsed``).

Async entrypoints are driven with ``asyncio.run`` from sync test functions, so no
``pytest-asyncio`` dependency is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.contracts import (
    CategoricalField,
    Entities,
    Filters,
    NodeType,
    NumericField,
    Operation,
    OverallStatus,
    SeriesDimension,
    Settings,
    VizType,
)
from app.planner.schema import PlannerNetwork, PlannerOutput, PlannerSeries

# ---------------------------------------------------------------------------
# Fake Responses-API objects
# ---------------------------------------------------------------------------


def make_resp(
    parsed: PlannerOutput | None = None,
    *,
    refusal: str | None = None,
    incomplete_reason: str | None = None,
) -> SimpleNamespace:
    """Build a fake ``ParsedResponse``-shaped object for the client to inspect."""
    status = "incomplete" if incomplete_reason else "completed"
    incomplete_details = (
        SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None
    )
    output: list[Any] = []
    if refusal is not None:
        output = [SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal=refusal)])]
    return SimpleNamespace(
        status=status,
        incomplete_details=incomplete_details,
        output=output,
        output_parsed=parsed,
    )


class FakeResponses:
    """Stand-in for ``client.responses`` whose ``parse`` returns canned results."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._results:
            raise AssertionError("responses.parse called more times than expected")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    """Stand-in for ``AsyncOpenAI`` exposing only ``.responses.parse``."""

    def __init__(self, results: list[Any]) -> None:
        self.responses = FakeResponses(results)


def install_fake_client(monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> FakeClient:
    """Patch the client factory to return a ``FakeClient`` over ``results``."""
    client = FakeClient(results)
    monkeypatch.setattr("app.planner.client._get_client", lambda settings: client)
    return client


# ---------------------------------------------------------------------------
# Fixtures and PlannerOutput factories
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key="sk-test", planner_model="gpt-4.1")


def time_trend_output() -> PlannerOutput:
    return PlannerOutput(
        operation=Operation.time_trend,
        entities=Entities(drug="pembrolizumab"),
        filters=Filters(start_year=2018),
        time_granularity="year",
        measure=None,
        proposed_viz=VizType.time_series,
        interpretation="Annual count of pembrolizumab trials since 2018.",
        assumptions=["Interpreted 'since 2018' as start_year >= 2018."],
    )


def comparison_output() -> PlannerOutput:
    return PlannerOutput(
        operation=Operation.comparison,
        entities=Entities(),
        filters=Filters(),
        group_by=CategoricalField.lead_sponsor_class,
        series=PlannerSeries(
            dimension=SeriesDimension.condition, values=["melanoma", "lung cancer"]
        ),
        proposed_viz=VizType.grouped_bar_chart,
        interpretation="Sponsor-class mix across melanoma and lung cancer trials.",
        assumptions=[],
    )


def invalid_comparison_output() -> PlannerOutput:
    """A comparison missing its `series` — valid PlannerOutput, invalid AnalysisPlan."""
    return PlannerOutput(
        operation=Operation.comparison,
        entities=Entities(),
        filters=Filters(),
        group_by=CategoricalField.lead_sponsor_class,
        series=None,
        proposed_viz=VizType.grouped_bar_chart,
        interpretation="Sponsor-class mix across two conditions.",
        assumptions=[],
    )


def network_output() -> PlannerOutput:
    return PlannerOutput(
        operation=Operation.cooccurrence_network,
        entities=Entities(condition="melanoma"),
        filters=Filters(statuses=[OverallStatus.RECRUITING]),
        network=PlannerNetwork(node_types=[NodeType.sponsor, NodeType.drug]),
        proposed_viz=VizType.network_graph,
        interpretation="Network of sponsors co-occurring in melanoma trials.",
        assumptions=[],
    )


def numeric_distribution_output() -> PlannerOutput:
    return PlannerOutput(
        operation=Operation.numeric_distribution,
        entities=Entities(condition="melanoma"),
        filters=Filters(),
        numeric_x=NumericField.enrollment_count,
        proposed_viz=VizType.histogram,
        interpretation="Distribution of enrollment sizes across melanoma trials.",
        assumptions=[],
    )
