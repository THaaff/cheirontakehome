"""geographic_distribution: country multi-count across a trial's countries."""

from __future__ import annotations

from app.contracts import AnalysisPlan, CategoricalField, Operation, StudyRecord
from app.transform import aggregate_geographic


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.geographic_distribution,
        group_by=CategoricalField.country,
        proposed_viz="choropleth_map",
        interpretation="trials by country",
    )


def test_country_counts_and_multi_count(studies: list[StudyRecord]) -> None:
    dataset = aggregate_geographic(studies, _plan())
    counts = {str(p.dims["country"]): int(p.value) for p in dataset.points}
    assert counts["United States"] == 6

    def ncts(country: str) -> set[str]:
        point = next(p for p in dataset.points if p.dims["country"] == country)
        return {c.nct_id for c in point.citations}

    # NCT02009449 is US + Canada; NCT03684785 is US + Australia. Each multi-counts.
    assert "NCT02009449" in ncts("United States") and "NCT02009449" in ncts("Canada")
    assert "NCT03684785" in ncts("United States") and "NCT03684785" in ncts("Australia")
    # Raw country names are preserved (no ISO mapping in the transform layer).
    assert "Korea, Republic of" in counts


def test_empty_input_is_safe() -> None:
    dataset = aggregate_geographic([], _plan())
    assert dataset.points == []
    assert dataset.warnings
