"""Chart builders: TidyDataset + AnalysisPlan -> ChartVizSpec.

Every builder follows the same three-step shape:

1. **Flatten** the tidy points into wire :class:`~app.contracts.data.ChartDatum`
   records (dimension keys + the measure key + ``citations``).
2. Set the renderer-agnostic semantic :class:`~app.contracts.viz.Encoding`
   (channels with ``field``/``type``/``title``).
3. Build the concrete embedded Vega-Lite dict (via :mod:`app.viz.vega_templates`)
   with the same records inlined under ``data.values`` (citations stripped — Vega
   ignores them anyway).

Citations are copied through unchanged; builders never invent provenance.
"""

from __future__ import annotations

from typing import Any

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Channel,
    ChannelType,
    ChartDatum,
    ChartVizSpec,
    Encoding,
    Measure,
    Phase,
    Renderer,
    TidyDataset,
    VizHints,
    VizType,
)

from . import geo, vega_templates

# The series dimension produced by the transform layer for `comparison` plans.
SERIES_DIM = "series"

# Canonical phase ordering — more meaningful for a phase axis than sorting by
# height, and matches the contracts reference fixture.
PHASE_ORDER: list[str] = [p.value for p in Phase]

# Human-readable axis/legend titles for the fields we group on.
_FIELD_LABELS: dict[str, str] = {
    "phase": "Clinical trial phase",
    "overall_status": "Overall status",
    "study_type": "Study type",
    "lead_sponsor_class": "Lead sponsor class",
    "intervention_type": "Intervention type",
    "country": "Country",
    "condition": "Condition",
    "year": "Year",
    "month": "Month",
    "enrollment_count": "Enrollment count",
    "duration_days": "Study duration (days)",
}

_UNITS: dict[Measure, str] = {
    Measure.trial_count: "trials",
    Measure.enrollment_sum: "participants",
    Measure.enrollment_mean: "participants (mean)",
}


def _label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())


def _sentence_case(text: str) -> str:
    """Capitalize the first character only, leaving acronyms (e.g. ``BRCA``) intact.

    Unlike :meth:`str.capitalize`, which lowercases the tail and would mangle the
    acronyms that pervade clinical/biological entity names (``EGFR`` -> ``Egfr``).
    """
    return text[:1].upper() + text[1:]


def _units(measure: Measure) -> str:
    return _UNITS.get(measure, measure.value.replace("_", " "))


def _measure_title(measure: Measure) -> str:
    if measure is Measure.trial_count:
        return "Number of trials"
    return _label(measure.value)


def _clean(value: float) -> int | float:
    """Render whole-number measures as ints (``78`` not ``78.0``)."""
    return int(value) if float(value).is_integer() else value


def _require_tidy(data: object) -> TidyDataset:
    if not isinstance(data, TidyDataset):
        raise TypeError(f"chart builders require a TidyDataset, got {type(data).__name__}")
    return data


def _flatten(data: TidyDataset) -> list[ChartDatum]:
    """Tidy points -> ChartDatum records (dims + measure + citations)."""
    measure = data.measure_name
    records: list[ChartDatum] = []
    for point in data.points:
        record: dict[str, Any] = {
            **point.dims,
            measure: _clean(point.value),
            "citations": point.citations,
        }
        records.append(ChartDatum.model_validate(record))
    return records


