# ClinicalTrials.gov · Query → Visualization

A backend that turns a natural-language question about clinical trials into a
**renderer-ready visualization spec** — a chart or a network graph — backed by real
[ClinicalTrials.gov v2](https://clinicaltrials.gov/data-api/api) data, with per-datum
citations back to the source trials.

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
Everything after that (retrieval from clinicaltrials.gov, aggregation, spec assembly, validation) is
ordinary, deterministic Python operating on real API responses. No number in the output
ever comes from the model.

---



## 2. How to run

**Prerequisites:** Python 3.12 and `[uv](https://docs.astral.sh/uv/)`.

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


|                     | **live**                                           | **replay**                   |
| ------------------- | -------------------------------------------------- | ---------------------------- |
| Planner (NL → plan) | OpenAI Structured Outputs (needs `OPENAI_API_KEY`) | recorded plan (no key)       |
| Retrieval (clinicaltrials.gov)  | hits the API, caches raw pages                     | reads the cache (no network) |
| Set via             | `options.mode:"live"` (default)                    | `options.mode:"replay"`      |


`.env` holds `OPENAI_API_KEY` (live only), `CTGOV_BASE_URL`, `CACHE_DIR`, and `PLANNER_MODEL`
(default `gpt-4.1`). `.env` **is gitignored; only** `.env.example` **is committed.**

> **Caveat about server replay.** The planner in the running server *always* calls
> the LLM, there is no planner-replay branch in `app/`, so `options.mode:"replay"` on a raw
> `curl` still needs a key for the *planning* step (it only makes *retrieval* key/network-free).
> Truly key-free reproduction is delivered by `scripts/capture_examples.py --mode replay`,
> which injects the **recorded** plans (the same seam the integration tests use). See
> [§6 Limitations](#6-limitations--what-id-improve-with-more-time).



### Reproduce the committed examples offline (no key, no network)

```bash
uv run python scripts/capture_examples.py --mode replay
ls examples/*/response.json
```

Every example under `examples/` regenerates from the committed recorded
plan + cached clinicaltrials.gov pages; the script self-verifies and exits non-zero on any drift.
I populated these once with `--mode live` (key + network).
See `[examples/README.md](examples/README.md)`.

---



## 3. Request & response schema

The authoritative contract is the exported JSON Schema in `[docs/schemas/](docs/schemas/)`
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

`VizSpec` **is a discriminated union on** `kind` — `chart` or `graph`. Two ideas make the
output frontend-friendly:

- **Semantic encoding layer + concrete embedded spec.** Every chart carries a
renderer-agnostic `encoding` (channel → `{field, type, title}`) and an embedded
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
input), `502` (upstream clinicaltrials.gov), `500` (internal). An empty result set is a valid `200` with
a `warnings` entry, never a silent blank chart.

---



## 4. Key design decisions & tradeoffs

**The model plans, code executes.** The LLM only classifies the
query into a fixed operation and extracts entities into a validated `AnalysisPlan`. It never
sees a trial count and never emits a data value. I chose this because the domain is clinical:
a confidently wrong "Phase 3: 78 trials" is worse than a clear error. It also makes the
system more testable. The planner is a classifier I can score, the executor is deterministic
code I can test against fixtures. **The tradeoff I'm accepting:** I give up agentic
flexibility for reliability and verifiability. 

**A closed-world** `AnalysisPlan` **intermediate (7 operations).** The single most important object is a
typed plan sitting between language and execution. Adding a query class is as easy as adding an enum value
plus a handler. That closed world is what makes hallucination structurally less likely: the model classifies into
a fixed set and extracts, never inventing fields. A pydantic `model_validator` enforces the
operation→required-fields matrix, so an invalid plan (e.g. a `comparison` with no `series`)
cannot even be constructed.

**Vega-Lite subset + a semantic layer.** I didn't want to re-invent the wheel, so rejected rebuilding 
my own charting grammar. Vega-Lite is a proven grammar and the assignment's `type/title/encoding/data` shape is already a subset of 
it, so the frontend renders with one `vega-embed` call. I add the renderer-agnostic semantic 
layer on top so the contract survives a renderer swap. 

**Discriminated union on** `kind` **(chart vs graph).** Vega-Lite can't express a force-directed
graph, so networks get their own `nodes`/`edges` spec (built with `networkx`, layout
optionally precomputed server-side). The union lets charts and graphs share one contract while
`chart` still carries a `renderer` (`vega-lite`/`vega`), but is discriminated on `kind`.

**Client-side aggregation, with projection pushdown and caching.** clinicaltrials.gov's `/stats`
endpoints don't accept search filters, so any *filtered* distribution must be computed locally
by paging `/studies`. I request only the fields the aggregation and citation excerpts need
 and cache raw pages keyed by the query and the data timestamp, which is also what makes `replay` mode possible.

**Provenance threaded from the transform layer.** Citations are a first-class output of
aggregation. Deep citations are cheap when threaded early and very expensive to retrofit. 
So every node, edge, and datum knows its source NCT id.

**Planner-executor over a ReAct loop.** One structured output call (plus at most one
validation/correction retry), not an open-ended tool-calling agent. 

---



## 5. Query & visualization coverage

Seven operations map to seven viz types through a **registry** (`app/viz/registry.py`)
`build_viz` derives the *authoritative* viz type from `plan.operation`. Adding a chart type is
one registry entry.


| Operation                  | Viz type                               | Example query                                              |
| -------------------------- | -------------------------------------- | ---------------------------------------------------------- |
| `time_trend`               | `time_series`                          | *"…pembrolizumab trials per year since 2018?"*             |
| `categorical_distribution` | `bar_chart`                            | *"…distribution of melanoma trials across phases?"*        |
| `comparison`               | `grouped_bar_chart`                    | *"…sponsor types for melanoma vs lung cancer?"*            |
| `cooccurrence_network`     | `network_graph`                        | *"…network of sponsors and drugs in melanoma trials?"*     |
| `geographic_distribution`  | `choropleth_map` (ranked-bar fallback) | *"…countries with the most recruiting melanoma trials?"*   |
| `numeric_distribution`     | `histogram`                            | *"…distribution of enrollment sizes for melanoma trials?"* |
| `numeric_relationship`     | `scatter_plot`                         | *"…enrollment vs. study duration?"*                        |


---



## 6. Limitations & what I'd improve with more time

- **Planner replay isn't wired into the server.** `app/planner/plan_query` always calls the
LLM, so key-free replay end-to-end only works via `scripts/capture_examples.py`. 
The clean fix is a recorded-plan store the pipeline reads in
`replay` mode, the retrieval cache already does exactly this for data.
- **Geo name → ISO mapping is finite.** Country names are matched against ~200 world-110m
entries; an *unknown* name falls back to a ranked bar chart, and *unrenderable* territories
(e.g. Singapore, Hong Kong, places the basemap has no polygon for) stay in the data
with a note but draw no shape. A gazetteer/fuzzy match would widen coverage.
- **Filters applied client-side.** Date and country filters run during transform, not as
server-side `filter.*` params; pushing them upstream would shrink payloads and let bigger
result sets be analyzed within the `max_studies` budget.
- **No** `/stats` **fast path.** Unfiltered global distributions could skip paging entirely via
`/stats/field/values`; I always page `/studies` for consistency.
- **Single-turn.** One request, one response. There is currently no follow-up refinement of the query or maintenance of session state.
- **More viz + a fuller eval.** the planner eval is 15 labeled queries, a larger set would make it more helpful.

---



## 7. AI tools used (integrity note)

This project was built with **AI coding assistance** (Claude via the Conductor multi-agent workspace), and I want to be specific about how.

I planned and built this project with Claude and Conductor, with Codex as a sanity check on reviews. 

- **I authored the design first**  — `docs/system-design.md` and the
per-stage PRDs fix the architecture (the model-plans-code-executes wall, the `AnalysisPlan`
, the viz registry, the contract shapes). As much as possible work was parallelized.
I planned out the PRDs for the whole project at the outset, and after the initial framework was built, 
several worktrees were created to speed up development. Each worktree was tested both by hand and by agent and 
went through an adversarial multi-agent review process.
- **How I validated correctness:**
  - **Planner eval** — 15 labeled queries scored for operation accuracy and entity extraction:
  **15/15 and 15/15** in replay (`uv run python -m app.planner.eval`).
  - **Test suite** — **247 passing, 2 skipped** across 39 files (`uv run pytest`), all offline;
  one end-to-end replay test drives the real `POST /visualize`.
  - **Live API spike** — real clinicaltrials.gov v2 responses captured and inspected to confirm field
  paths and the stats-filter limitation (`fixtures/raw/notes.md`).
  - **Replay determinism** — the six committed examples reproduce **byte-for-byte** offline;
  the capture script self-checks and fails on drift.

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
recordings in `app/planner/eval/recorded/`, so it's deterministic and key-free; `--live --record` re-queries `gpt-4.1` and rewrites those recordings.

---

