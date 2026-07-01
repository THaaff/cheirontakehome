# PRD: Integration and Validation (Phase 2)

**Worktree:** `integration` · **Status:** ready after the Phase 1 wave merges · **Depends on:** `contracts`, `retrieval`, `transform`, `viz`, `planner` · **Blocks:** `deliverables`
**Runs:** solo (serial gate) · **Read first:** `docs/system-design.md`, then every Phase 1 PRD

---

## Problem statement

The five stages exist in isolation. Nothing wires them into a working service, handles the comparison fan-out, validates the final spec, maps stage failures to HTTP status codes, or threads the live/replay mode through. This worktree is the orchestration brain: it replaces the contracts stub in `app/api/`, owns the output validation layer, and produces the real `POST /visualize`. It writes almost no new domain logic; its value is correct wiring, clean error semantics, and an end-to-end test that proves the pipeline.

## Goals
1. An orchestrator that runs request -> planner -> retrieval -> transform -> viz -> validation -> `VisualizationResponse`, including the comparison fan-out.
2. A validation stage that catches semantic problems the type system cannot (encoding fields missing from data, silently empty results) before anything reaches the client.
3. Clean, stage-tagged error handling mapped to HTTP codes, with the contract's `ErrorResponse` shape used even for input-validation errors.
4. Live and replay modes threaded end to end, so the whole pipeline runs key-free and network-free in replay.
5. An end-to-end test exercising the P0 vertical deterministically in CI.

## Non-goals
1. **No new aggregation, retrieval, planning, or chart logic.** Those are imported from their worktrees; gaps get flagged, not patched here.
2. **No README or example capture.** That is the deliverables worktree.
3. **No LLM-based output verification in v1.** The optional model sanity-check is P2.

## User stories
- As a **frontend engineer / grader**, I POST a query and get back a single render-ready `VisualizationResponse`, or a clear `ErrorResponse` with the stage that failed.
- As the **author debugging**, setting `options.debug=true` echoes the `AnalysisPlan` in `meta.plan` so I can see how the query was interpreted.
- As a **grader without a key or network**, I run the example requests in replay and get real outputs.

---

## Scope and specification

### Module layout (owns `app/api/**`, `app/validation/**`, `tests/integration/**`)
- `app/api/main.py` — FastAPI app; replaces the Phase 0 stub internals (keep the endpoint signature and `response_model`).
- `app/api/orchestrator.py` — the pipeline wiring and comparison fan-out.
- `app/api/errors.py` — `PipelineError` plus FastAPI exception handlers.
- `app/validation/validators.py` — semantic output checks.
- `app/validation/__init__.py` — exports `validate_output`.

### The orchestrator
```python
async def run_pipeline(request: VisualizationRequest, settings: Settings) -> VisualizationResponse:
    request_id = uuid4().hex

    # 1. Plan (the only LLM stage)
    plan = await _planning(request, settings)            # wraps plan_query

    # 2. Retrieve + 3. Transform, branching on operation
    if plan.operation is Operation.comparison:
        dataset, retr_meta = await _comparison_path(plan, settings, request.options)
        graph = None
    elif plan.operation is Operation.cooccurrence_network:
        result = await _retrieve(plan, settings, request.options)
        graph = build_cooccurrence_network(result.studies, plan)
        dataset, retr_meta = None, _meta_from(result)
    else:
        result = await _retrieve(plan, settings, request.options)
        dataset = dispatch_aggregation(plan, result.studies)   # transform
        graph, retr_meta = None, _meta_from(result)

    # 4. Build viz spec
    viz_spec = _build_viz(graph or dataset, plan)            # wraps build_viz

    # 5. Validate
    val_warnings = validate_output(viz_spec, graph or dataset)   # raises on hard failure

    # 6. Assemble
    meta = Meta(
        query_interpretation=plan.interpretation,
        assumptions=plan.assumptions,
        filters_applied=_filters_applied(plan),
        total_studies_matched=retr_meta.total_matched,
        studies_analyzed=retr_meta.studies_analyzed,
        data_timestamp=retr_meta.data_timestamp,
        warnings=retr_meta.warnings + (graph or dataset).warnings + val_warnings,
        plan=plan if request.options.debug else None,
    )
    return VisualizationResponse(request_id=request_id, visualization=viz_spec, meta=meta)
```
Each `_stage` helper wraps the imported stage call in `try/except` and raises a `PipelineError` tagged with the stage (see error mapping). Mode and `force_refresh` flow via `request.options` into `retrieve(plan, settings, options)`.

