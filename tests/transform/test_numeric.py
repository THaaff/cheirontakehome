"""numeric_distribution + numeric_relationship: binning, skips, contiguity."""

from __future__ import annotations

from app.contracts import AnalysisPlan, NumericField, Operation, StudyRecord
from app.transform import aggregate_numeric_distribution, aggregate_numeric_relationship


def _hist_plan(numeric: NumericField) -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.numeric_distribution,
        numeric_x=numeric,
        proposed_viz="histogram",
        interpretation="distribution",
    )


def test_enrollment_histogram_is_contiguous_and_counts_every_study(
    studies: list[StudyRecord],
) -> None:
    dataset = aggregate_numeric_distribution(studies, _hist_plan(NumericField.enrollment_count))
    assert dataset.dimension_names == ["bin_start", "bin_end"]
    # Bins tile the range with no gaps: each bin_end is the next bin_start.
    for prev, nxt in zip(dataset.points, dataset.points[1:], strict=False):
        assert prev.dims["bin_end"] == nxt.dims["bin_start"]
    # Every study has an enrollment_count, so all 10 land in some bin.
    assert int(sum(p.value for p in dataset.points)) == len(studies)
    assert not dataset.warnings


def test_duration_days_skips_records_missing_completion(studies: list[StudyRecord]) -> None:
    dataset = aggregate_numeric_distribution(studies, _hist_plan(NumericField.duration_days))
    # Only 5 studies have both a start and a completion date.
    assert int(sum(p.value for p in dataset.points)) == 5
    assert dataset.warnings and "5 study" in dataset.warnings[0]


def test_histogram_empty_input_is_safe() -> None:
    dataset = aggregate_numeric_distribution([], _hist_plan(NumericField.enrollment_count))
    assert dataset.points == []
    assert dataset.warnings


def test_numeric_relationship_one_point_per_complete_study(
    studies: list[StudyRecord],
) -> None:
    plan = AnalysisPlan(
        operation=Operation.numeric_relationship,
        numeric_x=NumericField.enrollment_count,
        numeric_y=NumericField.duration_days,
        proposed_viz="scatter_plot",
        interpretation="enrollment vs duration",
    )
    dataset = aggregate_numeric_relationship(studies, plan)
    # One point per study with both numerics (5 have a duration); value is always 1.
    assert len(dataset.points) == 5
    assert all(p.value == 1.0 for p in dataset.points)
    assert all("nct_id" in p.dims for p in dataset.points)
    assert dataset.measure_name == "study"
