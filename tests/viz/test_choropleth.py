"""Choropleth happy path and the documented ranked-bar fallback."""

from __future__ import annotations

from conftest import load_plan
from pydantic import TypeAdapter

from app.contracts import (
    ChartVizSpec,
    Citation,
    DataPoint,
    TidyDataset,
    VizSpec,
    VizType,
)
from app.viz import build_viz

_VIZ_ADAPTER = TypeAdapter(VizSpec)


def _geo_tidy(countries: list[str]) -> TidyDataset:
    points = [
        DataPoint(
            dims={"country": name},
            measure="trial_count",
            value=float(10 * (i + 1)),
            citations=[Citation(nct_id=f"NCT0000000{i}", excerpt=name, field="locations.country")],
        )
        for i, name in enumerate(countries)
    ]
    return TidyDataset(points=points, dimension_names=["country"], measure_name="trial_count")


def test_choropleth_when_all_countries_resolve() -> None:
    tidy = _geo_tidy(["United States", "France", "Germany"])
    spec = build_viz(tidy, load_plan("geographic_distribution.json"))
    assert isinstance(spec, ChartVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.type is VizType.choropleth_map
    assert spec.vega_spec["mark"] == "geoshape"
    values = spec.vega_spec["data"]["values"]
    assert values
    assert all("geo_id" in row for row in values)


def test_unknown_country_falls_back_to_ranked_bar_with_note() -> None:
    # "Atlantis" is unrecognized -> ranked bar fallback with an explanatory note.
    tidy = _geo_tidy(["United States", "Atlantis"])
    spec = build_viz(tidy, load_plan("geographic_distribution.json"))
    assert isinstance(spec, ChartVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.type is VizType.bar_chart
    assert spec.vega_spec["mark"] == "bar"
    assert spec.hints.note
    assert "Atlantis" in spec.hints.note
    # Citations still survive through the fallback.
    assert {c.nct_id for d in spec.data for c in d.citations} == {"NCT00000000", "NCT00000001"}


def test_unrenderable_territory_still_renders_choropleth_with_hint() -> None:
    # Hong Kong is a real place world-110m has no feature for: the map still
    # renders for the countries that resolve, and the territory is named in a
    # hint (never silently dropped from the data).
    tidy = _geo_tidy(["United States", "France", "Hong Kong"])
    spec = build_viz(tidy, load_plan("geographic_distribution.json"))
    assert isinstance(spec, ChartVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.type is VizType.choropleth_map
    assert spec.vega_spec["mark"] == "geoshape"
    # Only the resolvable countries get a geo_id; Hong Kong stays without one.
    values = spec.vega_spec["data"]["values"]
    assert sum("geo_id" in row for row in values) == 2
    assert spec.hints.note and "Hong Kong" in spec.hints.note
    # Every country — including the unrenderable one — survives in the data.
    assert {c.nct_id for d in spec.data for c in d.citations} == {
        "NCT00000000",
        "NCT00000001",
        "NCT00000002",
    }
