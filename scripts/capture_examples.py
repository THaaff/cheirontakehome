"""Capture the example runs (live) and reproduce them offline (replay).

This script turns a handful of natural-language queries into committed submission
artifacts — ``examples/<name>/{request,response,plan}.json`` plus a one-line
``note.md`` — and refreshes the ``demo/examples.json`` bundle the static demo
loads. It drives the **real** pipeline (``app.api.orchestrator.run_pipeline``), so
the captured JSON is exactly what ``POST /visualize`` returns; nothing here
re-implements a stage.

Two modes:

* ``--mode live`` (the author runs this once, with ``OPENAI_API_KEY`` in ``.env``
  and network access): plans each query with one LLM call, records the resulting
  ``AnalysisPlan`` to ``plan.json``, then runs the pipeline live so retrieval
  populates the committed cache under ``examples/replay_cache/``. The recorded
  plan and the cached CT.gov pages are what make replay key-free.

* ``--mode replay`` (the default; what a grader runs, with **no key and no
  network**): loads the recorded ``plan.json`` and the cached pages and re-runs
  the pipeline, then asserts the freshly-produced ``response.json`` is
  byte-for-byte identical to the committed one. A drift exits non-zero.

Why the recorded plan is needed: the planner (``app.planner.plan_query``) always
calls the LLM — there is no planner-replay branch in the running server, so
``options.mode="replay"`` only makes *retrieval* key-free. We close that gap the
same way the integration suite does (``tests/integration/conftest.py``): inject a
known plan by monkeypatching ``app.api.orchestrator.plan_query``. That is a
supported seam — the planner client's own docstring notes tests patch it — and it
keeps this worktree from touching any application code.

The only non-deterministic field in a response is ``request_id`` (a fresh UUID per
call); we normalize it to a placeholder so replay is byte-stable. The network
layout is seeded upstream, so graphs reproduce exactly too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# A bare ``python scripts/capture_examples.py`` puts scripts/ (not the repo root)
# on sys.path, so make the ``app`` package importable regardless of how we're run.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.api.orchestrator as orchestrator  # noqa: E402  (after the sys.path shim)
from app.contracts import (  # noqa: E402
    AnalysisPlan,
    GraphVizSpec,
    RequestMode,
    RequestOptions,
    Settings,
    VisualizationRequest,
    VisualizationResponse,
)
from app.planner import plan_query  # noqa: E402
from app.planner.client import aclose as planner_aclose  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "examples"
# The retrieval cache the graders replay from. It must be *committed*, so it lives
# under examples/ (which we own) rather than the gitignored top-level `.cache/`.
CACHE_DIR = EXAMPLES_DIR / "replay_cache"
DEMO_BUNDLE = REPO_ROOT / "demo" / "examples.json"

# request_id is a per-call UUID — the one non-deterministic field. Normalize it so
# a live capture and an offline replay serialize to identical bytes.
REQUEST_ID_PLACEHOLDER = "<request-id>"

# Page budget per query. Set high enough to analyze the *full* match for every
# example (the largest is ~14k lung-cancer trials in the comparison), so the demos
# show exact counts rather than a truncated sample. Per-datum citations are capped
# in the response (Settings.max_citations_per_datum), so the committed JSON stays
# reviewable even at full corpus. Part of the cache key, so changing it re-captures.
MAX_STUDIES = 25000


@dataclass(frozen=True)
class Example:
    """One captured query: its slug, the NL question, and a one-line note."""

    name: str
    query: str
    note: str
    hints: dict[str, Any] = field(default_factory=dict)
    max_studies: int = MAX_STUDIES


# Six queries spanning six of the seven operations (chart + graph unions, the
# choropleth or its ranked-bar fallback, the numeric histogram, and deep citations
# on nodes and edges). Queries are intentionally hint-free to showcase the planner
# turning pure natural language into a validated plan.
EXAMPLES: list[Example] = [
    Example(
        name="time_trend_pembrolizumab",
        query="How has the number of trials for pembrolizumab changed per year since 2018?",
        note=(
            "time_trend → time_series: annual count of pembrolizumab trials since 2018 — "
            "how research activity for the drug has grown year over year."
        ),
    ),
    Example(
        name="phase_distribution_melanoma",
        query="What is the distribution of melanoma trials across clinical trial phases?",
        note=(
            "categorical_distribution → bar_chart: how melanoma trials split across "
            "Phase 1–4 — where the pipeline is concentrated."
        ),
    ),
    Example(
        name="sponsor_comparison_conditions",
        query="Compare the types of sponsors running melanoma trials versus lung cancer trials.",
        note=(
            "comparison → grouped_bar_chart: sponsor-class mix (industry, NIH, other) for "
            "melanoma vs lung cancer — who funds research in each."
        ),
    ),
    Example(
        name="sponsor_drug_network_melanoma",
        query="Show the network of sponsors and drugs that co-occur in melanoma trials.",
        note=(
            "cooccurrence_network → network_graph: sponsors linked to the drugs they study "
            "in melanoma trials; every node and edge carries its source NCT ids."
        ),
    ),
    Example(
        name="geo_recruiting_melanoma",
        query="Which countries have the most actively recruiting melanoma trials?",
        note=(
            "geographic_distribution → choropleth_map: recruiting-melanoma-trial counts by "
            "country (falls back to a ranked bar chart if a name can't be mapped)."
        ),
    ),
    Example(
        name="enrollment_distribution_melanoma",
        query="What is the distribution of enrollment sizes for melanoma trials?",
        note=(
            "numeric_distribution → histogram: how melanoma trials distribute across "
            "enrollment-size bins — most are small, a long tail is large."
        ),
    ),
]


# ---------------------------------------------------------------------------
# planner seam + serialization
# ---------------------------------------------------------------------------


def _inject_plan(plan: AnalysisPlan) -> None:
    """Point the orchestrator's ``plan_query`` at a fixed plan (no LLM call).

    Mirrors ``tests/integration/conftest.py``: the orchestrator calls the
    module-level name ``app.api.orchestrator.plan_query``, so replacing it there is
    all it takes to bypass the planner while every downstream stage runs for real.
    """

    async def _fake_plan_query(request: object, settings: object) -> AnalysisPlan:
        return plan

    orchestrator.plan_query = _fake_plan_query  # type: ignore[assignment]


def _request(example: Example, mode: RequestMode) -> VisualizationRequest:
    return VisualizationRequest(
        query=example.query,
        options=RequestOptions(mode=mode, max_studies=example.max_studies),
        **example.hints,
    )


def _dumps(payload: dict[str, Any]) -> str:
    """One canonical JSON encoding used for every artifact (stable across runs)."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _request_json(example: Example) -> str:
    """The committed request. Pinned to replay mode — the reproducible path."""
    return _dumps(_request(example, RequestMode.replay).model_dump(mode="json"))


