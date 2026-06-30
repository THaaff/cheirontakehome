# System Design: ClinicalTrials.gov Query-to-Visualization Agent

**Status:** Draft for build · **Audience:** every Conductor worktree · **Type:** north-star reference (not a buildable task)

This document is the shared mental model. Every worktree reads it first, then reads its own PRD. It is authoritative for architecture, the external API, scope, the repo layout, and the build sequence. The **contracts PRD** (`docs/prd-contracts.md`) is authoritative for exact model definitions; this doc shows shapes at a high level only.

---

## 1. What we are building

A backend service that turns a natural-language question about clinical trials into a structured visualization specification, backed by real data from the ClinicalTrials.gov v2 API. Input is a NL query plus optional structured hints. Output is a renderer-ready visualization spec (chart or network graph) with metadata and, as a bonus, per-datum citations back to the source trial records.

A frontend is not required. The output must be unambiguous enough that a frontend engineer can render it without guessing.

This is two well-studied problems chained: NL-to-query (semantic parsing / function calling) and NL-to-visualization (chart-type selection plus field-to-channel encoding). We solve both with a constrained pipeline, not a free-form agent loop.

---

## 2. Goals and non-goals

### Goals
1. Cover the breadth of the assignment's example queries with one coherent approach: time trends, categorical distributions, comparisons, geographic patterns, and relationship/network views.
2. Produce frontend-friendly, self-describing output: a semantic encoding layer plus a concrete embedded spec, validated by a schema.
3. Make hallucination structurally impossible for any numeric value. The model classifies and extracts; code computes every count, height, and edge weight.
4. Handle messy real-world API data gracefully (null arrays, unnormalized dates, missing fields).
5. Be reproducible offline so a grader without an API key can still see real outputs (replay mode over cached fixtures).

### Non-goals (v1)
1. **No frontend application.** A single static demo page is the ceiling, and it is optional.
2. **No free-form agent autonomy.** No open-ended ReAct loop, no tool invention. The model fills a fixed plan object.
3. **No results-section analytics** (adverse events, outcome measures). We use protocol-level metadata only. Separate, much larger initiative.
4. **No model-generated data values, ever.** If a number is in the output, code derived it from the API.
5. **No multi-turn conversation or session state.** One request, one response.
6. **No write operations or auth.** Read-only public data.

---

## 3. Core principle: the model plans, code executes

There is a hard wall between LLM reasoning and deterministic execution.

- The LLM runs exactly one stage: it reads the NL query and emits a typed **AnalysisPlan** (intent, entities, operation, filters, grouping, proposed viz type). It never sees raw trial counts and never emits data values.
- Everything downstream (retrieval, aggregation, spec assembly, validation) is ordinary Python operating on real API responses.

Why this shape:
- **It wins the rubric.** "AI / Agent Design (20%)" explicitly rewards avoiding hallucination-prone steps and adding validation. A model that only fills a constrained, validated object cannot fabricate a statistic.
- **The domain demands it.** This is clinical data. A confidently wrong "Phase 3: 78 trials" is worse than a clear error.
- **It is testable.** The planner is evaluated as a classifier/extractor against a fixed query set. The executor is tested against fixtures. They decouple cleanly.

Tradeoff we are accepting, stated plainly for the README: we trade agentic flexibility for reliability and verifiability. For an open-ended research assistant that would be the wrong call. For a high-stakes, narrow-surface data tool it is the right one.

This is the same pattern commercial NL-to-viz systems use (Tableau Ask Data, Power BI Q&A, ThoughtSpot): constrain NL to a closed semantic layer rather than letting the model freestyle SQL or specs.

---

## 4. Architecture

Five stages, one LLM call, the rest deterministic.

```
NL query (+ optional structured hints)
   |
   v
[1] PLANNER            LLM, structured output
   |                   NL  ->  AnalysisPlan (the intermediate representation)
   |                   classifies operation, extracts entities/filters, proposes viz
   v
[2] RETRIEVAL         deterministic
   |                   AnalysisPlan -> ClinicalTrials.gov v2 calls
   |                   builds query.* / filter.*, projection pushdown, paging,
   |                   retries, caching -> raw study records
   v
[3] TRANSFORM         deterministic
   |                   raw records -> tidy dataset + provenance
   |                   groupby-count / time-bucket / co-occurrence / geo-rollup
   |                   tolerant date parsing, null-safe access
   v
[4] VIZ BUILDER       deterministic, registry-keyed by viz type
   |                   tidy data -> semantic encoding + embedded Vega-Lite/graph spec
   |                   attaches per-datum citations
   v
[5] VALIDATION        deterministic (+ optional LLM sanity check)
   |                   schema validity, encodings reference real fields, non-empty
   v
VisualizationResponse  (visualization spec + meta + citations)
```

