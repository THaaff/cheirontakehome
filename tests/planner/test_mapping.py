"""PlannerOutput -> AnalysisPlan mapping (where all contract validators run)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Entities,
    Filters,
    Measure,
    NumericField,
    Operation,
    VizType,
)
from app.planner.client import _map_to_plan
from app.planner.schema import PlannerOutput

from .conftest import (
    comparison_output,
    invalid_comparison_output,
    network_output,
    numeric_distribution_output,
    time_trend_output,
)


def test_each_operation_maps_to_analysis_plan() -> None:
    for output in (
        time_trend_output(),
        comparison_output(),
        network_output(),
        numeric_distribution_output(),
    ):
        plan = _map_to_plan(output)
        assert isinstance(plan, AnalysisPlan)
        assert plan.operation is output.operation


def test_omitted_defaults_fall_back_to_ir_defaults() -> None:
    """`time_granularity`/`measure` omitted by the model -> AnalysisPlan defaults."""
    output = PlannerOutput(
        operation=Operation.categorical_distribution,
        entities=Entities(condition="melanoma"),
        filters=Filters(),
        group_by=CategoricalField.phase,
        time_granularity=None,
        measure=None,
        proposed_viz=VizType.bar_chart,
        interpretation="Distribution of melanoma trials across phases.",
        assumptions=[],
    )
    plan = _map_to_plan(output)
    assert plan.time_granularity == "year"
    assert plan.measure is Measure.trial_count


def test_invalid_comparison_raises_validation_error() -> None:
    """A comparison without `series` is a valid PlannerOutput but an invalid plan."""
    with pytest.raises(ValidationError):
        _map_to_plan(invalid_comparison_output())


def test_series_min_length_enforced_on_mapping() -> None:
    """The min-length-2 constraint lives on SeriesSpec and runs during mapping."""
    from app.planner.schema import PlannerSeries

    output = comparison_output()
    output.series = PlannerSeries(dimension=output.series.dimension, values=["melanoma"])  # type: ignore[union-attr]
    with pytest.raises(ValidationError):
        _map_to_plan(output)


# --- Acceptance criteria (mapped-plan level) -------------------------------


def test_acceptance_time_trend_extraction() -> None:
    plan = _map_to_plan(time_trend_output())
    assert plan.operation is Operation.time_trend
    assert plan.entities.drug is not None and "pembrolizumab" in plan.entities.drug.lower()
    assert plan.filters.start_year == 2018


def test_acceptance_comparison_extraction() -> None:
    plan = _map_to_plan(comparison_output())
    assert plan.operation is Operation.comparison
    assert plan.group_by is CategoricalField.lead_sponsor_class
    assert plan.series is not None
    values = {v.lower() for v in plan.series.values}
    assert {"melanoma", "lung cancer"} <= values


def test_numeric_distribution_carries_numeric_x() -> None:
    plan = _map_to_plan(numeric_distribution_output())
    assert plan.numeric_x is NumericField.enrollment_count
    assert plan.numeric_y is None