def _vega_values(
    data: TidyDataset, *, extra: dict[int, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Dims + measure only, for ``vega_spec.data.values`` (citations stripped).

    ``extra`` optionally merges per-index fields (e.g. a resolved ``geo_id``).
    """
    measure = data.measure_name
    rows: list[dict[str, Any]] = []
    for i, point in enumerate(data.points):
        row: dict[str, Any] = {**point.dims, measure: _clean(point.value)}
        if extra and i in extra:
            row.update(extra[i])
        rows.append(row)
    return rows


def _entity_subject(plan: AnalysisPlan) -> str | None:
    """The most specific named entity, for title composition."""
    ent = plan.entities
    return ent.drug or ent.condition or ent.sponsor or (ent.terms[0] if ent.terms else None)


def build_title(plan: AnalysisPlan, viz_type: VizType) -> str:
    """A concise, human-readable title generated from the plan.

    Falls back to the planner's one-sentence ``interpretation`` (always present)
    whenever a generated title would be thin.
    """
    subject = _entity_subject(plan)
    prefix = f"{_sentence_case(subject)} " if subject else ""

    if viz_type is VizType.bar_chart and plan.group_by is not None:
        return _sentence_case(f"{prefix}trials by {_label(plan.group_by.value).lower()}".strip())
    if (
        viz_type is VizType.grouped_bar_chart
        and plan.group_by is not None
        and plan.series is not None
    ):
        compared = " vs ".join(plan.series.values)
        return f"{_label(plan.group_by.value)} across {compared}"
    if viz_type is VizType.time_series:
        unit = plan.time_granularity
        title = _sentence_case(f"{prefix}trials per {unit}".strip())
        if plan.filters.start_year is not None:
            title += f" since {plan.filters.start_year}"
        return title
    if viz_type is VizType.choropleth_map:
        return _sentence_case(f"{prefix}trials by country".strip())
    if viz_type is VizType.histogram and plan.numeric_x is not None:
        title = f"Distribution of {_label(plan.numeric_x.value).lower()}"
        return f"{title} for {subject}" if subject else title
    if (
        viz_type is VizType.scatter_plot
        and plan.numeric_x is not None
        and plan.numeric_y is not None
    ):
        return f"{_label(plan.numeric_x.value)} vs {_label(plan.numeric_y.value).lower()}"

    return plan.interpretation


def _sole_dimension(data: TidyDataset, viz_type: str) -> str:
    """The single grouping dimension for one-axis charts."""
    if not data.dimension_names:
        raise ValueError(f"{viz_type} requires at least one dimension")
    return data.dimension_names[0]


def build_bar_chart(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Categorical distribution -> sorted bar chart."""
    tidy = _require_tidy(data)
    dim = _sole_dimension(tidy, "bar_chart")
    measure = tidy.measure_name
    title = build_title(plan, VizType.bar_chart)
    return _ranked_bar(tidy, dim=dim, measure=measure, title=title, viz_type=VizType.bar_chart)


def _ranked_bar(
    data: TidyDataset,
    *,
    dim: str,
    measure: str,
    title: str,
    viz_type: VizType,
    note: str | None = None,
) -> ChartVizSpec:
    """Shared bar assembly (also the choropleth fallback)."""
    is_phase = dim == CategoricalField.phase.value
    sort: Any = PHASE_ORDER if is_phase else "-y"

    encoding = Encoding(
        x=Channel(field=dim, type=ChannelType.nominal, title=_label(dim), sort=sort),
        y=Channel(
            field=measure, type=ChannelType.quantitative, title=_measure_title(Measure(measure))
        ),
    )
    vega = vega_templates.bar_spec(
        title=title,
        x_field=dim,
        x_title=_label(dim),
        y_field=measure,
        y_title=_measure_title(Measure(measure)),
        values=_vega_values(data),
        sort=sort,
    )
    hints = VizHints(
        sort=None if is_phase else "-y",
        units=_units(Measure(measure)),
        note=note or ("Phases shown in canonical order, not by height." if is_phase else None),
    )
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=viz_type,
        title=title,
        encoding=encoding,
        data=_flatten(data),
        vega_spec=vega,
        hints=hints,
    )


def build_grouped_bar_chart(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Comparison -> grouped bar chart (one bar per series value)."""
    tidy = _require_tidy(data)
    if SERIES_DIM not in tidy.dimension_names:
        raise ValueError("grouped_bar_chart requires a 'series' dimension in the tidy data")
    group_dims = [d for d in tidy.dimension_names if d != SERIES_DIM]
    if not group_dims:
        raise ValueError("grouped_bar_chart requires a grouping dimension besides 'series'")
    group = group_dims[0]
    measure = tidy.measure_name
    title = build_title(plan, VizType.grouped_bar_chart)
    series_title = _label(plan.series.dimension.value) if plan.series is not None else "Series"

    encoding = Encoding(
        x=Channel(field=group, type=ChannelType.nominal, title=_label(group)),
        y=Channel(
            field=measure, type=ChannelType.quantitative, title=_measure_title(Measure(measure))
        ),
        color=Channel(field=SERIES_DIM, type=ChannelType.nominal, title=series_title),
    )
    vega = vega_templates.grouped_bar_spec(
        title=title,
        x_field=group,
        x_title=_label(group),
        y_field=measure,
        y_title=_measure_title(Measure(measure)),
        series_field=SERIES_DIM,
        series_title=series_title,
        values=_vega_values(tidy),
    )
    hints = VizHints(
        units=_units(Measure(measure)),
        note="Grouped bars: one cluster per category, one bar per series value.",
    )
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=VizType.grouped_bar_chart,
        title=title,
        encoding=encoding,
        data=_flatten(tidy),
        vega_spec=vega,
        hints=hints,
    )


def build_time_series(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Time trend -> line+point time series."""
    tidy = _require_tidy(data)
    dim = _sole_dimension(tidy, "time_series")
    measure = tidy.measure_name
    title = build_title(plan, VizType.time_series)
    # Vega-Lite reads *numeric* temporal values as epoch milliseconds, so a year
    # bucket like 2018 would land in 1970. Inline the temporal field as a string
    # (parsed as an ISO date) and bin/format it in UTC so the displayed year is
    # stable regardless of the viewer's timezone.
    time_unit = "utcyearmonth" if plan.time_granularity == "month" else "utcyear"
    values = _vega_values(tidy)
    for row in values:
        row[dim] = str(row[dim])

    encoding = Encoding(
        x=Channel(field=dim, type=ChannelType.temporal, title=_label(dim)),
        y=Channel(
            field=measure, type=ChannelType.quantitative, title=_measure_title(Measure(measure))
        ),
    )
    vega = vega_templates.time_series_spec(
        title=title,
        x_field=dim,
        x_title=_label(dim),
        y_field=measure,
        y_title=_measure_title(Measure(measure)),
        time_unit=time_unit,
        values=values,
    )
    hints = VizHints(x_time_unit=plan.time_granularity, units=_units(Measure(measure)))
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=VizType.time_series,
        title=title,
        encoding=encoding,
        data=_flatten(tidy),
        vega_spec=vega,
        hints=hints,
    )


def build_histogram(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Numeric distribution -> histogram over pre-computed bins."""
    tidy = _require_tidy(data)
    dim = _sole_dimension(tidy, "histogram")
    measure = tidy.measure_name
    title = build_title(plan, VizType.histogram)
    # Preserve the bin order as emitted by the transform layer.
    bin_order = [str(point.dims[dim]) for point in tidy.points]

    encoding = Encoding(
        x=Channel(field=dim, type=ChannelType.ordinal, title=_label(dim), sort=bin_order),
        y=Channel(
            field=measure, type=ChannelType.quantitative, title=_measure_title(Measure(measure))
        ),
    )
    vega = vega_templates.histogram_spec(
        title=title,
        x_field=dim,
        x_title=_label(dim),
        y_field=measure,
        y_title=_measure_title(Measure(measure)),
        values=_vega_values(tidy),
        sort=bin_order,
    )
    hints = VizHints(
        units=_units(Measure(measure)), note="Bins pre-computed in the transform layer."
    )
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=VizType.histogram,
        title=title,
        encoding=encoding,
        data=_flatten(tidy),
        vega_spec=vega,
        hints=hints,
    )


def build_scatter_plot(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Numeric relationship -> scatter plot (one point per study)."""
    tidy = _require_tidy(data)
    measure = tidy.measure_name
    x_field = (
        plan.numeric_x.value
        if plan.numeric_x is not None
        else _sole_dimension(tidy, "scatter_plot")
    )
    y_field = plan.numeric_y.value if plan.numeric_y is not None else measure
    title = build_title(plan, VizType.scatter_plot)

    encoding = Encoding(
        x=Channel(field=x_field, type=ChannelType.quantitative, title=_label(x_field)),
        y=Channel(field=y_field, type=ChannelType.quantitative, title=_label(y_field)),
    )
    vega = vega_templates.scatter_spec(
        title=title,
        x_field=x_field,
        x_title=_label(x_field),
        y_field=y_field,
        y_title=_label(y_field),
        values=_vega_values(tidy),
    )
    hints = VizHints(note="One point per study.")
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=VizType.scatter_plot,
        title=title,
        encoding=encoding,
        data=_flatten(tidy),
        vega_spec=vega,
        hints=hints,
    )


def build_choropleth(data: object, plan: AnalysisPlan) -> ChartVizSpec:
    """Geographic distribution -> choropleth, or ranked-bar fallback.

    CT.gov gives country *names*; the choropleth keys on numeric geo ids. An
    **unknown** name (a typo or bad value) signals something is off upstream, so
    we fall back to a ranked ``bar_chart`` and explain it in a hint rather than
    drawing a partial map. **Unrenderable** territories (real places the
    world-110m basemap has no polygon for, e.g. Hong Kong or Singapore) do not
    block the map: we render the choropleth for every country that resolves and
    name the omitted territories in a hint. Either way no datum is silently
    dropped — every point stays in ``data`` with its citations.
    """
    tidy = _require_tidy(data)
    dim = _sole_dimension(tidy, "choropleth_map")
    measure = tidy.measure_name
    names = [str(point.dims[dim]) for point in tidy.points]
    resolved, unrenderable, unknown = geo.resolve_countries(names)

    # Only an unrecognized name (or nothing resolving at all) forces the bar
    # fallback; expected-but-unrenderable territories are handled below.
    if unknown or not resolved:
        note = (
            "Choropleth unavailable: "
            f"{', '.join(unknown or unrenderable)} could not be mapped to a "
            "geographic id; showing a ranked bar chart of trial counts by country instead."
        )
        return _ranked_bar(
            tidy,
            dim=dim,
            measure=measure,
            title=build_title(plan, VizType.bar_chart),
            viz_type=VizType.bar_chart,
            note=note,
        )

    title = build_title(plan, VizType.choropleth_map)
    # Only resolved points carry a geo_id; unrenderable points stay in the data
    # (with citations) but draw no shape on the map.
    geo_extra = {
        i: {"geo_id": resolved[name]}
        for i, point in enumerate(tidy.points)
        if (name := str(point.dims[dim])) in resolved
    }

    encoding = Encoding(
        x=Channel(field=dim, type=ChannelType.nominal, title=_label(dim)),
        y=Channel(
            field=measure, type=ChannelType.quantitative, title=_measure_title(Measure(measure))
        ),
    )
    vega = vega_templates.choropleth_spec(
        title=title,
        geo_id_field="geo_id",
        country_field=dim,
        measure_field=measure,
        measure_title=_measure_title(Measure(measure)),
        values=_vega_values(tidy, extra=geo_extra),
    )
    if unrenderable:
        verb = "is" if len(unrenderable) == 1 else "are"
        note = (
            f"{', '.join(unrenderable)} {verb} not shown on the map (no country boundary in "
            "the world-110m basemap); the counts remain in the underlying data."
        )
    else:
        note = "Country counts mapped onto a world choropleth (vega world-110m)."
    hints = VizHints(
        units=_units(Measure(measure)),
        note=note,
    )
    return ChartVizSpec(
        renderer=Renderer.vega_lite,
        type=VizType.choropleth_map,
        title=title,
        encoding=encoding,
        data=_flatten(tidy),
        vega_spec=vega,
        hints=hints,
    )