### Stage responsibilities and ownership

| Stage | Module | Owns | Consumes | Produces |
|---|---|---|---|---|
| Planner | `app/planner/` | prompt, structured-output call, planner eval set | `VisualizationRequest` | `AnalysisPlan` |
| Retrieval | `app/retrieval/` | query builder, HTTP client, cache | `AnalysisPlan` | raw study records (typed slices) |
| Transform | `app/transform/` | aggregation primitives, date parsing, provenance | raw records + plan | `TidyDataset` (with citations) |
| Viz builder | `app/viz/` | viz registry, per-type builders | `TidyDataset` + plan | `VizSpec` |
| Validation | `app/validation/` | output validators | `VizSpec` + plan | validated `VisualizationResponse` or error |
| API + wiring | `app/api/` | FastAPI app, orchestration, error mapping | request | response |
| Contracts | `app/contracts/` | every shared model + enums | nothing | the types everyone imports |

The single most important architectural object is the **AnalysisPlan IR**. It is a typed object sitting between language and execution. Adding a new query class is "add an enum value plus a handler," not "rewrite the agent." That closed-world IR is what produces breadth without one-off hacks, and it is what makes hallucination impossible: the model classifies into a fixed operation set and extracts entities, never inventing fields or values.

The second most important object is the **viz registry**: a dispatch table keyed by viz type, where each entry knows how to turn a tidy dataset into a spec. Adding a chart type is one registry entry, not a change to the pipeline.

---

## 5. Worked example, end to end

Query: *"How has the number of trials for pembrolizumab changed per year since 2018?"*

1. **Planner** emits:
   ```
   operation: time_trend
   entities: { drug: "pembrolizumab" }
   filters: { start_year: 2018 }
   time_granularity: year
   measure: trial_count
   proposed_viz: time_series
   interpretation: "Annual count of pembrolizumab trials since 2018"
   ```
2. **Retrieval** builds `GET /studies?query.intr=pembrolizumab&fields=NCTId,BriefTitle,StartDate&pageSize=1000&countTotal=true`, pages via `nextPageToken`, caches the raw pages.
3. **Transform** parses each `StartDate` with a tolerant parser, drops nulls (recording a warning count), buckets by year, filters to >= 2018, counts trials per year, and attaches to each year the list of contributing NCT IDs as citations.
4. **Viz builder** (registry entry for `time_series`) maps `year -> x (temporal)`, `trial_count -> y (quantitative)`, emits the semantic encoding plus an embedded Vega-Lite line spec with the data inlined, and carries citations on each datum.
5. **Validation** confirms the spec is schema-valid, the encoding fields exist in the data, and the dataset is non-empty. Returns the response with `meta.studies_analyzed`, `meta.total_studies_matched`, `meta.data_timestamp`, and any warnings.

No count in that response came from the model. The model only chose `time_trend` and extracted the drug and the year floor.

---

## 6. Key design decisions

| Decision | Choice | Rationale | Rejected alternative |
|---|---|---|---|
| Viz spec format | Vega-Lite subset, embedded, plus a renderer-agnostic semantic layer | Vega-Lite is a proven grammar; the assignment's `type/title/encoding/data` is already a Vega-Lite subset; frontend renders with one `vega-embed` call | Bespoke spec format (reinvents a grammar, harder for frontend) |
| Output union | Discriminated union on `kind` (`chart` vs `graph`); chart carries `renderer` (`vega-lite` or `vega`) | Lets us mix spec dialects without breaking the contract; the semantic layer stays constant | Single rigid schema that cannot express networks |
| Query/viz space | Closed set of 7 operations mapped to 7 viz types | Breadth without one-off hacks; makes the planner a classifier; enables validation | Open-ended NL-to-spec generation (hallucination-prone, untestable) |
| LLM role | Plan only, never compute | Structural hallucination prevention; testable; domain-appropriate | ReAct agent with tool autonomy |
| Aggregation locus | Client-side, paging `/studies` | Stats endpoints do not accept search filters, so filtered distributions must be computed locally | Server-side `/stats` for everything (only works unfiltered) |
| Payload control | Projection pushdown via `fields=` | A full study record is large; we request only fields the aggregation and citation excerpt need | Fetching full records (megabytes vs kilobytes when paging) |
| Reproducibility | Cache raw responses + record planner outputs; `live` vs `replay` mode | Grader without an API key can still see real outputs; deterministic example runs | Live-only (fragile, needs key, rate-limited) |
| Provenance | First-class output of the transform layer from day one | Deep citations bonus is cheap if threaded early, very expensive to retrofit | Bolt citations on at the end |
| Network rendering | Own `nodes/edges` spec built with networkx, layout optionally precomputed server-side | Vega-Lite cannot do force-directed graphs; full Vega can but our own spec is cleaner and frontend-agnostic | Forcing the graph into full Vega in v1 |
| Enum values | Internal enums mirror the API's controlled vocabulary exactly (`PHASE3`, `RECRUITING`, `INDUSTRY`, ...) | Removes a whole class of translation bugs between our types and the API | Pretty-printed internal enums that need mapping both directions |