def _response_json(response: VisualizationResponse) -> str:
    payload = response.model_dump(mode="json")
    payload["request_id"] = REQUEST_ID_PLACEHOLDER
    return _dumps(payload)


def _is_empty(response: VisualizationResponse) -> bool:
    viz = response.visualization
    if isinstance(viz, GraphVizSpec):
        return not viz.data.nodes
    return not viz.data


def _summary(response: VisualizationResponse) -> str:
    viz = response.visualization
    meta = response.meta
    if isinstance(viz, GraphVizSpec):
        shape = f"{len(viz.data.nodes)} nodes, {len(viz.data.edges)} edges"
    else:
        shape = f"{len(viz.data)} data points"
    total = meta.total_studies_matched
    matched = "" if total is None else f", {total} matched"
    return f"{viz.type.value} ({shape}; {meta.studies_analyzed} analyzed{matched})"


# ---------------------------------------------------------------------------
# artifact writing
# ---------------------------------------------------------------------------


def _example_dir(example: Example) -> Path:
    path = EXAMPLES_DIR / example.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_static(example: Example) -> None:
    """Write the deterministic per-example files (request.json, note.md)."""
    ex_dir = _example_dir(example)
    (ex_dir / "request.json").write_text(_request_json(example), encoding="utf-8")
    (ex_dir / "note.md").write_text(example.note.rstrip() + "\n", encoding="utf-8")


def _bundle_entry(example: Example, response: VisualizationResponse) -> dict[str, Any]:
    payload = response.model_dump(mode="json")
    payload["request_id"] = REQUEST_ID_PLACEHOLDER
    return {
        "name": example.name,
        "title": response.visualization.title,
        "note": example.note,
        "request": _request(example, RequestMode.replay).model_dump(mode="json"),
        "response": payload,
    }


def _write_bundle(entries: list[dict[str, Any]]) -> None:
    DEMO_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    DEMO_BUNDLE.write_text(_dumps({"examples": entries}), encoding="utf-8")


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------


