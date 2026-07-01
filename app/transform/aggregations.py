"""Pure, deterministic aggregation primitives (one per operation).

Each function turns clean :class:`StudyRecord`s plus an :class:`AnalysisPlan`
into a :class:`TidyDataset` whose every :class:`DataPoint` carries the NCT-id
provenance that produced it. There is no I/O, no network, and no model here —
this is where every number in the final visualization is actually computed, so
that the LLM never emits a count it could hallucinate.

Cross-cutting rules honored throughout:

* **Multi-count** for list-valued fields (``phase``, ``intervention_type``,
  ``country``, ``condition``): a study contributes once to *each distinct value*
  it carries (deduped per study, so ``["DRUG", "DRUG"]`` counts once for DRUG).
* **Exclusion with a warning** for records that cannot be placed (unparseable /
  missing dates in :func:`aggregate_time_trend`, missing numerics in the numeric
  operations).
* **Empty-input safety**: an empty (or fully-excluded) input yields an empty
  dataset plus a ``warning``, never an exception.
"""

from __future__ import annotations

import math
from datetime import date

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    DataPoint,
    NumericField,
    StudyRecord,
    TidyDataset,
)
from app.transform.provenance import (
    FIELD_CONDITIONS,
    FIELD_COUNTRY,
    FIELD_DURATION_DAYS,
    FIELD_ENROLLMENT,
    FIELD_INTERVENTION_TYPE,
    FIELD_LEAD_SPONSOR_CLASS,
    FIELD_OVERALL_STATUS,
    FIELD_PHASES,
    FIELD_START_DATE,
    FIELD_STUDY_TYPE,
    make_citation,
)

_MEASURE = "trial_count"

# Source field path for each categorical field's citations.
_FIELD_PATH: dict[CategoricalField, str] = {
    CategoricalField.phase: FIELD_PHASES,
    CategoricalField.overall_status: FIELD_OVERALL_STATUS,
    CategoricalField.study_type: FIELD_STUDY_TYPE,
    CategoricalField.lead_sponsor_class: FIELD_LEAD_SPONSOR_CLASS,
    CategoricalField.intervention_type: FIELD_INTERVENTION_TYPE,
    CategoricalField.country: FIELD_COUNTRY,
    CategoricalField.condition: FIELD_CONDITIONS,
}

