"""Chart builder acceptance tests, parametrized over the tidy chart fixtures.

Covers every assertion the PRD asks for: output validates as VizSpec, encoding
field names exist in the data records, vega_spec.data.values is populated, and
citations survive.
"""

from __future__ import annotations

import pytest
from conftest import CHART_CASES, load_plan, load_tidy
from pydantic import TypeAdapter

from app.contracts import ChartVizSpec, Encoding, Entities, VizSpec, VizType
from app.viz import build_viz

_VIZ_ADAPTER = TypeAdapter(VizSpec)


def _encoding_fields(encoding: Encoding) -> list[str]:
    channels = [encoding.x, encoding.y, encoding.color, encoding.column, encoding.size]
    return [ch.field for ch in channels if ch is not None]


def _source_nct_ids(tidy_name: str) -> set[str]:
    tidy = load_tidy(tidy_name)
    return {c.nct_id for p in tidy.points for c in p.citations}


@pytest.mark.parametrize(("tidy_name", "plan_name"), CHART_CASES)
def test_chart_output_validates_as_vizspec(tidy_name: str, plan_name: str) -> None:
    spec = build_viz(load_tidy(tidy_name), load_plan(plan_name))
    assert isinstance(spec, ChartVizSpec)
    # Round-trips cleanly through the discriminated union.
    _VIZ_ADAPTER.validate_python(spec.model_dump())


@pytest.mark.parametrize(("tidy_name", "plan_name"), CHART_CASES)
def test_encoding_fields_exist_in_data(tidy_name: str, plan_name: str) -> None:
    spec = build_viz(load_tidy(tidy_name), load_plan(plan_name))
    assert isinstance(spec, ChartVizSpec)
    fields = _encoding_fields(spec.encoding)
    assert fields
    for datum in spec.data:
        keys = datum.model_dump().keys()
        for field in fields:
            assert field in keys, f"encoding field {field!r} missing from datum {keys}"


@pytest.mark.parametrize(("tidy_name", "plan_name"), CHART_CASES)
def test_vega_data_values_populated_and_carry_axes(tidy_name: str, plan_name: str) -> None:
    spec = build_viz(load_tidy(tidy_name), load_plan(plan_name))
    assert isinstance(spec, ChartVizSpec)
    values = spec.vega_spec["data"]["values"]
    assert values, "vega_spec.data.values must be non-empty"
    assert len(values) == len(spec.data)
    x_field = spec.encoding.x.field
    y_field = spec.encoding.y.field
    for row in values:
        assert x_field in row and y_field in row
        # Citations are stripped from the embedded spec (Vega ignores them).
        assert "citations" not in row


@pytest.mark.parametrize(("tidy_name", "plan_name"), CHART_CASES)
def test_citations_survive(tidy_name: str, plan_name: str) -> None:
    spec = build_viz(load_tidy(tidy_name), load_plan(plan_name))
    assert isinstance(spec, ChartVizSpec)
    emitted = {c.nct_id for datum in spec.data for c in datum.citations}
    assert emitted == _source_nct_ids(tidy_name)
    assert emitted, "expected at least one citation to survive"


def test_bar_chart_specifics() -> None:
    # Acceptance: categorical_distribution -> bar_chart, x.field == dimension name.
    tidy = load_tidy("bar.json")
    spec = build_viz(tidy, load_plan("categorical_distribution.json"))
    assert isinstance(spec, ChartVizSpec)
    assert spec.type is VizType.bar_chart
    assert spec.encoding.x.field == tidy.dimension_names[0] == "phase"
    assert spec.encoding.y.field == "trial_count"
    assert spec.vega_spec["mark"] == "bar"


def test_grouped_bar_specifics() -> None:
    # Acceptance: comparison -> color set to series, vega groups by series (xOffset).
    spec = build_viz(load_tidy("comparison.json"), load_plan("comparison.json"))
    assert isinstance(spec, ChartVizSpec)
    assert spec.type is VizType.grouped_bar_chart
    assert spec.encoding.color is not None
    assert spec.encoding.color.field == "series"
    assert spec.vega_spec["encoding"]["xOffset"]["field"] == "series"
    assert spec.vega_spec["encoding"]["color"]["field"] == "series"


def test_time_series_specifics() -> None:
    spec = build_viz(load_tidy("time_series.json"), load_plan("time_trend.json"))
    assert isinstance(spec, ChartVizSpec)
    assert spec.type is VizType.time_series
    assert spec.encoding.x.field == "year"
    assert spec.vega_spec["encoding"]["x"]["timeUnit"] == "utcyear"
    assert spec.hints.x_time_unit == "year"
    # Years inline as ISO-date strings, not ints: Vega-Lite reads numeric temporal
    # values as epoch ms, which would collapse every point onto 1970.
    year_values = [row["year"] for row in spec.vega_spec["data"]["values"]]
    assert year_values == ["2018", "2019", "2020", "2021", "2022"]


def test_title_preserves_acronym_casing() -> None:
    # Clinical/biological acronyms (NSCLC, EGFR, BRCA, ...) must survive title
    # casing intact; str.capitalize() would mangle "NSCLC" into "Nsclc".
    plan = load_plan("categorical_distribution.json").model_copy(
        update={"entities": Entities(condition="NSCLC")}
    )
    spec = build_viz(load_tidy("bar.json"), plan)
    assert isinstance(spec, ChartVizSpec)
    assert "NSCLC" in spec.title
    assert "Nsclc" not in spec.title
