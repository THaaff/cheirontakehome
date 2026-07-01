"""Network builder: layout flag and citation preservation."""

from __future__ import annotations

from conftest import NETWORK_CASE, load_graph, load_plan
from pydantic import TypeAdapter

from app.contracts import GraphVizSpec, Renderer, VizSpec, VizType
from app.viz import build_viz

_VIZ_ADAPTER = TypeAdapter(VizSpec)
_TIDY_NAME, _PLAN_NAME = NETWORK_CASE


def test_network_validates_and_is_precomputed() -> None:
    graph = load_graph(_TIDY_NAME)
    spec = build_viz(graph, load_plan(_PLAN_NAME))
    assert isinstance(spec, GraphVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.kind == "graph"
    assert spec.renderer is Renderer.graph
    assert spec.type is VizType.network_graph
    # Every node in the fixture carries x/y -> precomputed.
    assert spec.layout == "precomputed"


def test_node_and_edge_citations_preserved() -> None:
    graph = load_graph(_TIDY_NAME)
    spec = build_viz(graph, load_plan(_PLAN_NAME))
    assert isinstance(spec, GraphVizSpec)

    src_node_cits = {c.nct_id for n in graph.nodes for c in n.citations}
    out_node_cits = {c.nct_id for n in spec.data.nodes for c in n.citations}
    assert out_node_cits == src_node_cits

    src_edge_cits = {c.nct_id for e in graph.edges for c in e.citations}
    out_edge_cits = {c.nct_id for e in spec.data.edges for c in e.citations}
    assert out_edge_cits == src_edge_cits


def test_missing_coordinates_fall_back_to_force_layout() -> None:
    graph = load_graph(_TIDY_NAME)
    # Drop one node's coordinates -> not a complete precomputed layout.
    graph.nodes[0].x = None
    graph.nodes[0].y = None
    spec = build_viz(graph, load_plan(_PLAN_NAME))
    assert isinstance(spec, GraphVizSpec)
    assert spec.layout == "force"