### Comparison fan-out (`_comparison_path`)
For a `comparison` plan, build one sub-plan per `series.values` entry by injecting the value into the entity slot named by `series.dimension` (`drug -> entities.drug`, `condition -> entities.condition`, `sponsor -> entities.sponsor`), keeping `group_by` and `filters`. Retrieve all sub-plans concurrently with `asyncio.gather`, pair each result's `studies` with its series value, and pass `list[(series_value, studies)]` to `aggregate_comparison`. Merge meta: sum `studies_analyzed`; sum `total_matched` when all are present, else `None`; concatenate and de-duplicate `warnings`; take the first non-null `data_timestamp`.

### Validation stage (`app/validation/`)
`validate_output(viz_spec, data) -> list[str]` returns soft warnings and raises `PipelineError(stage="visualization")` on a hard failure. Checks:
- **Hard:** the spec parses as `VizSpec` (final guard); for charts, every `encoding` channel `field` is a key present in the `data` records; `vega_spec` has a `data.values` array; for graphs, every edge endpoint id exists in `nodes`.
- **Soft (warn, do not fail):** empty `data` is allowed only if an upstream warning already explains it (otherwise raise, because silent emptiness is a bug); missing citations on data points (note it, since they are the bonus, but do not fail).

Empty result sets are a normal 200 with a warning, never an error.

### Error mapping (`app/api/errors.py`)
A single `PipelineError(stage: PipelineStage, error_type: str, message: str, details: dict | None)`. FastAPI exception handlers convert:

| Source | Stage | HTTP |
|---|---|---|
| FastAPI `RequestValidationError` (malformed body) | `validation` | 422 |
| planner failure (refusal, length, post-validation) | `planning` | 422 |
| retrieval upstream failure after retries | `retrieval` | 502 |
| transform / viz / validation hard failure | `transform`/`visualization` | 500 |

All handlers emit the contract's `ErrorResponse` shape (so even malformed-input errors return `{request_id, error:{type, stage, message, details}}`, not FastAPI's default envelope). A zero-study retrieval is **not** an error.

### Endpoint (`app/api/main.py`)
Replace the stub body of `POST /visualize` with `await run_pipeline(request, settings)`, keeping the `VisualizationRequest` body and `response_model=VisualizationResponse`. Keep `GET /health`. Settings is a module-level dependency. CORS stays permissive for the demo.