CS fundamentals worth naming in the README (they signal we know the theory behind chart selection): Mackinlay's APT (1986) formalized *expressiveness* and *effectiveness* of encodings; Cleveland and McGill (1984) ranked encodings by perceptual accuracy (position > length > angle > area > color). Our chart-picker is a small hardcoded version of those rankings. Draco (UW Interactive Data Lab) is the modern constraint-based operationalization, and LIDA (Microsoft Research) is the closest LLM-era analog to this whole assignment; both are good README references.

---

## 7. External data source: ClinicalTrials.gov v2 (shared cheat sheet)

Every worktree should treat these as ground truth. The retrieval worktree confirms field paths during the Phase 0 spike.

- **Base URL:** `https://clinicaltrials.gov/api/v2/`. The classic v1/XML API was retired in June 2024. Ignore any v1 examples.
- **Search:** `GET /studies`. Key params: `query.term`, `query.cond` (condition), `query.intr` (intervention/drug), `query.spons` (sponsor), `query.locn` (location), `filter.overallStatus`, `filter.phase`, `filter.geo`, `fields` (comma-separated projection), `sort`, `countTotal=true`, `pageSize` (max 1000, default 10, always set it), `pageToken` (cursor; pass `nextPageToken` from the previous page).
- **Single study:** `GET /studies/{nctId}`.
- **Stats:** `GET /stats/size`, `GET /stats/field/values`. Treat these as **whole-registry** aggregations; they do not take the search expression. Use only for global unfiltered distributions and for discovering enum values. (Confirm during the spike.)
- **Enums and metadata:** there are endpoints to list enumerated field values and the data model. Use them to get authoritative controlled vocabularies rather than hardcoding a possibly-incomplete list.
- **Freshness:** data refreshes weekdays by about 9am ET; `GET /api/v2/version` returns `dataTimestamp`. Put that timestamp in cache keys and in `meta.data_timestamp`.
- **Response shape:** studies are nested under `protocolSection`, `derivedSection`, and (when present) `resultsSection`. We use `protocolSection` and `derivedSection` only.
- **Real-world data gotchas (handle explicitly):** `conditions`, `interventions`, `locations`, and `collaborators` can be null or empty; dates are not normalized and arrive variously as `2024-01-15`, `January 2024`, or `January 15, 2024`. The transform layer needs a tolerant date parser and null-safe accessors. Call this out in the README.

Indicative field paths the transform layer will need (the spike confirms exact casing):
`protocolSection.identificationModule.nctId`, `...identificationModule.briefTitle`, `...statusModule.overallStatus`, `...statusModule.startDateStruct.date`, `...designModule.phases[]`, `...designModule.studyType`, `...sponsorCollaboratorsModule.leadSponsor.name`, `...sponsorCollaboratorsModule.leadSponsor.class`, `...armsInterventionsModule.interventions[].type`/`.name`, `...conditionsModule.conditions[]`, `...contactsLocationsModule.locations[].country`, `...designModule.enrollmentInfo.count`.

---

## 8. Scope matrix: operations to viz types

