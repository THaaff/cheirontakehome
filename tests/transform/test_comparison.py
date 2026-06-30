"""comparison: per-series aggregation with the series tag on every point."""

from __future__ import annotations

from app.contracts import AnalysisPlan, CategoricalField, Operation, SeriesSpec, StudyRecord
from app.transform import aggregate_comparison


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.comparison,
        group_by=CategoricalField.lead_sponsor_class,
        series=SeriesSpec(dimension="condition", values=["group-a", "group-b"]),
        proposed_viz="grouped_bar_chart",
        interpretation="sponsor-class mix across two groups",
    )


def test_points_carry_series_and_counts_are_per_series(studies: list[StudyRecord]) -> None:
    series_studies = [("group-a", studies[:5]), ("group-b", studies[5:])]
    dataset = aggregate_comparison(series_studies, _plan())

    assert dataset.dimension_names == ["lead_sponsor_class", "series"]
    assert all("series" in p.dims for p in dataset.points)

    def counts(series: str) -> dict[str, int]:
        return {
            str(p.dims["lead_sponsor_class"]): int(p.value)
            for p in dataset.points
            if p.dims["series"] == series
        }

    # studies[:5] are all OTHER; studies[5:] are INDUSTRY x4 + NETWORK x1.
    assert counts("group-a") == {"OTHER": 5}
    assert counts("group-b") == {"INDUSTRY": 4, "NETWORK": 1}


def test_empty_series_list_is_safe() -> None:
    dataset = aggregate_comparison([], _plan())
    assert dataset.points == []
    assert dataset.warnings


def test_all_empty_series_warns() -> None:
    dataset = aggregate_comparison([("group-a", []), ("group-b", [])], _plan())
    assert dataset.points == []
    assert dataset.warnings
