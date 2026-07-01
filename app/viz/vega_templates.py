"""Hand-built Vega-Lite v5 spec dicts (no extra dependency).

Each function returns a plain ``dict`` ready to drop into ``vega-embed``, with
the chart's records inlined under ``data.values``. We build these by hand rather
than going through altair so the output is transparent, dependency-free, and
fully under our control (the assignment rewards "frontend-friendly I/O").

The semantic :class:`~app.contracts.viz.Encoding` is produced separately by the
chart builders; these templates are the concrete embedded layer only. Vega-Lite
ignores any extra keys on a datum (e.g. ``citations``), so callers inline the
dimension/measure keys only.
"""

from __future__ import annotations

from typing import Any

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

# Standard vega world atlas; ``countries`` feature ids are ISO 3166-1 numeric
# codes, which app.viz.geo maps country names to.
WORLD_TOPOJSON_URL = "https://cdn.jsdelivr.net/npm/vega-datasets@2/data/world-110m.json"


def _channel(field: str, ch_type: str, title: str, **extra: Any) -> dict[str, Any]:
    channel: dict[str, Any] = {"field": field, "type": ch_type, "title": title}
    channel.update(extra)
    return channel


def bar_spec(
    *,
    title: str,
    x_field: str,
    x_title: str,
    y_field: str,
    y_title: str,
    values: list[dict[str, Any]],
    sort: Any = None,
) -> dict[str, Any]:
    """A simple/ranked bar chart."""
    x_channel = _channel(x_field, "nominal", x_title)
    if sort is not None:
        x_channel["sort"] = sort
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": x_channel,
            "y": _channel(y_field, "quantitative", y_title),
        },
        "data": {"values": values},
    }


def grouped_bar_spec(
    *,
    title: str,
    x_field: str,
    x_title: str,
    y_field: str,
    y_title: str,
    series_field: str,
    series_title: str,
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    """Grouped bars: one cluster per ``x_field``, one bar per series value."""
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": _channel(x_field, "nominal", x_title),
            "y": _channel(y_field, "quantitative", y_title),
            "xOffset": {"field": series_field},
            "color": _channel(series_field, "nominal", series_title),
        },
        "data": {"values": values},
    }


def time_series_spec(
    *,
    title: str,
    x_field: str,
    x_title: str,
    y_field: str,
    y_title: str,
    time_unit: str,
    values: list[dict[str, Any]],
    color_field: str | None = None,
    color_title: str | None = None,
    color_sort: Any = None,
) -> dict[str, Any]:
    """A line+point time series with an explicit ``timeUnit`` on x.

    When ``color_field`` is given, the series is split into one colored line per
    value of that field (e.g. one line per phase).
    """
    encoding: dict[str, Any] = {
        "x": _channel(x_field, "temporal", x_title, timeUnit=time_unit),
        "y": _channel(y_field, "quantitative", y_title),
    }
    if color_field is not None:
        color = _channel(color_field, "nominal", color_title or color_field)
        if color_sort is not None:
            color["sort"] = color_sort
        encoding["color"] = color
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "mark": {"type": "line", "point": True},
        "encoding": encoding,
        "data": {"values": values},
    }


def histogram_spec(
    *,
    title: str,
    x_field: str,
    x_title: str,
    y_field: str,
    y_title: str,
    values: list[dict[str, Any]],
    sort: Any = None,
) -> dict[str, Any]:
    """A histogram over pre-computed bins (bin label is an ordinal x)."""
    x_channel = _channel(x_field, "ordinal", x_title)
    if sort is not None:
        x_channel["sort"] = sort
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": x_channel,
            "y": _channel(y_field, "quantitative", y_title),
        },
        "data": {"values": values},
    }


def scatter_spec(
    *,
    title: str,
    x_field: str,
    x_title: str,
    y_field: str,
    y_title: str,
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    """A scatter plot, one point per study."""
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "mark": "point",
        "encoding": {
            "x": _channel(x_field, "quantitative", x_title),
            "y": _channel(y_field, "quantitative", y_title),
        },
        "data": {"values": values},
    }


def choropleth_spec(
    *,
    title: str,
    geo_id_field: str,
    country_field: str,
    measure_field: str,
    measure_title: str,
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    """A choropleth that joins data rows to world-110m features by geo id.

    Each row in ``values`` must carry ``geo_id_field`` (the ISO numeric code),
    ``country_field`` (display name), and ``measure_field`` (the count).
    """
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "data": {"values": values},
        "transform": [
            {
                "lookup": geo_id_field,
                "from": {
                    "data": {
                        "url": WORLD_TOPOJSON_URL,
                        "format": {"type": "topojson", "feature": "countries"},
                    },
                    "key": "id",
                },
                "as": "geo",
            }
        ],
        "projection": {"type": "equalEarth"},
        "mark": "geoshape",
        "encoding": {
            "shape": {"field": "geo", "type": "geojson"},
            "color": _channel(measure_field, "quantitative", measure_title),
            "tooltip": [
                {"field": country_field, "type": "nominal"},
                {"field": measure_field, "type": "quantitative"},
            ],
        },
    }
