"""``AnalysisPlan`` -> CT.gov ``/studies`` query params, plus client-side filters.

Filter-locus rule (system robustness): push server-side only the params confirmed
to work cleanly on ``GET /studies``. Confirmed against the live v2 API:

* ``query.*`` and ``filter.overallStatus`` (the latter takes a comma- or
  pipe-separated OR list; we use comma).
* **Phase** is pushed server-side via ``aggFilters=phase:<codes>``. The live API
  has **no** ``filter.phase`` parameter (it returns HTTP 400 ``"filter.phase is
  unknown parameter"`` even for a known-good value), but ``aggFilters`` accepts a
  space-separated OR list of numeric phase codes that exactly mirrors
  ``filter.advanced=AREA[Phase]<token>`` counts (verified for all six phases).
  Pushing phase server-side spends the ``max_studies`` budget only on relevant
  trials instead of fetching-and-discarding.

``study_type`` and ``countries`` remain client-side post-filters on the parsed
:class:`StudyRecord` (the live API has no ``filter.studyType``; an ``aggFilters``
study-type facet exists but is left for a follow-up). ``start_year``/``end_year``
are deferred to the transform stage (which parses dates anyway).
"""

from __future__ import annotations

from app.contracts import AnalysisPlan, Filters, Phase, StudyRecord
from app.retrieval.warnings import WarningsCollector

# aggFilters phase codes. Verified live: each code's countTotal equals
# filter.advanced=AREA[Phase]<token>, and a space-separated list is server-side OR.
_PHASE_AGG_CODE: dict[Phase, str] = {
    Phase.EARLY_PHASE1: "0",
    Phase.PHASE1: "1",
    Phase.PHASE2: "2",
    Phase.PHASE3: "3",
    Phase.PHASE4: "4",
    Phase.NA: "NA",
}

# Projection pushdown: request only the fields the downstream needs. Casing is
# confirmed against fixtures/raw/notes.md and the live API.
SERVER_FIELDS: list[str] = [
    "NCTId",
    "BriefTitle",
    "Phase",
    "OverallStatus",
    "StudyType",
    "LeadSponsorName",
    "LeadSponsorClass",
    "StartDate",
    "PrimaryCompletionDate",
    "InterventionType",
    "InterventionName",
    "Condition",
    "LocationCountry",
    "EnrollmentCount",
]


def build_server_params(plan: AnalysisPlan) -> dict[str, str]:
    """Build the stable server-side query params (excluding paging cursors)."""
    params: dict[str, str] = {"format": "json", "fields": ",".join(SERVER_FIELDS)}

    entities = plan.entities
    if entities.drug:
        params["query.intr"] = entities.drug
    if entities.condition:
        params["query.cond"] = entities.condition
    if entities.sponsor:
        params["query.spons"] = entities.sponsor
    if entities.terms:
        params["query.term"] = " ".join(entities.terms)

    if plan.filters.statuses:
        # Sorted so the param (and therefore the cache key) is order-independent.
        params["filter.overallStatus"] = ",".join(sorted(s.value for s in plan.filters.statuses))

    phase_facet = _phase_aggfilter(plan.filters.phases)
    if phase_facet is not None:
        params["aggFilters"] = phase_facet

    return params


def _phase_aggfilter(phases: list[Phase]) -> str | None:
    """Return the ``aggFilters`` phase facet, or ``None`` to keep phase client-side.

    Returns ``None`` when no phases are requested, or (defensively) when the set
    contains a phase with no known aggFilters code — in which case the *whole*
    phase filter stays client-side so the OR semantics can't silently drop
    matching trials. Codes are sorted so the param (and cache key) is stable.
    """
    if not phases:
        return None
    if any(phase not in _PHASE_AGG_CODE for phase in phases):
        return None
    codes = sorted({_PHASE_AGG_CODE[phase] for phase in phases})
    return "phase:" + " ".join(codes)


def residual_client_filters(plan: AnalysisPlan) -> Filters:
    """The filters still to apply client-side after server-side pushdown.

    Phase is dropped here exactly when :func:`build_server_params` pushed it via
    ``aggFilters`` (both consult :func:`_phase_aggfilter`, so they can't drift).
    """
    if _phase_aggfilter(plan.filters.phases) is not None:
        return plan.filters.model_copy(update={"phases": []})
    return plan.filters


def apply_client_filters(
    records: list[StudyRecord], filters: Filters, warnings: WarningsCollector
) -> list[StudyRecord]:
    """Apply the post-fetch filters that have no clean server-side param.

    Each filter that actually drops at least one record adds a single
    de-duplicated warning. Year filters are intentionally not applied here.
    """
    result = records

    if filters.phases:
        wanted = set(filters.phases)
        kept = [r for r in result if wanted.intersection(r.phases)]
        _warn_if_dropped(warnings, "phase", len(result), len(kept))
        result = kept

    if filters.study_type is not None:
        kept = [r for r in result if r.study_type == filters.study_type]
        _warn_if_dropped(warnings, "study-type", len(result), len(kept))
        result = kept

    if filters.countries:
        wanted_countries = {c.casefold() for c in filters.countries}
        kept = [
            r
            for r in result
            if wanted_countries.intersection({c.casefold() for c in r.countries})
        ]
        _warn_if_dropped(warnings, "country", len(result), len(kept))
        result = kept

    return result


def _warn_if_dropped(warnings: WarningsCollector, name: str, before: int, after: int) -> None:
    if after < before:
        warnings.add(
            f"Applied {name} filter client-side: dropped {before - after} of "
            f"{before} fetched studies."
        )
