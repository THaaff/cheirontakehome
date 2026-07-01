"""End-to-end replay tests for the P0/P1 vertical (no key, no network).

Each test injects a known ``AnalysisPlan`` fixture and seeds the retrieval cache
from ``fixtures/raw``, then drives the real ``POST /visualize`` endpoint.
"""

from __future__ import annotations

from _replay_helpers import empty_pages, load_plan, seed_cache, seed_comparison

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Measure,
    Operation,
    SeriesDimension,
    SeriesSpec,
    Settings,
    VizType,
)


def _post(client: object, query: str, **options: object) -> object:
    body = {"query": query, "options": {"mode": "replay", **options}}
    return client.post("/visualize", json=body)  # type: ignore[attr-defined]


def test_time_trend_replay(make_client, replay_settings: Settings) -> None:
    """"pembrolizumab trials per year since 2018" -> 200 time_series + populated meta."""
    plan = load_plan("time_trend.json")
    seed_cache(replay_settings.cache_dir, plan, "studies_pembrolizumab.json")
    client = make_client(plan)

    resp = _post(client, "pembrolizumab trials per year since 2018")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    viz = body["visualization"]
    assert viz["kind"] == "chart"
    assert viz["type"] == "time_series"
    assert isinstance(viz["vega_spec"]["data"]["values"], list)
    assert viz["vega_spec"]["data"]["values"]  # populated
    meta = body["meta"]
    assert meta["total_studies_matched"] == 2892
    assert meta["studies_analyzed"] == 50
    assert meta["data_timestamp"] == "2026-06-30T09:00:05"
    assert meta["query_interpretation"]
    assert body["request_id"]


def test_comparison_replay(make_client, replay_settings: Settings) -> None:
    """Comparison across two conditions -> both series present, studies_analyzed = sum.

    Built in-code without a ``study_type`` filter: the captured fixtures do not
    populate ``studyType``, so the canonical ``comparison.json`` plan's
    ``INTERVENTIONAL`` filter would (correctly) drop every study.
    """
    plan = AnalysisPlan(
        operation=Operation.comparison,
        group_by=CategoricalField.lead_sponsor_class,
        series=SeriesSpec(dimension=SeriesDimension.condition, values=["melanoma", "lung cancer"]),
        measure=Measure.trial_count,
        proposed_viz=VizType.grouped_bar_chart,
        interpretation="Sponsor-class mix across melanoma and lung cancer trials",
    )
    seed_comparison(replay_settings.cache_dir, plan, "studies_melanoma.json")
    client = make_client(plan)

    resp = _post(client, "compare sponsor classes across melanoma and lung cancer")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    viz = body["visualization"]
    assert viz["type"] == "grouped_bar_chart"

    series_values = {record["series"] for record in viz["data"]}
    assert {"melanoma", "lung cancer"} <= series_values

    total_from_data = sum(record["trial_count"] for record in viz["data"])
    assert body["meta"]["studies_analyzed"] == total_from_data
    assert body["meta"]["studies_analyzed"] > 0
    # Both series carry the melanoma countTotal, so total_matched sums to 2 * 3723.
    assert body["meta"]["total_studies_matched"] == 2 * 3723


def test_cooccurrence_network_replay(make_client, replay_settings: Settings) -> None:
    """cooccurrence_network -> 200 graph spec with edges that connect real nodes."""
    plan = load_plan("cooccurrence_network.json")
    seed_cache(replay_settings.cache_dir, plan, "studies_melanoma.json")
    client = make_client(plan)

    resp = _post(client, "network of sponsors and drugs in melanoma trials")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    viz = body["visualization"]
    assert viz["kind"] == "graph"
    assert viz["type"] == "network_graph"

    nodes = viz["data"]["nodes"]
    node_ids = {node["id"] for node in nodes}
    for edge in viz["data"]["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
    if not nodes:
        # An empty graph is a valid 200 only if a warning explains it.
        assert body["meta"]["warnings"]


def test_zero_studies_is_200_with_warning(make_client, replay_settings: Settings) -> None:
    """Zero matched studies -> 200, empty-but-valid spec, and a warning (not an error)."""
    plan = load_plan("time_trend.json")
    seed_cache(replay_settings.cache_dir, plan, pages=empty_pages())
    client = make_client(plan)

    resp = _post(client, "pembrolizumab trials per year")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    viz = body["visualization"]
    assert viz["type"] == "time_series"
    assert viz["data"] == []
    assert viz["vega_spec"]["data"]["values"] == []
    assert body["meta"]["studies_analyzed"] == 0
    assert body["meta"]["warnings"]  # transform explained the emptiness


def test_debug_true_echoes_plan(make_client, replay_settings: Settings) -> None:
    plan = load_plan("time_trend.json")
    seed_cache(replay_settings.cache_dir, plan, "studies_pembrolizumab.json")
    client = make_client(plan)

    resp = _post(client, "pembrolizumab trend", debug=True)

    assert resp.status_code == 200, resp.text
    assert resp.json()["meta"]["plan"]["operation"] == "time_trend"


def test_debug_false_omits_plan(make_client, replay_settings: Settings) -> None:
    plan = load_plan("time_trend.json")
    seed_cache(replay_settings.cache_dir, plan, "studies_pembrolizumab.json")
    client = make_client(plan)

    resp = _post(client, "pembrolizumab trend")

    assert resp.json()["meta"]["plan"] is None
