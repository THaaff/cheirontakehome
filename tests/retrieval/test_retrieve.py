"""End-to-end retrieve() over a fake transport (offline mirror of live smoke)."""

from __future__ import annotations

from pathlib import Path

from _helpers import FakeCTGov, drug_plan, execute, load_raw, split_into_pages

from app.contracts import (
    AnalysisPlan,
    Entities,
    Filters,
    Phase,
    RequestOptions,
    RetrievalResult,
    Settings,
    StudyRecord,
)


def test_drug_query_returns_valid_non_empty_result(tmp_path: Path) -> None:
    """Mirror of the live acceptance criterion for a drug query, fully offline."""
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_pembrolizumab.json"), 25))
    result = execute(fake, drug_plan(), Settings(cache_dir=str(tmp_path)), RequestOptions())

    assert isinstance(result, RetrievalResult)
    assert result.studies  # non-empty
    assert all(isinstance(s, StudyRecord) for s in result.studies)
    assert result.studies_analyzed == len(result.studies)
    assert result.total_matched == 2892
    assert result.data_timestamp == "2026-06-30T09:00:05"
    # Re-validates against the frozen contract (full round-trip).
    RetrievalResult.model_validate(result.model_dump())
    assert fake.studies_requests[0].get("query.intr") == "pembrolizumab"


def test_condition_query(tmp_path: Path) -> None:
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_melanoma.json"), 25))
    plan = AnalysisPlan(
        operation="categorical_distribution",  # type: ignore[arg-type]
        group_by="phase",  # type: ignore[arg-type]
        entities=Entities(condition="melanoma"),
        proposed_viz="bar_chart",  # type: ignore[arg-type]
        interpretation="phase distribution for melanoma",
    )
    result = execute(fake, plan, Settings(cache_dir=str(tmp_path)), RequestOptions())

    assert result.studies
    assert result.total_matched == 3723
    assert fake.studies_requests[0].get("query.cond") == "melanoma"


def test_phase_filter_is_pushed_server_side(tmp_path: Path) -> None:
    """A phase filter goes out as aggFilters; no client-side phase drop happens."""
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_melanoma.json"), 25))
    plan = AnalysisPlan(
        operation="categorical_distribution",  # type: ignore[arg-type]
        group_by="phase",  # type: ignore[arg-type]
        entities=Entities(condition="melanoma"),
        filters=Filters(phases=[Phase.PHASE2, Phase.PHASE3]),
        proposed_viz="bar_chart",  # type: ignore[arg-type]
        interpretation="phase 2/3 melanoma trials",
    )
    result = execute(fake, plan, Settings(cache_dir=str(tmp_path)), RequestOptions())

    assert fake.studies_requests[0]["aggFilters"] == "phase:2 3"
    assert "filter.phase" not in fake.studies_requests[0]
    # Phase was filtered server-side, so no client-side "phase filter ... dropped" warning.
    assert not any("phase filter" in w for w in result.warnings)