# Which categorical fields are list-valued (multi-count) vs single scalars.
_LIST_FIELDS = frozenset(
    {
        CategoricalField.phase,
        CategoricalField.intervention_type,
        CategoricalField.country,
        CategoricalField.condition,
    }
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _distinct(values: list[str]) -> list[str]:
    """De-duplicate while preserving first-seen order."""

    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _field_values(study: StudyRecord, field: CategoricalField) -> list[str]:
    """Distinct values a study contributes for ``field`` (multi-count aware).

    List-valued fields return every distinct value (deduped per study); scalar
    fields return a one-element list, or an empty list when the value is absent.
    """

    if field is CategoricalField.phase:
        return _distinct([p.value for p in study.phases])
    if field is CategoricalField.intervention_type:
        return _distinct([t.value for t in study.intervention_types])
    if field is CategoricalField.country:
        return _distinct(study.countries)
    if field is CategoricalField.condition:
        return _distinct(study.conditions)
    if field is CategoricalField.overall_status:
        return [study.overall_status.value] if study.overall_status is not None else []
    if field is CategoricalField.study_type:
        return [study.study_type.value] if study.study_type is not None else []
    if field is CategoricalField.lead_sponsor_class:
        return (
            [study.lead_sponsor_class.value] if study.lead_sponsor_class is not None else []
        )
    raise AssertionError(f"unhandled categorical field: {field}")  # pragma: no cover


def _count_by_field(
    studies: list[StudyRecord], field: CategoricalField
) -> dict[str, list[StudyRecord]]:
    """Group studies into ``value -> [contributing studies]`` buckets."""

    buckets: dict[str, list[StudyRecord]] = {}
    for study in studies:
        for value in _field_values(study, field):
            buckets.setdefault(value, []).append(study)
    return buckets


def _sorted_by_value(points: list[DataPoint], dim_name: str) -> list[DataPoint]:
    """Deterministic order: value descending, then dimension key ascending.

    The viz layer is free to re-sort; we emit a stable order so output is
    reproducible and tests are not order-fragile.
    """

    return sorted(points, key=lambda p: (-p.value, str(p.dims.get(dim_name, ""))))


def _categorical_points(
    buckets: dict[str, list[StudyRecord]],
    group_name: str,
    field_path: str,
    *,
    extra_dims: dict[str, str | int | float] | None = None,
) -> list[DataPoint]:
    points: list[DataPoint] = []
    for value, contributors in buckets.items():
        dims: dict[str, str | int | float] = {group_name: value}
        if extra_dims:
            dims.update(extra_dims)
        citations = [make_citation(s, excerpt=value, field=field_path) for s in contributors]
        points.append(
            DataPoint(
                dims=dims,
                measure=_MEASURE,
                value=float(len(contributors)),
                citations=citations,
            )
        )
    return points


def _categorical_dataset(studies: list[StudyRecord], field: CategoricalField) -> TidyDataset:
    group_name = field.value
    if not studies:
        return TidyDataset(
            points=[],
            dimension_names=[group_name],
            measure_name=_MEASURE,
            warnings=[f"no studies to aggregate; empty {group_name} distribution"],
        )
    buckets = _count_by_field(studies, field)
    points = _sorted_by_value(
        _categorical_points(buckets, group_name, _FIELD_PATH[field]), group_name
    )
    warnings = [] if points else [f"no studies carried a {group_name} value; empty distribution"]
    return TidyDataset(
        points=points,
        dimension_names=[group_name],
        measure_name=_MEASURE,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# time_trend
# ---------------------------------------------------------------------------


def _period_key(d: date, granularity: str) -> int:
    """A monotonic integer key per period (so zero-fill is a plain range)."""

    if granularity == "month":
        return d.year * 12 + (d.month - 1)
    return d.year


def _period_dim_value(key: int, granularity: str) -> int | str:
    if granularity == "month":
        year, month = divmod(key, 12)
        return f"{year:04d}-{month + 1:02d}"
    return key


def _time_point(
    dim_name: str,
    granularity: str,
    key: int,
    members: list[StudyRecord],
    *,
    extra_dims: dict[str, str | int | float] | None = None,
) -> DataPoint:
    """One period bucket -> a :class:`DataPoint` with per-study date citations."""
    citations = [
        make_citation(
            s,
            excerpt=s.start_date_raw or (s.start_date.isoformat() if s.start_date else None),
            field=FIELD_START_DATE,
        )
        for s in members
    ]
    dims: dict[str, str | int | float] = {dim_name: _period_dim_value(key, granularity)}
    if extra_dims:
        dims.update(extra_dims)
    return DataPoint(
        dims=dims, measure=_MEASURE, value=float(len(members)), citations=citations
    )


def aggregate_time_trend(studies: list[StudyRecord], plan: AnalysisPlan) -> TidyDataset:
    """Bucket study start dates by year (default) or month into a trial-count series.

    When ``plan.group_by`` is set, the trend is split into one series per value of
    that categorical field (e.g. one line per phase) — the dataset gains a second
    dimension and every ``(period, group)`` cell is zero-filled so each line is
    gap-free. Otherwise a single count-per-period series is produced.

    Records with ``start_date is None`` are excluded and reported in a warning.
    The ``filters.start_year`` / ``end_year`` range is applied here (filtered-out
    records are dropped silently); the planner sets ``end_year`` for bounded or
    past-tense ranges so not-yet-started (future-dated) trials don't appear.
    """

    granularity = plan.time_granularity
    dim_name = "period" if granularity == "month" else "year"
    group_field = plan.group_by
    dim_names = [dim_name] if group_field is None else [dim_name, group_field.value]

    if not studies:
        return TidyDataset(
            points=[],
            dimension_names=dim_names,
            measure_name=_MEASURE,
            warnings=["no studies to aggregate; empty time trend"],
        )

    start_year = plan.filters.start_year
    end_year = plan.filters.end_year

    # Pass 1: keep studies with a usable, in-range start date (period key + study).
    in_range: list[tuple[int, StudyRecord]] = []
    excluded = 0
    for study in studies:
        d = study.start_date
        if d is None:
            excluded += 1
            continue
        if start_year is not None and d.year < start_year:
            continue
        if end_year is not None and d.year > end_year:
            continue
        in_range.append((_period_key(d, granularity), study))

    warnings: list[str] = []
    if excluded:
        warnings.append(
            f"{excluded} study(ies) had unparseable or missing start dates "
            f"and were excluded from the time trend"
        )

    if not in_range:
        warnings.append("no studies with a usable start date in range; empty time trend")
        return TidyDataset(
            points=[], dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
        )

    key_lo = min(k for k, _ in in_range)
    key_hi = max(k for k, _ in in_range)
    period_keys = range(key_lo, key_hi + 1)  # inclusive, zero-filled

    if group_field is None:
        contributors: dict[int, list[StudyRecord]] = {}
        for key, study in in_range:
            contributors.setdefault(key, []).append(study)
        points = [
            _time_point(dim_name, granularity, key, contributors.get(key, []))
            for key in period_keys
        ]
        return TidyDataset(
            points=points, dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
        )

    # Grouped: bucket by (period, group value); multi-count for list-valued fields.
    group_name = group_field.value
    grouped: dict[tuple[int, str], list[StudyRecord]] = {}
    group_values: list[str] = []
    seen: set[str] = set()
    for key, study in in_range:
        for value in _field_values(study, group_field):
            grouped.setdefault((key, value), []).append(study)
            if value not in seen:
                seen.add(value)
                group_values.append(value)
    group_values.sort()  # stable; the viz layer applies any domain ordering (e.g. phase)

    points = [
        _time_point(dim_name, granularity, key, grouped.get((key, value), []),
                    extra_dims={group_name: value})
        for value in group_values
        for key in period_keys
    ]
    return TidyDataset(
        points=points, dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
    )


# ---------------------------------------------------------------------------
# categorical_distribution / geographic_distribution
# ---------------------------------------------------------------------------


def aggregate_categorical(studies: list[StudyRecord], plan: AnalysisPlan) -> TidyDataset:
    """Group studies by ``plan.group_by`` into a trial-count distribution."""

    field = plan.group_by
    if field is None:
        raise ValueError("categorical_distribution requires plan.group_by")
    return _categorical_dataset(studies, field)


def aggregate_geographic(studies: list[StudyRecord], plan: AnalysisPlan) -> TidyDataset:
    """Group studies by country (multi-count across a trial's countries).

    Raw country names are preserved; ISO mapping for a choropleth is the viz
    layer's concern.
    """

    return _categorical_dataset(studies, CategoricalField.country)


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def aggregate_comparison(
    series_studies: list[tuple[str, list[StudyRecord]]], plan: AnalysisPlan
) -> TidyDataset:
    """Aggregate each series' records by ``group_by`` and tag points with the series.

    ``series_studies`` is assembled by the orchestrator as
    ``list[tuple[series_value, records]]`` (see the comparison contract in the
    transform PRD); this function only aggregates the already-labeled sets.
    """

    field = plan.group_by
    if field is None:
        raise ValueError("comparison requires plan.group_by")
    group_name = field.value
    dim_names = [group_name, "series"]

    if not series_studies:
        return TidyDataset(
            points=[],
            dimension_names=dim_names,
            measure_name=_MEASURE,
            warnings=["no series to aggregate; empty comparison"],
        )

    points: list[DataPoint] = []
    total = 0
    for series_value, studies in series_studies:
        total += len(studies)
        buckets = _count_by_field(studies, field)
        series_points = _categorical_points(
            buckets, group_name, _FIELD_PATH[field], extra_dims={"series": series_value}
        )
        points.extend(_sorted_by_value(series_points, group_name))

    warnings = [] if total else ["all comparison series were empty; nothing to aggregate"]
    return TidyDataset(
        points=points, dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
    )


# ---------------------------------------------------------------------------
# numeric_distribution / numeric_relationship
# ---------------------------------------------------------------------------


def _numeric_value(study: StudyRecord, numeric: NumericField) -> float | None:
    """The numeric value for a study, or ``None`` when it cannot be computed."""

    if numeric is NumericField.enrollment_count:
        return float(study.enrollment_count) if study.enrollment_count is not None else None
    # duration_days = completion_date - start_date (both required, non-negative).
    if study.start_date is not None and study.completion_date is not None:
        days = (study.completion_date - study.start_date).days
        return float(days) if days >= 0 else None
    return None


def _numeric_excerpt(numeric: NumericField, value: float) -> str:
    if numeric is NumericField.enrollment_count:
        return str(int(value))
    return f"{int(value)} days"


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (pure Python; no numpy)."""

    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (q / 100.0) * (len(s) - 1)
    lo_i = math.floor(rank)
    hi_i = math.ceil(rank)
    if lo_i == hi_i:
        return s[lo_i]
    frac = rank - lo_i
    return s[lo_i] * (1 - frac) + s[hi_i] * frac


def _bin_edges(values: list[float]) -> list[float]:
    """Histogram bin edges via Freedman-Diaconis, with a ~20-bin fallback.

    Falls back to 20 equal-width bins when the IQR is zero (degenerate spread);
    collapses to a single unit-width bin when every value is identical.
    """

    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [lo, lo + 1.0]

    n = len(values)
    iqr = _percentile(values, 75) - _percentile(values, 25)
    width = (2 * iqr / (n ** (1 / 3))) if iqr > 0 else 0.0
    # Freedman-Diaconis bin count, capped at 50; fall back to 20 bins when the
    # IQR is zero (degenerate spread).
    nbins = 20 if width <= 0 else min(max(1, math.ceil((hi - lo) / width)), 50)

    step = (hi - lo) / nbins
    return [lo + i * step for i in range(nbins + 1)]


def aggregate_numeric_distribution(
    studies: list[StudyRecord], plan: AnalysisPlan
) -> TidyDataset:
    """Bin a numeric field (``enrollment_count`` or ``duration_days``) into a histogram.

    Records missing the numeric are skipped (and counted in a warning). One point
    is emitted per bin — including empty bins — so the histogram has no gaps.
    """

    numeric = plan.numeric_x
    if numeric is None:
        raise ValueError("numeric_distribution requires plan.numeric_x")
    dim_names = ["bin_start", "bin_end"]

    if not studies:
        return TidyDataset(
            points=[],
            dimension_names=dim_names,
            measure_name=_MEASURE,
            warnings=["no studies to aggregate; empty histogram"],
        )

    valued: list[tuple[StudyRecord, float]] = []
    skipped = 0
    for study in studies:
        v = _numeric_value(study, numeric)
        if v is None:
            skipped += 1
            continue
        valued.append((study, v))

    warnings: list[str] = []
    if skipped:
        warnings.append(f"{skipped} study(ies) skipped: missing {numeric.value}")
    if not valued:
        warnings.append(f"no studies with {numeric.value}; empty histogram")
        return TidyDataset(
            points=[], dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
        )

    edges = _bin_edges([v for _, v in valued])
    nbins = len(edges) - 1
    lo, hi = edges[0], edges[-1]
    width = (hi - lo) / nbins if nbins else 0.0
    field_path = (
        FIELD_ENROLLMENT if numeric is NumericField.enrollment_count else FIELD_DURATION_DAYS
    )

    buckets: list[list[tuple[StudyRecord, float]]] = [[] for _ in range(nbins)]
    for study, v in valued:
        idx = 0 if width == 0 else min(int((v - lo) / width), nbins - 1)
        buckets[max(idx, 0)].append((study, v))

    points: list[DataPoint] = []
    for i in range(nbins):
        members = buckets[i]
        citations = [
            make_citation(s, excerpt=_numeric_excerpt(numeric, v), field=field_path)
            for s, v in members
        ]
        points.append(
            DataPoint(
                dims={"bin_start": edges[i], "bin_end": edges[i + 1]},
                measure=_MEASURE,
                value=float(len(members)),
                citations=citations,
            )
        )
    return TidyDataset(
        points=points, dimension_names=dim_names, measure_name=_MEASURE, warnings=warnings
    )


def aggregate_numeric_relationship(
    studies: list[StudyRecord], plan: AnalysisPlan
) -> TidyDataset:
    """One point per study with both numerics present (scatter). Kept simple (P2)."""

    numeric_x = plan.numeric_x
    numeric_y = plan.numeric_y
    if numeric_x is None or numeric_y is None:
        raise ValueError("numeric_relationship requires numeric_x and numeric_y")
    dim_names = ["nct_id", numeric_x.value, numeric_y.value]

    if not studies:
        return TidyDataset(
            points=[],
            dimension_names=dim_names,
            measure_name="study",
            warnings=["no studies to aggregate; empty scatter"],
        )

    points: list[DataPoint] = []
    skipped = 0
    for study in studies:
        x = _numeric_value(study, numeric_x)
        y = _numeric_value(study, numeric_y)
        if x is None or y is None:
            skipped += 1
            continue
        dims: dict[str, str | int | float] = {"nct_id": study.nct_id, numeric_x.value: x}
        dims[numeric_y.value] = y
        points.append(
            DataPoint(
                dims=dims,
                measure="study",
                value=1.0,
                citations=[make_citation(study, field=None)],
            )
        )

    warnings: list[str] = []
    if skipped:
        warnings.append(
            f"{skipped} study(ies) skipped: missing {numeric_x.value} or {numeric_y.value}"
        )
    if not points:
        warnings.append("no studies with both numerics; empty scatter")
    return TidyDataset(
        points=points, dimension_names=dim_names, measure_name="study", warnings=warnings
    )
