"""time_trend: date exclusion + warning, zero-fill, year-range filter, granularity."""

from __future__ import annotations

from app.contracts import AnalysisPlan, CategoricalField, Filters, Operation, StudyRecord
from app.transform import aggregate_time_trend


def _plan(
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    granularity: str = "year",
    group_by: CategoricalField | None = None,
) -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.time_trend,
        filters=Filters(start_year=start_year, end_year=end_year),
        time_granularity=granularity,  # type: ignore[arg-type]
        group_by=group_by,
        proposed_viz="time_series",
        interpretation="annual trial count",
    )


def test_unparseable_date_excluded_and_warned(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan())
    # NCT03666325 has start_date None (raw "Fall 2018") -> excluded.
    assert len(dataset.warnings) == 1
    assert "1 study" in dataset.warnings[0]
    cited = {c.nct_id for p in dataset.points for c in p.citations}
    assert "NCT03666325" not in cited


def test_year_buckets_have_no_gaps(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan())
    years = [int(p.dims["year"]) for p in dataset.points]
    assert years == list(range(min(years), max(years) + 1))
    assert years[0] == 2013 and years[-1] == 2026


def test_count_for_2018(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan())
    by_year = {int(p.dims["year"]): int(p.value) for p in dataset.points}
    assert by_year[2018] == 3
    assert by_year[2014] == 0  # zero-filled period


def test_year_range_filter(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan(start_year=2018))
    years = [int(p.dims["year"]) for p in dataset.points]
    assert min(years) == 2018  # 2013 and 2017 filtered out
    assert all(y >= 2018 for y in years)


def test_citation_excerpt_is_raw_date(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan())
    point_2018 = next(p for p in dataset.points if p.dims["year"] == 2018)
    excerpts = {c.excerpt for c in point_2018.citations}
    # All three 2018 studies carry their raw start-date string as the excerpt.
    assert "2018-02-08" in excerpts
    assert all(c.field == "protocolSection.statusModule.startDateStruct.date"
               for c in point_2018.citations)


def test_month_granularity(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan(granularity="month"))
    assert dataset.dimension_names == ["period"]
    periods = [str(p.dims["period"]) for p in dataset.points]
    assert "2018-02" in periods  # NCT03240016 started 2018-02-08
    # YYYY-MM, lexicographically sorted and gap-free month-by-month.
    assert periods == sorted(periods)


def test_empty_input_is_safe() -> None:
    dataset = aggregate_time_trend([], _plan())
    assert dataset.points == []
    assert dataset.warnings


def test_end_year_excludes_future_periods(studies: list[StudyRecord]) -> None:
    # A trial dated 2026 must not appear once the range is bounded at 2025.
    dataset = aggregate_time_trend(studies, _plan(start_year=2018, end_year=2025))
    years = [int(p.dims["year"]) for p in dataset.points]
    assert max(years) == 2025
    assert 2026 not in years


def test_group_by_phase_makes_one_series_per_phase(studies: list[StudyRecord]) -> None:
    dataset = aggregate_time_trend(studies, _plan(group_by=CategoricalField.phase))
    assert dataset.dimension_names == ["year", "phase"]

    phases = sorted({str(p.dims["phase"]) for p in dataset.points})
    assert phases == ["PHASE1", "PHASE2", "PHASE3"]

    years = sorted({int(p.dims["year"]) for p in dataset.points})
    assert years == list(range(2013, 2027))  # zero-filled across the full range
    assert len(dataset.points) == len(phases) * len(years)  # every (phase, year) cell

    by = {(str(p.dims["phase"]), int(p.dims["year"])): int(p.value) for p in dataset.points}
    assert by[("PHASE2", 2018)] == 2  # NCT03240016 + NCT03684785 (multi-phase)
    assert by[("PHASE1", 2018)] == 1  # NCT03684785 also counts under PHASE1
    assert by[("PHASE3", 2025)] == 1
    assert by[("PHASE1", 2014)] == 0  # zero-filled gap

    # Zero-filled cells carry no citations; real cells cite their source trials.
    p2_2018 = next(
        p for p in dataset.points if p.dims["phase"] == "PHASE2" and p.dims["year"] == 2018
    )
    assert {c.nct_id for c in p2_2018.citations} == {"NCT03240016", "NCT03684785"}