| Operation | Example query | Viz type | Priority |
|---|---|---|---|
| `time_trend` | trials per year for drug X since 2018 | `time_series` | P0 |
| `categorical_distribution` | distribution of condition Y trials across phases | `bar_chart` | P0 |
| `comparison` | sponsor categories across two conditions | `grouped_bar_chart` | P0 |
| `geographic_distribution` | countries with most recruiting trials for Y | `choropleth_map` (fallback ranked `bar_chart`) | P1 |
| `cooccurrence_network` | network of sponsors and drugs for Y; drug-drug combinations | `network_graph` | P1 (high value) |
| `numeric_distribution` | distribution of enrollment sizes | `histogram` | P2 |
| `numeric_relationship` | enrollment vs study duration | `scatter_plot` | P2 |

P0 is the must-ship vertical. The network graph and deep citations are the differentiators the rubric explicitly rewards; reserve dedicated time for them after P0 works end to end.

---

## 9. Repository layout and worktree ownership

Each worktree owns one directory and imports only from the frozen `app/contracts/` package. This is what keeps parallel agents from colliding on the same files.

```
repo/
  app/
    contracts/      # FROZEN in Phase 0: every shared model + enums   [worktree: contracts]
    planner/        # NL -> AnalysisPlan                              [worktree: planner]
    retrieval/      # CT.gov client + query builder + cache           [worktree: retrieval]
    transform/      # aggregation primitives + provenance             [worktree: transform]
    viz/            # spec builders + registry                        [worktree: viz]
    validation/     # output validators                               [worktree: integration]
    api/            # FastAPI app + orchestration                     [contracts: skeleton; integration: wiring]
  fixtures/
    raw/            # captured real CT.gov responses + field-path notes
    requests/       # example requests
    plans/          # example AnalysisPlans (one per operation)
    tidy/           # example tidy datasets
    responses/      # example full responses (one per viz type)
  docs/
    system-design.md   # this file
    prd-contracts.md   # contracts PRD
    schemas/           # exported JSON Schemas (generated in Phase 0)
  scripts/
    spike_api.py       # Phase 0 live-API capture script
  tests/
    contracts/ planner/ retrieval/ transform/ viz/ integration/
  pyproject.toml
  README.md
  .env.example
```

Merge discipline: `app/api/` is touched twice but never concurrently. Contracts creates the skeleton in Phase 0 (merged to main before anyone else starts); integration replaces the stub internals in Phase 2 (after Phase 1 worktrees merge). No two parallel worktrees write the same file.

---

## 10. Tech stack and versions

- **Language:** Python 3.12.
- **Service:** FastAPI (async; its auto-generated OpenAPI doc doubles as schema documentation).
- **Models:** Pydantic v2 for every contract (validation and JSON-Schema export for free).
- **HTTP:** httpx (async client) for the CT.gov calls.
- **Graphs:** networkx (co-occurrence construction and `spring_layout`).
- **Dates:** `python-dateutil` for tolerant parsing.
- **LLM:** hosted OpenAI for the planner via Structured Outputs (`strict: true` JSON-schema conformance, enforced by constrained decoding). Use the SDK's `responses.parse(..., text_format=PlannerOutput)` (or `chat.completions.parse(..., response_format=...)`), which returns a validated Pydantic instance. Default `PLANNER_MODEL=gpt-4.1` (supports Structured Outputs); `gpt-4.1-mini` is a cheaper, faster option in the same family if the eval set passes on it. Read the key from `OPENAI_API_KEY`. Note: strict mode has a known subset (forces `additionalProperties:false`, treats optionals as nullable, ignores some value constraints), so the planner targets a constraint-light schema and re-validates into the full IR (see the planner PRD).
- **Tests/quality:** pytest, ruff, mypy (on `app/contracts` at minimum).
- **Env/deps:** uv (fast, lockfile). pip + venv is an acceptable fallback.
- **Demo (optional):** one static HTML page using `vega-embed` from a CDN, plus a small d3-force or cytoscape block for the network type. No build chain.

---

## 11. Cross-cutting conventions

- **Config:** a single `Settings` object (pydantic-settings) reading env vars: `OPENAI_API_KEY`, `CTGOV_BASE_URL` (default the v2 base), `CACHE_DIR`, `PLANNER_MODEL` (default `gpt-4.1`), `REQUEST_MODE` default.
- **Request modes:** `live` hits the API and the model; `replay` reads cached raw responses and recorded plans. Replay makes example runs deterministic and key-free for graders.
- **Errors:** every stage raises a typed error mapped to an `ErrorResponse` with a `stage` field. HTTP mapping: 422 validation/planning input errors, 502 upstream CT.gov failures, 500 internal. Never return a 200 with fabricated or empty-but-unflagged data; an empty result set is a valid 200 with a `warnings` entry, not a silent blank chart.
- **Provenance:** citations are attached in the transform layer and threaded through unchanged. Viz builders never invent citations.
- **Logging:** structured logs per stage with the request id; log the AnalysisPlan at debug level.
- **Testing:** unit tests per worktree against fixtures; one end-to-end test in `tests/integration` exercising the P0 vertical in replay mode.

