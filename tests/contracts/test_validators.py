"""Validator enforcement — the operation matrix and request constraints (Section K).

These negative tests are the core "an invalid plan cannot be constructed" win.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    EdgeSemantics,
    NetworkSpec,
    NumericField,
    Operation,
    SeriesSpec,
    VisualizationRequest,
    VizType,
)

# ---------------------------------------------------------------------------
# AnalysisPlan: operation-to-required-fields matrix (PRD Section C)
# ---------------------------------------------------------------------------


def test_comparison_without_series_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.comparison,
            group_by=CategoricalField.lead_sponsor_class,
            proposed_viz=VizType.grouped_bar_chart,
            interpretation="compare sponsor mix",
        )


def test_comparison_without_group_by_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.comparison,
            series=SeriesSpec(dimension="condition", values=["melanoma", "lung cancer"]),
            proposed_viz=VizType.grouped_bar_chart,
            interpretation="compare sponsor mix",
        )


def test_categorical_distribution_without_group_by_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.categorical_distribution,
            proposed_viz=VizType.bar_chart,
            interpretation="distribution",
        )


def test_geographic_distribution_requires_group_by_country() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.geographic_distribution,
            group_by=CategoricalField.phase,
            proposed_viz=VizType.choropleth_map,
            interpretation="geo",
        )


def test_geographic_distribution_without_group_by_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.geographic_distribution,
            proposed_viz=VizType.choropleth_map,
            interpretation="geo",
        )


def test_cooccurrence_network_without_network_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.cooccurrence_network,
            proposed_viz=VizType.network_graph,
            interpretation="network",
        )


def test_numeric_distribution_without_numeric_x_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.numeric_distribution,
            proposed_viz=VizType.histogram,
            interpretation="hist",
        )


def test_numeric_relationship_without_numeric_y_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.numeric_relationship,
            numeric_x=NumericField.enrollment_count,
            proposed_viz=VizType.scatter_plot,
            interpretation="scatter",
        )


def test_numeric_relationship_without_numeric_x_raises() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlan(
            operation=Operation.numeric_relationship,
            numeric_y=NumericField.duration_days,
            proposed_viz=VizType.scatter_plot,
            interpretation="scatter",
        )


# ---------------------------------------------------------------------------
# Positive: each operation constructs when its requirements are met
# ---------------------------------------------------------------------------


def test_time_trend_requires_nothing_extra() -> None:
    plan = AnalysisPlan(
        operation=Operation.time_trend,
        proposed_viz=VizType.time_series,
        interpretation="annual trend",
    )
    assert plan.operation is Operation.time_trend


def test_valid_comparison_constructs() -> None:
    plan = AnalysisPlan(
        operation=Operation.comparison,
        group_by=CategoricalField.lead_sponsor_class,
        series=SeriesSpec(dimension="condition", values=["melanoma", "lung cancer"]),
        proposed_viz=VizType.grouped_bar_chart,
        interpretation="compare sponsor mix",
    )
    assert plan.series is not None


def test_valid_geographic_distribution_constructs() -> None:
    plan = AnalysisPlan(
        operation=Operation.geographic_distribution,
        group_by=CategoricalField.country,
        proposed_viz=VizType.choropleth_map,
        interpretation="geo",
    )
    assert plan.group_by is CategoricalField.country


def test_valid_cooccurrence_network_constructs() -> None:
    plan = AnalysisPlan(
        operation=Operation.cooccurrence_network,
        network=NetworkSpec(node_types=["sponsor", "drug"]),
        proposed_viz=VizType.network_graph,
        interpretation="network",
    )
    assert plan.network is not None


# ---------------------------------------------------------------------------
# Nested model constraints
# ---------------------------------------------------------------------------


def test_series_spec_requires_two_values() -> None:
    with pytest.raises(ValidationError):
        SeriesSpec(dimension="condition", values=["melanoma"])


def test_network_spec_max_nodes_bounds() -> None:
    with pytest.raises(ValidationError):
        NetworkSpec(node_types=["drug"], max_nodes=1)
    with pytest.raises(ValidationError):
        NetworkSpec(node_types=["drug"], max_nodes=201)


def test_sponsor_only_network_requires_shared_drug_semantics() -> None:
    # A trial has one lead sponsor, so co-occurrence-in-trial is impossible here.
    with pytest.raises(ValidationError):
        NetworkSpec(node_types=["sponsor"])  # defaults to co_occurrence_in_trial
    with pytest.raises(ValidationError):
        NetworkSpec(node_types=["sponsor"], edge_semantics="co_occurrence_in_trial")


def test_shared_drug_semantics_only_valid_for_sponsor_only() -> None:
    with pytest.raises(ValidationError):
        NetworkSpec(node_types=["sponsor", "drug"], edge_semantics="shared_drug")


def test_valid_sponsor_sponsor_network_constructs() -> None:
    spec = NetworkSpec(node_types=["sponsor"], edge_semantics="shared_drug")
    assert spec.edge_semantics is EdgeSemantics.shared_drug


# ---------------------------------------------------------------------------
# VisualizationRequest constraints (PRD Section B)
# ---------------------------------------------------------------------------


def test_empty_query_raises() -> None:
    with pytest.raises(ValidationError):
        VisualizationRequest(query="")


def test_whitespace_only_query_raises() -> None:
    with pytest.raises(ValidationError):
        VisualizationRequest(query="   ")


def test_query_is_stripped() -> None:
    req = VisualizationRequest(query="  trials for melanoma  ")
    assert req.query == "trials for melanoma"


def test_end_year_before_start_year_raises() -> None:
    with pytest.raises(ValidationError):
        VisualizationRequest(query="q", start_year=2022, end_year=2018)


def test_equal_start_and_end_year_ok() -> None:
    req = VisualizationRequest(query="q", start_year=2020, end_year=2020)
    assert req.start_year == req.end_year == 2020


def test_year_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        VisualizationRequest(query="q", start_year=1800)
    with pytest.raises(ValidationError):
        VisualizationRequest(query="q", end_year=2200)


def test_max_studies_bounds() -> None:
    from app.contracts import RequestOptions

    with pytest.raises(ValidationError):
        RequestOptions(max_studies=0)
    with pytest.raises(ValidationError):
        RequestOptions(max_studies=50001)
