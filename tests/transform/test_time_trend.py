"""time_trend: date exclusion + warning, zero-fill, year-range filter, granularity."""

from __future__ import annotations

from app.contracts import AnalysisPlan, Filters, Operation, StudyRecord
from app.transform import aggregate_time_trend


def _plan(*, start_year: int | None = None, granularity: str = "year") -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.time_trend,
        filters=Filters(start_year=start_year),
        time_granularity=granularity,  # type: ignore[arg-type]
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
