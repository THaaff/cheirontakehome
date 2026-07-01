"""The viz registry and the single ``build_viz`` entrypoint.

The registry is a dispatch table keyed by :class:`~app.contracts.enums.VizType`:
adding a chart type is one entry, not a pipeline change (system-design.md §4/§6).
``build_viz`` derives the **authoritative** viz type from ``plan.operation`` (the
closed operation→viz matrix); ``plan.proposed_viz`` is advisory and never used
for dispatch.
"""

from __future__ import annotations

from collections.abc import Callable

from app.contracts import (
    AnalysisPlan,
    GraphData,
    Operation,
    TidyDataset,
    VizSpec,
    VizType,
)

from .charts import (
    build_bar_chart,
    build_choropleth,
    build_grouped_bar_chart,
    build_histogram,
    build_scatter_plot,
    build_time_series,
)
from .network import build_network

# Either a tidy (chart) dataset or graph (network) data crosses into a builder.
VizInput = TidyDataset | GraphData
VizBuilder = Callable[[VizInput, AnalysisPlan], VizSpec]

# The authoritative operation -> viz type matrix (PRD Section A / system-design §8).
OPERATION_TO_VIZ: dict[Operation, VizType] = {
    Operation.time_trend: VizType.time_series,
    Operation.categorical_distribution: VizType.bar_chart,
    Operation.comparison: VizType.grouped_bar_chart,
    Operation.geographic_distribution: VizType.choropleth_map,
    Operation.cooccurrence_network: VizType.network_graph,
    Operation.numeric_distribution: VizType.histogram,
    Operation.numeric_relationship: VizType.scatter_plot,
}

# One builder per viz type. Builders accept the broad VizInput and narrow it
# internally (chart builders require a TidyDataset, the network builder GraphData).
VIZ_BUILDERS: dict[VizType, VizBuilder] = {
    VizType.bar_chart: build_bar_chart,
    VizType.grouped_bar_chart: build_grouped_bar_chart,
    VizType.time_series: build_time_series,
    VizType.histogram: build_histogram,
    VizType.scatter_plot: build_scatter_plot,
    VizType.choropleth_map: build_choropleth,
    VizType.network_graph: build_network,
}


def viz_type_for(plan: AnalysisPlan) -> VizType:
    """The authoritative viz type for a plan, derived from its operation."""
    try:
        return OPERATION_TO_VIZ[plan.operation]
    except KeyError as exc:  # pragma: no cover - every Operation is mapped above
        raise ValueError(f"no viz type mapped for operation {plan.operation!r}") from exc


def build_viz(data: VizInput, plan: AnalysisPlan) -> VizSpec:
    """Build a renderer-ready :class:`VizSpec` from tidy/graph data and a plan."""
    viz_type = viz_type_for(plan)
    try:
        builder = VIZ_BUILDERS[viz_type]
    except KeyError as exc:  # pragma: no cover - every VizType has a builder above
        raise ValueError(f"no builder registered for viz type {viz_type!r}") from exc
    return builder(data, plan)