async def capture_live() -> int:
    """Plan + record + run each query live, populating the committed replay cache."""
    settings = Settings(cache_dir=str(CACHE_DIR))
    if not settings.openai_api_key:
        print(
            "error: --mode live needs OPENAI_API_KEY (set it in .env). "
            "Replay reproduction needs no key: `--mode replay`.",
            file=sys.stderr,
        )
        return 1

    print(f"Capturing {len(EXAMPLES)} examples LIVE (cache -> {CACHE_DIR}) ...")
    entries: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            for example in EXAMPLES:
                request = _request(example, RequestMode.live)
                plan = await plan_query(request, settings)  # the one LLM call
                (_example_dir(example) / "plan.json").write_text(
                    plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
                )

                _inject_plan(plan)
                response = await orchestrator.run_pipeline(request, settings, http_client=client)

                if _is_empty(response):
                    print(
                        f"  ✗ {example.name}: EMPTY result set — pick or rephrase the query "
                        "so the example is illustrative.",
                        file=sys.stderr,
                    )
                    return 1

                _write_static(example)
                (_example_dir(example) / "response.json").write_text(
                    _response_json(response), encoding="utf-8"
                )
                entries.append(_bundle_entry(example, response))
                print(f"  ✓ {example.name}: {_summary(response)}")
    finally:
        await planner_aclose()

    _write_bundle(entries)
    print(f"\nWrote {len(entries)} examples + demo/examples.json. Commit examples/ and demo/.")
    print("Reproduce offline with: uv run python scripts/capture_examples.py --mode replay")
    return 0


async def capture_replay() -> int:
    """Re-run each query from the recorded plan + cached pages; verify byte-stability."""
    settings = Settings(
        cache_dir=str(CACHE_DIR),
        default_mode=RequestMode.replay,
        openai_api_key=None,  # explicit: keyless even if a .env key is present
    )

    print(f"Reproducing {len(EXAMPLES)} examples in REPLAY (no key, no network) ...")
    entries: list[dict[str, Any]] = []
    ok = True
    for example in EXAMPLES:
        ex_dir = EXAMPLES_DIR / example.name
        plan_path = ex_dir / "plan.json"
        if not plan_path.is_file():
            print(
                f"  ✗ {example.name}: no plan.json — run `--mode live` once to capture it.",
                file=sys.stderr,
            )
            ok = False
            continue

        plan = AnalysisPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        _inject_plan(plan)
        try:
            response = await orchestrator.run_pipeline(
                _request(example, RequestMode.replay), settings, http_client=None
            )
        except Exception as exc:  # noqa: BLE001 - report which example failed, keep going
            print(f"  ✗ {example.name}: replay failed: {exc}", file=sys.stderr)
            ok = False
            continue

        _write_static(example)
        new_text = _response_json(response)
        resp_path = ex_dir / "response.json"
        if resp_path.is_file():
            if resp_path.read_text(encoding="utf-8") == new_text:
                print(f"  ✓ {example.name}: reproduced byte-for-byte ({_summary(response)})")
            else:
                resp_path.write_text(new_text, encoding="utf-8")  # surface the drift in `git diff`
                print(
                    f"  ✗ {example.name}: DRIFT from committed response.json (rewrote it; "
                    "inspect `git diff`).",
                    file=sys.stderr,
                )
                ok = False
        else:
            resp_path.write_text(new_text, encoding="utf-8")
            print(f"  ~ {example.name}: response.json was missing; wrote it.")
        entries.append(_bundle_entry(example, response))

    _write_bundle(entries)
    if ok:
        print("\nAll examples reproduced offline with no key and no network.")
    else:
        print("\nFAILED: some examples were missing or drifted (see above).", file=sys.stderr)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    # The network builder feeds a set of string node-ids into ``spring_layout``, and
    # CPython randomizes string hashing per process — so set-iteration order (and
    # thus the seeded layout coordinates) would differ run to run. Pin the hash seed
    # by re-exec'ing once, so every capture and replay is byte-identical.
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, *sys.argv])

    parser = argparse.ArgumentParser(
        prog="python scripts/capture_examples.py", description=__doc__
    )
    parser.add_argument(
        "--mode",
        choices=("live", "replay"),
        default="replay",
        help="live: capture with a key + network (author, once). "
        "replay: reproduce offline (default; no key, no network).",
    )
    args = parser.parse_args(argv)
    runner = capture_live if args.mode == "live" else capture_replay
    return asyncio.run(runner())


if __name__ == "__main__":
    raise SystemExit(main())