---

## 12. How this maps to the grading rubric

| Criterion | Weight | Where we earn it |
|---|---|---|
| System Design | 35% | staged pipeline, AnalysisPlan IR, viz registry, projection pushdown, caching, explicit real-data handling |
| AI / Agent Design | 20% | model fills a validated IR only; deterministic execution; pydantic validators enforce the operation matrix; planner eval set |
| Code Quality | 20% | typed contracts, fixtures, tests, ruff/mypy, docstrings, clear module boundaries |
| Query / Viz Coverage | 15% | 7-operation matrix; network graph scores higher than single-chart systems |
| I/O Design | 10% | pydantic + OpenAPI + exported JSON Schemas; semantic layer plus embedded spec |
| Bonus: deep citations | n/a | provenance threaded from the transform layer to every datum, node, and edge |

---

## 13. Execution plan for Conductor

The serial bottleneck is the contracts. Everything parallelizes the moment the interfaces are frozen.

**Phase 0 (serial, do not parallelize):** the **contracts** worktree. Freeze all models, export JSON Schemas, build the FastAPI stub, capture real API fixtures, settle the stats-filter question. Merge to main before anything else starts. This is the unblocker.

**Phase 1 (parallel wave):** five worktrees, each against fixtures/mocks defined by the contracts.
- `retrieval`, `transform`, `viz`, `planner`, and (optional) `demo`.
- None depend on each other; all depend only on merged contracts.

**Phase 2 (integration, serial):** wire the P0 vertical (`time_trend` -> `time_series`) end to end against the live API, prove it, then turn on the remaining P0 operations through the registry. Owns `app/validation/` and the real `app/api/` wiring.

**Phase 3 (hardening, partly parallel):** thread deep citations end to end; build the `cooccurrence_network` operation (heaviest single feature); empty/error handling; then P1/P2 viz types if time allows.

**Phase 4 (deliverables, serial):** README (schemas, design decisions, tradeoffs, limitations, AI-tools-used writeup), 3 to 5 example runs captured as real JSON, optional deploy, final pass.

### Worktree dependency and chaining order

| Order | Worktree | Depends on | Blocks | Can run with |
|---|---|---|---|---|
| 1 | contracts | none | all | none (solo) |
| 2 | retrieval | contracts | integration | transform, viz, planner, demo |
| 2 | transform | contracts | integration | retrieval, viz, planner, demo |
| 2 | viz | contracts | integration | retrieval, transform, planner, demo |
| 2 | planner | contracts | integration | retrieval, transform, viz, demo |
| 2 | demo (opt) | contracts | none | the rest of wave 2 |
| 3 | integration | retrieval, transform, viz, planner | hardening | none (solo) |
| 4 | hardening (citations, network) | integration | deliverables | partial overlap |
| 5 | deliverables | hardening | none | none |

Critical path: `contracts -> {retrieval, transform, viz, planner} -> integration -> network + citations -> README/examples`. The only true serial gates are Phase 0 (front) and Phase 4 (back); the middle is wide.

---

## 14. Open questions

| Question | Owner | Blocking? |
|---|---|---|
| uv vs pip/poetry for env and deps | Taylor | non-blocking (default uv) |
| Confirm Python 3.12 | Taylor | non-blocking |
| ruff + mypy in the CI gate from Phase 0, or add later | Taylor | non-blocking (recommend from Phase 0) |
| Fresh repo or slot into an existing scaffold | Taylor | blocking for contracts kickoff |
| Choropleth in P1, or downgrade geo to ranked bar only | Taylor / data | non-blocking |
| Does `/stats/field/values` accept search filters | retrieval spike | resolved in Phase 0; plan assumes no |

---

## 15. How to use this document

This doc is reference, not a task. The buildable work lives in the per-worktree PRDs. Start by handing the **contracts PRD** to Conductor; it points back here for context. When you spin up Phase 1 worktrees, each PRD will tell the agent to read this file plus the contracts PRD before writing code.
