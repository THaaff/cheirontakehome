# ClinicalTrials.gov · Query → Visualization

A backend that turns a natural-language question about clinical trials into a
**renderer-ready visualization spec** — a chart or a network graph — backed by real
[ClinicalTrials.gov v2](https://clinicaltrials.gov/data-api/api) data, with per-datum
**citations** back to the source trials. A frontend is not required: the output is
unambiguous enough to render without guessing.

```
POST /visualize   {"query": "How has the number of pembrolizumab trials changed per year since 2018?"}
   → {"visualization": { "kind": "chart", "type": "time_series", "encoding": {…}, "vega_spec": {…},
                         "data": [ {"year": 2018, "trial_count": 41, "citations": [{"nct_id": "NCT…"}]}, … ] },
      "meta": { "query_interpretation": "…", "studies_analyzed": 500, "data_timestamp": "…", "warnings": […] } }
```

---

## 1. Overview

This is **two well-studied problems chained**, solved with a constrained pipeline rather
than a free-form agent loop:

1. **NL → query** (semantic parsing / function-calling): classify the question into a
   fixed operation and extract its entities and filters.
2. **NL → visualization** (chart-type selection + field-to-channel encoding): map that
   structured intent onto a chart or graph.

An LLM runs **exactly one stage** — it reads the query and fills a typed `AnalysisPlan`.
Everything after that (retrieval from CT.gov, aggregation, spec assembly, validation) is
ordinary, deterministic Python operating on real API responses. **No number in the output
ever comes from the model.**

---

## 2. How to run

**Prerequisites:** Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                                   # create the venv + install locked deps
cp .env.example .env                      # then set OPENAI_API_KEY for live mode (see below)
uv run uvicorn app.api.main:app --port 8000
```

Example request (interactive docs at `http://localhost:8000/docs`):

```bash
curl -s -X POST localhost:8000/visualize \
  -H 'content-type: application/json' \
  -d '{"query": "What is the distribution of melanoma trials across phases?"}' | head -c 600
```

### Live vs. replay

| | **live** | **replay** |
|---|---|---|
| Planner (NL → plan) | OpenAI Structured Outputs (needs `OPENAI_API_KEY`) | recorded plan (no key) |
| Retrieval (CT.gov) | hits the API, caches raw pages | reads the cache (no network) |
| Set via | `options.mode:"live"` (default) | `options.mode:"replay"` |

`.env` holds `OPENAI_API_KEY` (live only), `CTGOV_BASE_URL`, `CACHE_DIR`, and `PLANNER_MODEL`
(default `gpt-4.1`). **`.env` is gitignored; only `.env.example` is committed.**

> **Honest caveat about server replay.** The planner in the running server *always* calls
> the LLM — there is no planner-replay branch in `app/`, so `options.mode:"replay"` on a raw
> `curl` still needs a key for the *planning* step (it only makes *retrieval* key/network-free).
> Truly key-free reproduction is delivered by **`scripts/capture_examples.py --mode replay`**,
> which injects the **recorded** plans (the same seam the integration tests use). See
> [§6 Limitations](#6-limitations--what-id-improve-with-more-time). This is a deliberate,
> documented tradeoff, not an oversight.

### Reproduce the committed examples offline (no key, no network)

```bash
uv run python scripts/capture_examples.py --mode replay
ls examples/*/response.json
```

Every example under `examples/` regenerates **byte-for-byte** from the committed recorded
plan + cached CT.gov pages; the script self-verifies and exits non-zero on any drift. The
author populated these once with `--mode live` (key + network); graders never need either.
See [`examples/README.md`](examples/README.md).

---

## 3. Request & response schema

The authoritative contract is the exported JSON Schema in **[`docs/schemas/`](docs/schemas/)**
(`VisualizationRequest.json`, `VisualizationResponse.json`, `ErrorResponse.json`) — also served
live as OpenAPI at `/docs`. Highlights:

**Request** — only `query` is required; the rest are optional planner hints.

```jsonc
{
  "query": "…",                       // required, natural language
  "drug_name": null, "condition": null, "sponsor": null,   // optional hints
  "phase": null, "country": null, "start_year": null, "end_year": null,
  "options": { "mode": "live", "max_studies": 25000, "force_refresh": false, "debug": false }
}
```

**Response envelope** — `request_id`, the `visualization` spec, and `meta`
(`query_interpretation`, `filters_applied`, `total_studies_matched`, `studies_analyzed`,
`data_timestamp`, `warnings`, and the full `plan` when `options.debug` is true).

**`VizSpec` is a discriminated union on `kind`** — `chart` or `graph`. Two ideas make the
output frontend-friendly:

- **Semantic encoding layer + concrete embedded spec.** Every chart carries a
  renderer-agnostic `encoding` (channel → `{field, type, title}`) *and* an embedded
  Vega-Lite `vega_spec` with the data inlined under `data.values`. A frontend can render
  with a single `vega-embed` call, or read the semantic layer and draw its own way.
- **Per-datum citations.** Every chart datum, graph node, and graph edge carries a list of
  `Citation {nct_id, excerpt, field}` pointing back to the exact contributing trials.

```jsonc
// kind:"chart"  (renderer: "vega-lite" | "vega")
{ "kind": "chart", "type": "bar_chart", "renderer": "vega-lite", "title": "…",
  "encoding": { "x": {"field":"phase","type":"nominal"}, "y": {"field":"trial_count","type":"quantitative"} },
  "data": [ { "phase": "PHASE3", "trial_count": 78, "citations": [ {"nct_id":"NCT…","excerpt":"PHASE3"} ] } ],
  "vega_spec": { "$schema":"…/vega-lite/v5.json", "mark":"bar", "data": {"values":[…]}, … } }

// kind:"graph"  (renderer: "graph")
{ "kind": "graph", "type": "network_graph", "layout": "precomputed",
  "data": { "nodes": [ {"id":"drug:pembrolizumab","type":"drug","weight":38,"x":…,"y":…,"citations":[…]} ],
            "edges": [ {"source":"…","target":"…","weight":8,"citations":[…]} ] } }
```

Errors return an `ErrorResponse` tagged with the failing `stage` — `422` (validation/planning
input), `502` (upstream CT.gov), `500` (internal). An empty result set is a valid `200` with
a `warnings` entry, never a silent blank chart.

---

## 4. Key design decisions & tradeoffs

**The model plans; code executes — a hard wall between them.** The LLM only classifies the
query into a fixed operation and extracts entities into a validated `AnalysisPlan`; it never
sees a trial count and never emits a data value. I chose this because the domain is clinical:
a confidently wrong *"Phase 3: 78 trials"* is worse than a clear error. It also makes the
system **testable** — the planner is a classifier I can score, the executor is deterministic
code I can test against fixtures. **The tradeoff I'm accepting:** I give up agentic
flexibility for reliability and verifiability. For an open-ended research assistant that
would be the wrong call; for a high-stakes, narrow-surface data tool it's the right one.
This is the same pattern commercial NL-to-viz systems use (Tableau Ask Data, Power BI Q&A) —
constrain NL to a closed semantic layer instead of letting the model freestyle specs.

**A closed-world `AnalysisPlan` IR (7 operations).** The single most important object is a
typed plan sitting between language and execution. Adding a query class is "add an enum value
plus a handler," not "rewrite the agent." That closed world is what yields *breadth without
one-off hacks* and what makes hallucination structurally impossible: the model classifies into
a fixed set and extracts, never inventing fields. A pydantic `model_validator` enforces the
operation→required-fields matrix, so an invalid plan (e.g. a `comparison` with no `series`)
cannot even be constructed.

**Vega-Lite subset + a semantic layer.** Vega-Lite is a proven grammar and the assignment's
`type/title/encoding/data` shape is already a subset of it, so the frontend renders with one
`vega-embed` call. I add the renderer-agnostic semantic layer on top so the contract survives
a renderer swap. *Rejected:* a bespoke spec format (reinvents a grammar).

**Discriminated union on `kind` (chart vs graph).** Vega-Lite can't express a force-directed
graph, so networks get their own `nodes`/`edges` spec (built with `networkx`, layout
optionally precomputed server-side). The union lets charts and graphs share one contract while
`chart` still carries a `renderer` (`vega-lite`/`vega`) — the discriminator is `kind`, not
`renderer`, because `renderer` isn't unique.

**Client-side aggregation, with projection pushdown and caching.** CT.gov's `/stats`
endpoints don't accept search filters, so any *filtered* distribution must be computed locally
by paging `/studies`. I request only the fields the aggregation and citation excerpts need
(`fields=` projection pushdown — kilobytes vs. megabytes when paging) and cache raw pages
keyed by the query and the data timestamp, which is also what makes `replay` mode possible.

**Provenance threaded from the transform layer.** Citations are a first-class output of
aggregation and pass through the viz builders unchanged. Deep citations are cheap when threaded
early and very expensive to retrofit — so every node, edge, and datum knows its source NCT ids.

**Planner-executor over a ReAct loop.** One structured-output call (plus at most one
validation-correction retry), not an open-ended tool-invoking agent. Fewer moving parts, no
tool-invention, and a decode that's constrained to a JSON schema.

*Chart-selection theory worth naming:* the picker is a small hardcoded version of Mackinlay's
APT (expressiveness/effectiveness, 1986) and Cleveland–McGill's perceptual ranking (position >
length > angle > area > color, 1984). Draco is the modern constraint-based version, and LIDA is
the closest LLM-era analog to this whole task.

---

## 5. Query & visualization coverage

Seven operations map to seven viz types through a **registry** (`app/viz/registry.py`) —
`build_viz` derives the *authoritative* viz type from `plan.operation`. Adding a chart type is
one registry entry. **✅ = a committed example** under `examples/`.

| Operation | Viz type | Example query | Tier | |
|---|---|---|---|---|
| `time_trend` | `time_series` | *"…pembrolizumab trials per year since 2018?"* | P0 | ✅ |
| `categorical_distribution` | `bar_chart` | *"…distribution of melanoma trials across phases?"* | P0 | ✅ |
| `comparison` | `grouped_bar_chart` | *"…sponsor types for melanoma vs lung cancer?"* | P0 | ✅ |
| `cooccurrence_network` | `network_graph` | *"…network of sponsors and drugs in melanoma trials?"* | P1 | ✅ |
| `geographic_distribution` | `choropleth_map` (ranked-bar fallback) | *"…countries with the most recruiting melanoma trials?"* | P1 | ✅ |
| `numeric_distribution` | `histogram` | *"…distribution of enrollment sizes for melanoma trials?"* | P2 | ✅ |
| `numeric_relationship` | `scatter_plot` | *"…enrollment vs. study duration?"* | P2 | wired, not captured |

The `cooccurrence_network` (bipartite sponsor↔drug, drug↔drug, or sponsor↔sponsor) and the
deep-citation payload are the differentiators. Six of the seven operations are captured as
real runs; see [`examples/`](examples/).

---

## 6. Limitations & what I'd improve with more time

- **Planner replay isn't wired into the server.** `app/planner/plan_query` always calls the
  LLM, so key-free replay end-to-end only works via `scripts/capture_examples.py` (which
  injects recorded plans). The clean fix is a recorded-plan store the pipeline reads in
  `replay` mode — the retrieval cache already does exactly this for data.
- **Geo name → ISO mapping is finite.** Country names are matched against ~200 world-110m
  entries; an *unknown* name falls back to a ranked bar chart, and *unrenderable* territories
  (e.g. Singapore, Hong Kong — real places the basemap has no polygon for) stay in the data
  with a note but draw no shape. A gazetteer/fuzzy match would widen coverage.
- **Filters applied client-side.** Date and country filters run during transform, not as
  server-side `filter.*` params; pushing them upstream would shrink payloads and let bigger
  result sets be analyzed within the `max_studies` budget.
- **No `/stats` fast path.** Unfiltered global distributions could skip paging entirely via
  `/stats/field/values`; I always page `/studies` for consistency.
- **Protocol-metadata only.** No results-section analytics (adverse events, outcome measures)
  — a separate, much larger initiative.
- **Single-turn.** One request, one response; no follow-up refinement or session state.
- **More viz + a fuller eval.** `scatter_plot` is wired but not captured; the planner eval is
  15 labeled queries — a larger, adversarial set would harden it.

---

## 7. AI tools used (integrity note)

This project was built with **AI coding assistance** (Anthropic's Claude via the Conductor
multi-agent workspace), and I want to be specific about how.

- **What the tools did.** I authored the design first — `docs/system-design.md` and the
  per-stage PRDs fix the architecture (the model-plans-code-executes wall, the `AnalysisPlan`
  IR, the viz registry, the contract shapes). The frozen `app/contracts/` package was written
  and locked in Phase 0; each later stage (planner, retrieval, transform, viz, integration)
  was then implemented against those frozen contracts, largely generated-and-reviewed by the
  agent, one worktree at a time. This deliverables layer (README, examples, capture script,
  demo) was likewise generated against the finished system and does not touch `app/`.
- **What I designed deliberately vs. generated-and-adapted.** *Deliberate:* the staged
  pipeline, the closed operation set and its validation matrix, the chart-vs-graph union, the
  provenance-from-transform decision, the live/replay reproducibility model. *Generated and
  then reviewed/adapted:* most implementation code within those contracts, the vega templates,
  and the geo mapping table.
- **How I validated correctness (not vibes).**
  - **Planner eval** — 15 labeled queries scored for operation accuracy and entity extraction:
    **15/15 and 15/15** in replay (`uv run python -m app.planner.eval`).
  - **Test suite** — **247 passing, 2 skipped** across 39 files (`uv run pytest`), all offline;
    one end-to-end replay test drives the real `POST /visualize`.
  - **Live API spike** — real CT.gov v2 responses captured and inspected to confirm field
    paths and the stats-filter limitation (`fixtures/raw/notes.md`).
  - **Replay determinism** — the six committed examples reproduce **byte-for-byte** offline;
    the capture script self-checks and fails on drift.
- **A real bug I caught reviewing generated output.** The network's server-side `spring_layout`
  is seeded, but the graph feeds a *set of string node-ids* into it, and CPython randomizes
  string hashing per process — so layout coordinates drifted run-to-run. The capture script
  pins `PYTHONHASHSEED=0` (by re-exec) so every capture and replay is identical. That's the
  kind of determinism gap that only surfaces when you actually diff the outputs.

---

## 8. Testing & eval

```bash
uv run pytest                          # 247 passed, 2 skipped — all offline, no key/network
uv run pytest tests/integration        # end-to-end POST /visualize in replay
uv run python -m app.planner.eval      # planner eval (replay): 15/15 operation & extraction
uv run python -m app.planner.eval --live --record   # re-record plans (needs OPENAI_API_KEY)
uv run ruff check .                     # lint (clean)
uv run mypy app/contracts               # type-check the frozen contracts (strict)
```

The 2 skipped tests are live-only (they need a key + network); everything else runs against
fixtures and the replay cache. The planner eval defaults to **replay** over committed
recordings in `app/planner/eval/recorded/`, so it's deterministic and key-free; `--live
--record` re-queries `gpt-4.1` and rewrites those recordings.

---

## Repository layout

```
app/         contracts · planner · retrieval · transform · viz · validation · api   (the system — not modified here)
docs/        system-design.md · prd-*.md · schemas/*.json (the authoritative contract)
examples/    <name>/{request,response,plan}.json + note.md  ·  replay_cache/  (committed, offline-reproducible)
demo/        index.html (optional bonus) + examples.json (generated bundle)
scripts/     capture_examples.py · export_schemas.py · spike_api.py
tests/       247 tests across the 6 stages + integration
```

**Optional demo (bonus).** A single static `demo/index.html` (no build step) renders chart
specs with `vega-embed` and the network spec with a small `d3-force` block, surfacing
citations on hover/click:

```bash
uv run uvicorn app.api.main:app --port 8000 &   # for the live query box (needs a key)
python -m http.server -d demo 8080              # then open http://localhost:8080
```

The example browser in the demo is **fully offline** (it loads `demo/examples.json`); the
live query box needs the running API. See [`demo/README.md`](demo/README.md).

**Packaging.** The repo *is* the submission; producing a zip is a manual final step, e.g.
`git archive --format=zip -o submission.zip HEAD` (excludes `.venv/`, `.cache/`, `.git/`).
