"""VizSpec discriminated-union resolution (PRD Section K)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts import ChartVizSpec, GraphVizSpec, Renderer, VizSpec, VizType

_ADAPTER: TypeAdapter[VizSpec] = TypeAdapter(VizSpec)

_CHART_DICT = {
    "kind": "chart",
    "renderer": "vega-lite",
    "type": "bar_chart",
    "title": "Phases",
    "encoding": {
        "x": {"field": "phase", "type": "nominal"},
        "y": {"field": "trial_count", "type": "quantitative"},
    },
    "data": [{"phase": "PHASE3", "trial_count": 78, "citations": []}],
    "vega_spec": {"mark": "bar"},
}

_GRAPH_DICT = {
    "kind": "graph",
    "title": "Network",
    "data": {
        "nodes": [{"id": "drug:p", "label": "Pembrolizumab", "type": "drug", "weight": 5.0}],
        "edges": [{"source": "drug:p", "target": "sponsor:m", "weight": 3.0}],
    },
    "layout": "force",
}


def test_chart_dict_resolves_to_chart() -> None:
    spec = _ADAPTER.validate_python(_CHART_DICT)
    assert isinstance(spec, ChartVizSpec)
    assert spec.renderer is Renderer.vega_lite


def test_graph_dict_resolves_to_graph() -> None:
    spec = _ADAPTER.validate_python(_GRAPH_DICT)
    assert isinstance(spec, GraphVizSpec)
    assert spec.renderer is Renderer.graph
    assert spec.type is VizType.network_graph


def test_graph_defaults_fill_renderer_type_and_encoding() -> None:
    spec = _ADAPTER.validate_python(_GRAPH_DICT)
    assert isinstance(spec, GraphVizSpec)
    # GraphEncoding defaults applied.
    assert spec.encoding.node_id == "id"
    assert spec.encoding.edge_weight == "weight"


def test_missing_discriminator_raises() -> None:
    bad = dict(_CHART_DICT)
    del bad["kind"]
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(bad)


def test_unknown_discriminator_raises() -> None:
    bad = dict(_CHART_DICT)
    bad["kind"] = "scatter"
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(bad)


def test_union_roundtrips_through_json() -> None:
    spec = _ADAPTER.validate_python(_CHART_DICT)
    dumped = _ADAPTER.dump_json(spec)
    reparsed = _ADAPTER.validate_json(dumped)
    assert reparsed == spec
