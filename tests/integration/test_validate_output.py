"""Unit tests for ``validate_output`` — the semantic guard on the final spec."""

from __future__ import annotations

import pytest
from _replay_helpers import load_plan

from app.api.errors import PipelineError
from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Citation,
    DataPoint,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphVizSpec,
    Measure,
    NodeType,
    Operation,
    PipelineStage,
    TidyDataset,
    VizType,
)
from app.transform import aggregate_time_trend, build_cooccurrence_network
from app.validation import validate_output
from app.viz import build_viz

_CATEGORICAL_PLAN = AnalysisPlan(
    operation=Operation.categorical_distribution,
    group_by=CategoricalField.phase,
    measure=Measure.trial_count,
    proposed_viz=VizType.bar_chart,
    interpretation="phase distribution",
)
_TIME_TREND_PLAN = load_plan("time_trend.json")
_NETWORK_PLAN = load_plan("cooccurrence_network.json")


def _bar_tidy(*, with_citations: bool = True) -> TidyDataset:
    citations = [Citation(nct_id="NCT01", excerpt="PHASE3")] if with_citations else []
    points = [
        DataPoint(dims={"phase": "PHASE3"}, measure="trial_count", value=5.0, citations=citations),
        DataPoint(dims={"phase": "PHASE2"}, measure="trial_count", value=3.0, citations=citations),
    ]
    return TidyDataset(points=points, dimension_names=["phase"], measure_name="trial_count")


def test_valid_chart_returns_no_hard_failure() -> None:
    tidy = _bar_tidy()
    spec = build_viz(tidy, _CATEGORICAL_PLAN)
    warnings = validate_output(spec, tidy)
    assert isinstance(warnings, list)


def test_chart_encoding_field_absent_raises() -> None:
    tidy = _bar_tidy()
    spec = build_viz(tidy, _CATEGORICAL_PLAN)
    bad_y = spec.encoding.y.model_copy(update={"field": "___nope___"})
    bad_spec = spec.model_copy(update={"encoding": spec.encoding.model_copy(update={"y": bad_y})})

    with pytest.raises(PipelineError) as exc_info:
        validate_output(bad_spec, tidy)
    assert exc_info.value.stage is PipelineStage.visualization
    assert exc_info.value.error_type == "encoding_field_absent"


def test_chart_missing_vega_values_raises() -> None:
    tidy = _bar_tidy()
    spec = build_viz(tidy, _CATEGORICAL_PLAN)
    bad_spec = spec.model_copy(update={"vega_spec": {"data": {}}})

    with pytest.raises(PipelineError) as exc_info:
        validate_output(bad_spec, tidy)
    assert exc_info.value.error_type == "vega_values_missing"


def test_chart_missing_citations_is_soft_warning() -> None:
    tidy = _bar_tidy(with_citations=False)
    spec = build_viz(tidy, _CATEGORICAL_PLAN)
    warnings = validate_output(spec, tidy)
    assert any("citation" in warning for warning in warnings)


def test_graph_dangling_edge_raises() -> None:
    graph = GraphData(
        nodes=[GraphNode(id="drug:a", label="A", type=NodeType.drug, weight=1.0)],
        edges=[GraphEdge(source="drug:a", target="sponsor:ghost", weight=1.0)],
    )
    spec = GraphVizSpec(title="net", data=graph, layout="force")

    with pytest.raises(PipelineError) as exc_info:
        validate_output(spec, graph)
    assert exc_info.value.error_type == "dangling_edge"


def test_empty_with_warning_passes() -> None:
    tidy = aggregate_time_trend([], _TIME_TREND_PLAN)
    assert tidy.warnings  # transform explained the emptiness
    spec = build_viz(tidy, _TIME_TREND_PLAN)
    assert validate_output(spec, tidy) == []

    graph = build_cooccurrence_network([], _NETWORK_PLAN)
    assert graph.warnings
    graph_spec = build_viz(graph, _NETWORK_PLAN)
    assert validate_output(graph_spec, graph) == []


def test_empty_without_warning_raises() -> None:
    tidy = TidyDataset(points=[], dimension_names=["year"], measure_name="trial_count", warnings=[])
    spec = build_viz(tidy, _TIME_TREND_PLAN)

    with pytest.raises(PipelineError) as exc_info:
        validate_output(spec, tidy)
    assert exc_info.value.error_type == "silent_empty_result"
