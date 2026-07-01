"""query_builder: server-param mapping (filter-locus rule) and client filters."""

from __future__ import annotations

from app.contracts import (
    AnalysisPlan,
    Entities,
    Filters,
    OverallStatus,
    Phase,
    StudyRecord,
    StudyType,
)
from app.retrieval.query_builder import (
    SERVER_FIELDS,
    apply_client_filters,
    build_server_params,
    residual_client_filters,
)
from app.retrieval.warnings import WarningsCollector


def _plan(**kwargs: object) -> AnalysisPlan:
    base: dict[str, object] = {
        "operation": "time_trend",
        "proposed_viz": "time_series",
        "interpretation": "x",
    }
    base.update(kwargs)
    return AnalysisPlan.model_validate(base)


def test_entities_map_to_query_params() -> None:
    params = build_server_params(
        _plan(entities=Entities(drug="pembrolizumab", condition="melanoma", sponsor="Merck"))
    )
    assert params["query.intr"] == "pembrolizumab"
    assert params["query.cond"] == "melanoma"
    assert params["query.spons"] == "Merck"
    assert params["format"] == "json"
    assert params["fields"] == ",".join(SERVER_FIELDS)


def test_terms_are_space_joined() -> None:
    params = build_server_params(_plan(entities=Entities(terms=["immunotherapy", "vaccine"])))
    assert params["query.term"] == "immunotherapy vaccine"


def test_statuses_map_to_sorted_comma_list() -> None:
    params = build_server_params(
        _plan(filters=Filters(statuses=[OverallStatus.RECRUITING, OverallStatus.COMPLETED]))
    )
    # Sorted so the cache key is order-independent.
    assert params["filter.overallStatus"] == "COMPLETED,RECRUITING"


def test_invalid_filter_params_are_never_emitted() -> None:
    """filter.phase / filter.studyType do not exist in CT.gov v2 (HTTP 400)."""
    params = build_server_params(
        _plan(filters=Filters(phases=[Phase.PHASE3], study_type=StudyType.INTERVENTIONAL))
    )
    assert "filter.phase" not in params
    assert "filter.studyType" not in params


def test_phase_is_pushed_via_aggfilters() -> None:
    params = build_server_params(_plan(filters=Filters(phases=[Phase.PHASE3])))
    assert params["aggFilters"] == "phase:3"


def test_multiple_phases_are_space_joined_or_and_sorted() -> None:
    """Space-separated codes = server-side OR; sorted for a stable cache key."""
    params = build_server_params(_plan(filters=Filters(phases=[Phase.PHASE3, Phase.PHASE2])))
    assert params["aggFilters"] == "phase:2 3"


def test_early_phase1_and_na_have_aggfilter_codes() -> None:
    params = build_server_params(_plan(filters=Filters(phases=[Phase.NA, Phase.EARLY_PHASE1])))
    assert params["aggFilters"] == "phase:0 NA"


def test_no_aggfilters_when_no_phases() -> None:
    params = build_server_params(_plan(entities=Entities(drug="pembrolizumab")))
    assert "aggFilters" not in params


def test_study_type_is_not_pushed_to_aggfilters() -> None:
    params = build_server_params(_plan(filters=Filters(study_type=StudyType.INTERVENTIONAL)))
    assert "aggFilters" not in params  # study_type stays client-side


def test_residual_filters_drop_pushed_phase_keep_the_rest() -> None:
    plan = _plan(
        filters=Filters(
            phases=[Phase.PHASE3],
            study_type=StudyType.INTERVENTIONAL,
            countries=["United States"],
        )
    )
    residual = residual_client_filters(plan)
    assert residual.phases == []  # pushed server-side, so not re-filtered client-side
    assert residual.study_type is StudyType.INTERVENTIONAL
    assert residual.countries == ["United States"]


def test_residual_filters_unchanged_when_no_phase_pushdown() -> None:
    plan = _plan(filters=Filters(study_type=StudyType.OBSERVATIONAL))
    residual = residual_client_filters(plan)
    assert residual is plan.filters  # nothing pushed -> returned as-is, no copy


def _record(nct_id: str, **kwargs: object) -> StudyRecord:
    return StudyRecord(nct_id=nct_id, **kwargs)  # type: ignore[arg-type]


def test_client_filter_phases() -> None:
    warnings = WarningsCollector()
    records = [
        _record("NCT1", phases=[Phase.PHASE3]),
        _record("NCT2", phases=[Phase.PHASE1]),
        _record("NCT3", phases=[]),
    ]
    kept = apply_client_filters(records, Filters(phases=[Phase.PHASE3]), warnings)
    assert [r.nct_id for r in kept] == ["NCT1"]
    assert any("phase filter" in w for w in warnings.list())


def test_client_filter_study_type_and_country_casefold() -> None:
    warnings = WarningsCollector()
    records = [
        _record("NCT1", study_type=StudyType.INTERVENTIONAL, countries=["United States"]),
        _record("NCT2", study_type=StudyType.OBSERVATIONAL, countries=["France"]),
    ]
    kept = apply_client_filters(
        records,
        Filters(study_type=StudyType.INTERVENTIONAL, countries=["united states"]),
        warnings,
    )
    assert [r.nct_id for r in kept] == ["NCT1"]


def test_client_filter_no_warning_when_nothing_dropped() -> None:
    warnings = WarningsCollector()
    records = [_record("NCT1", phases=[Phase.PHASE2])]
    kept = apply_client_filters(records, Filters(phases=[Phase.PHASE2]), warnings)
    assert [r.nct_id for r in kept] == ["NCT1"]
    assert warnings.list() == []


def test_year_filters_are_not_applied_client_side() -> None:
    warnings = WarningsCollector()
    records = [_record("NCT1"), _record("NCT2")]
    kept = apply_client_filters(records, Filters(start_year=2030, end_year=2031), warnings)
    assert len(kept) == 2  # deferred to transform
    assert warnings.list() == []
