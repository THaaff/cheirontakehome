"""Visualization spec models and the VizSpec discriminated union (PRD Section E).

The output carries two layers at once: a renderer-agnostic *semantic* encoding
(:class:`Encoding` / :class:`GraphEncoding`) and a concrete *embedded* spec
(``vega_spec`` for charts, node/edge :class:`~app.contracts.data.GraphData` for
graphs). The semantic layer is constant across renderers; the embedded spec is
what a frontend hands straight to ``vega-embed`` (or a graph renderer).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .data import ChartDatum, GraphData
from .enums import ChannelType, Renderer, VizType


class Channel(BaseModel):
    """A single encoding channel (semantic layer)."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="The data field this channel reads.")
    type: ChannelType = Field(description="nominal / ordinal / quantitative / temporal.")
    title: str | None = Field(default=None, description="Axis/legend title.")
    sort: str | list[str] | None = Field(default=None, description="Optional sort directive.")


class Encoding(BaseModel):
    """Chart semantic encoding (matches the assignment's `encoding`)."""

    model_config = ConfigDict(extra="forbid")

    x: Channel
    y: Channel
    color: Channel | None = Field(
        default=None, description="The series channel for grouped/comparison."
    )
    column: Channel | None = Field(default=None, description="Optional facet.")
    size: Channel | None = Field(default=None, description="Optional size channel.")


class GraphEncoding(BaseModel):
    """Documents the node/edge channel mapping (fixed fields with defaults)."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = "id"
    node_label: str = "label"
    node_group: str = "type"
    node_size: str = "weight"
    edge_source: str = "source"
    edge_target: str = "target"
    edge_weight: str = "weight"


class VizHints(BaseModel):
    """Free-form rendering hints for the frontend."""

    model_config = ConfigDict(extra="forbid")

    sort: str | None = Field(default=None, description="e.g. -y for descending bars.")
    x_time_unit: str | None = Field(default=None, description="e.g. year.")
    units: str | None = Field(default=None, description="e.g. trials.")
    note: str | None = Field(default=None, description="Free-text rendering hint.")


class ChartVizSpec(BaseModel):
    """A chart visualization (Vega-Lite / Vega)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["chart"] = "chart"
    renderer: Renderer = Field(description="vega-lite or vega.")
    type: VizType
    title: str
    encoding: Encoding
    data: list[ChartDatum]
    vega_spec: dict[str, Any] = Field(
        description="Concrete embedded spec with data inlined under data.values."
    )
    hints: VizHints = Field(default_factory=VizHints)


class GraphVizSpec(BaseModel):
    """A network-graph visualization (own node/edge spec)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["graph"] = "graph"
    renderer: Literal[Renderer.graph] = Renderer.graph
    type: Literal[VizType.network_graph] = VizType.network_graph
    title: str
    encoding: GraphEncoding = Field(default_factory=GraphEncoding)
    data: GraphData
    layout: Literal["precomputed", "force"] = Field(
        description="precomputed if x/y set on nodes, else force."
    )
    hints: VizHints = Field(default_factory=VizHints)


# Discriminated on `kind` (unique per member), NOT `renderer`: `renderer` has
# two values (vega-lite, vega) that both belong to ChartVizSpec, so it cannot be
# a unique discriminator. See docs/system-design.md §6 decision table.
VizSpec = Annotated[
    ChartVizSpec | GraphVizSpec,
    Field(discriminator="kind"),
]
