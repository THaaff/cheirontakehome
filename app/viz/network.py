"""Network builder: GraphData + AnalysisPlan -> GraphVizSpec.

A network graph cannot be expressed in Vega-Lite, so we emit our own
node/edge spec (:class:`~app.contracts.viz.GraphVizSpec`) that a frontend
renders with a force-directed library (d3-force, cytoscape, ...). The builder is
a near pass-through: the transform layer already produced the nodes/edges (and
optionally a precomputed ``spring_layout``); we attach the fixed
:class:`~app.contracts.viz.GraphEncoding`, decide the ``layout`` flag, and carry
every node/edge citation through unchanged.
"""

from __future__ import annotations

from typing import Literal

from app.contracts import (
    AnalysisPlan,
    GraphData,
    GraphEncoding,
    GraphVizSpec,
    VizHints,
    VizType,
)

from .charts import build_title


def _has_precomputed_layout(data: GraphData) -> bool:
    """True iff every node carries both x and y coordinates."""
    return bool(data.nodes) and all(n.x is not None and n.y is not None for n in data.nodes)


def build_network(data: object, plan: AnalysisPlan) -> GraphVizSpec:
    """Co-occurrence network -> GraphVizSpec with the correct layout flag."""
    if not isinstance(data, GraphData):
        raise TypeError(f"the network builder requires GraphData, got {type(data).__name__}")

    layout: Literal["precomputed", "force"] = (
        "precomputed" if _has_precomputed_layout(data) else "force"
    )
    title = build_title(plan, VizType.network_graph)
    hints = VizHints(
        units="trials",
        note="Node size encodes trial participation; edge weight encodes co-occurrence count.",
    )
    return GraphVizSpec(
        title=title,
        encoding=GraphEncoding(),
        data=data,
        layout=layout,
        hints=hints,
    )