### Client lifecycle (long-lived, injected, closed on shutdown)
Both `plan_query` and `retrieve` accept an injected client and otherwise fall back to internal creation. The server must own the clients for the application lifecycle rather than relying on those fallbacks (per the SDK's one-client-per-lifecycle guidance; per-request clients defeat connection pooling, keep-alive, and TLS reuse). Use a FastAPI lifespan:
- On startup, create one `httpx.AsyncClient` for CT.gov and, only when `OPENAI_API_KEY` is configured, one `AsyncOpenAI`; store both on `app.state`.
- The orchestrator passes the httpx client into every `retrieve(...)` call (so the comparison fan-out's concurrent retrievals share one pool) and the OpenAI client into `plan_query(...)`.
- On shutdown, `await app.state.http.aclose()` and `await app.state.openai.close()`.

Guarding OpenAI creation on the key keeps a replay-only server key-free (the planner is only exercised on the live path; replay/injected-plan tests never call it). Do not use an `atexit` hook to close async clients; it runs without an event loop. The stages' internal client creation remains only as a fallback for standalone/CLI use.

---

## Requirements

### Must-have (P0)
- [ ] `run_pipeline` wires all five stages and returns a valid `VisualizationResponse` for time_trend, categorical_distribution, comparison, and cooccurrence_network.
- [ ] Comparison fan-out builds correct sub-plans, retrieves concurrently, and merges meta.
- [ ] `validate_output` enforces the hard checks and treats empty-with-warning as a 200.
- [ ] Stage-tagged `PipelineError` mapping to 422/502/500; all errors use the `ErrorResponse` shape.
- [ ] Mode/`force_refresh` thread through; the pipeline runs end to end in replay with no key and no network.
- [ ] `options.debug` echoes the plan in `meta.plan`.

### Nice-to-have (P1)
- [ ] geographic_distribution and numeric paths wired.
- [ ] Structured per-stage logging with the `request_id`.
- [ ] `ruff` + `mypy app/api app/validation` clean.

### Future considerations (P2)
- [ ] Optional LLM sanity-check of the final spec.
- [ ] Response caching keyed by the request.

### Acceptance criteria
- Given a POST of "pembrolizumab trials per year since 2018" in replay, When the pipeline runs, Then it returns a 200 `VisualizationResponse` with a `time_series` spec and populated `meta`.
- Given a comparison query across two conditions in replay, When the pipeline runs, Then both series appear in the data and `meta.studies_analyzed` equals the sum across series.
- Given a query whose retrieval matches zero studies, When the pipeline runs, Then it returns a 200 with an empty-but-valid spec and a warning, not an error.
- Given a malformed request body, When posted, Then the response is 422 in the `ErrorResponse` shape with `stage="validation"`.
- Given a forced retrieval failure (upstream 5xx), When the pipeline runs, Then the response is 502 with `stage="retrieval"`.
- Given a built spec whose encoding references a field absent from the data, When validated, Then `validate_output` raises and the response is 500 with `stage="visualization"`.

---

## Verification commands
```
uv run pytest tests/integration -q
uv run ruff check app/api app/validation     # P1
uv run mypy app/api app/validation           # P1
uv run uvicorn app.api.main:app --port 8000 &
curl -s -X POST localhost:8000/visualize -H 'content-type: application/json' \
  -d '{"query":"pembrolizumab trials per year since 2018","options":{"mode":"replay"}}' | head -c 600
```
The CI end-to-end test runs in replay: it can either inject a known `AnalysisPlan` from `fixtures/plans/` (bypassing the planner) plus cached retrieval, or run the full pipeline against the planner's recorded outputs. A separate full-pipeline test is gated on `OPENAI_API_KEY` and network and is opt-in.

## File ownership and boundaries
Owns `app/api/**`, `app/validation/**`, `tests/integration/**`. Imports stage entrypoints from `app.planner`, `app.retrieval`, `app.transform`, `app.viz`, and types from `app.contracts`. Does not modify those worktrees' modules or `app/contracts/**`; if a stage's interface does not fit, flag it rather than editing it. Keep the `/visualize` signature stable.

## Dependencies and chaining
Upstream: merged `contracts`, `retrieval`, `transform`, `viz`, `planner`. Needs the planner's recorded eval outputs and a populated retrieval cache for deterministic replay tests. Blocks `deliverables`. Runs solo.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Comparison `total_matched`: sum vs `None` when mixed | integration | non-blocking (sum when all present, else None) |
| CI e2e: inject plan fixture vs full replay | integration | non-blocking (recommend inject for determinism, plus opt-in full) |
| Map planning failure to 422 vs a 200 with an explanatory body | Taylor | non-blocking (recommend 422) |

## Conductor handoff prompt
```
You are building the "integration" worktree for a ClinicalTrials.gov query-to-visualization backend. It
wires the five existing stages into a working service; write almost no new domain logic. Read
docs/system-design.md (sections 4, 11, 13) and every Phase 1 PRD, then build exactly what
docs/prd-integration.md specifies.

You own app/api/**, app/validation/**, and tests/integration/** only. Import stage entrypoints from
app.planner (plan_query), app.retrieval (retrieve), app.transform (the aggregation functions and
build_cooccurrence_network), app.viz (build_viz), and types from app.contracts. Do not modify those
modules or contracts; flag interface gaps instead.

Build run_pipeline(request, settings) -> VisualizationResponse: call the planner, branch on
plan.operation (comparison -> fan out one sub-plan per series value, retrieve concurrently with
asyncio.gather, pass list[(series_value, studies)] to aggregate_comparison; cooccurrence_network ->
build_cooccurrence_network; else -> dispatch the matching aggregation), call build_viz, then
validate_output, then assemble Meta (echo the plan only when options.debug). Thread options.mode and
force_refresh into retrieve(plan, settings, options). Implement validate_output with the hard checks
(encoding fields present in data, vega_spec.data.values populated, graph edge endpoints exist) and treat
empty-with-warning as a normal 200. Define PipelineError(stage,...) and FastAPI exception handlers
mapping planner->422, retrieval->502, transform/viz/validation->500, and FastAPI body-validation->422,
all emitting the contract ErrorResponse shape. Replace the stub body of POST /visualize with run_pipeline,
keeping the signature and response_model.

The CI end-to-end test runs in replay (no key, no network), injecting a known AnalysisPlan fixture plus
cached retrieval; a full-pipeline test is opt-in behind OPENAI_API_KEY. Acceptance: every command in the
PRD "Verification commands" block passes and every acceptance criterion holds. ruff and mypy on app/api
and app/validation are P1.
```
