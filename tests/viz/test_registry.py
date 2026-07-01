"""Registry coverage and operation-driven (not proposed_viz-driven) dispatch."""

from __future__ import annotations

from conftest import load_plan, load_tidy

from app.contracts import ChartVizSpec, Operation, VizType
from app.viz import OPERATION_TO_VIZ, VIZ_BUILDERS, build_viz, viz_type_for


def test_every_operation_maps_to_a_viz_type() -> None:
    assert set(OPERATION_TO_VIZ) == set(Operation)


def test_every_viz_type_has_a_builder() -> None:
    assert set(VIZ_BUILDERS) == set(VizType)


def test_viz_type_is_derived_from_operation_not_proposed_viz() -> None:
    # A deliberately wrong proposed_viz must not change the dispatched type.
    plan = load_plan("categorical_distribution.json").model_copy(
        update={"proposed_viz": VizType.scatter_plot}
    )
    assert plan.proposed_viz is VizType.scatter_plot
    assert viz_type_for(plan) is VizType.bar_chart

    spec = build_viz(load_tidy("bar.json"), plan)
    assert isinstance(spec, ChartVizSpec)
    assert spec.type is VizType.bar_chart
