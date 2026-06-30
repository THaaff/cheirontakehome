# PRD: Contracts and Skeleton (Phase 0)

**Worktree:** `contracts` · **Status:** ready to build · **Depends on:** nothing · **Blocks:** every other worktree
**Read first:** `docs/system-design.md`

---

## Problem statement

Five worktrees are about to build in parallel against each other's interfaces. If those interfaces are not frozen first, every worktree guesses at the shape of the data crossing its boundary, and integration becomes a rewrite. This worktree defines the shared types once, validates them, exports their JSON Schemas, stands up a stub API that returns the real wire shape, and captures real API fixtures so downstream worktrees have something concrete to test against. Until this lands and merges to main, no other worktree starts.

## Goals

1. A frozen `app/contracts/` package: every shared Pydantic v2 model and enum, with the operation-to-required-fields rules enforced by validators.
2. Exported JSON Schemas for the top-level request, response, and error types in `docs/schemas/`, so a frontend engineer can build a renderer with zero guessing.
3. A runnable FastAPI skeleton: `POST /visualize` returns a hardcoded, schema-valid `VisualizationResponse`; `GET /health` returns ok; `/docs` renders the OpenAPI spec.
4. A fixture library that parses cleanly against the models: example requests, plans (one per operation), tidy datasets, and full responses (one per viz type).
5. Real API fixtures captured from a short live spike, plus a notes file documenting confirmed field paths and the stats-filter finding.

## Non-goals

1. **No planner.** No model calls. The stub response is hardcoded from a fixture.
2. **No retrieval.** No HTTP to CT.gov except the one-off spike script.
3. **No transform or aggregation logic.** Tidy fixtures are hand-written.
4. **No viz building logic.** Response fixtures are hand-written and schema-valid.
5. **No business rules beyond contract validators.** This worktree defines shapes and the constraints intrinsic to them, nothing more.

## User stories

These are the consumers of this worktree's output.

- As the **transform worktree**, I need a frozen `TidyDataset`/`DataPoint` model with a citation slot so I can emit aggregated data and provenance without guessing the shape.
- As the **viz worktree**, I need a frozen `VizSpec` discriminated union and `Encoding` model so I can build chart and graph specs that validate.
- As the **planner worktree**, I need a frozen `AnalysisPlan` with enums and validators so I can target the model's structured output at a real schema and know which fields each operation requires.
- As the **retrieval worktree**, I need real captured API responses and a field-path notes file so I can build the query and parsing layer against ground truth, not against the docs alone.
- As the **frontend engineer / grader**, I need exported JSON Schemas and a live `/docs` page so I can understand the I/O without reading Python.
- As the **integration worktree**, I need a stub `POST /visualize` already wired with `response_model` so I can swap in real orchestration without redefining the endpoint.

---

## Scope: deliverables

1. `app/contracts/__init__.py` re-exporting all public models and enums.
2. `app/contracts/enums.py` — all enums (Section A).
3. `app/contracts/request.py` — `VisualizationRequest`, `RequestOptions` (Section B).
4. `app/contracts/plan.py` — `AnalysisPlan` and nested models, with validators (Section C).
5. `app/contracts/data.py` — `Citation`, `DataPoint`, `TidyDataset`, `ChartDatum`, `GraphNode`, `GraphEdge`, `GraphData`, and the retrieval-to-transform interface `StudyRecord` and `RetrievalResult` (Sections D and D2).
6. `app/contracts/viz.py` — `Channel`, `Encoding`, `GraphEncoding`, `VizHints`, `ChartVizSpec`, `GraphVizSpec`, `VizSpec` union (Section E).
7. `app/contracts/response.py` — `Meta`, `VisualizationResponse`, `ErrorDetail`, `ErrorResponse` (Section F).
8. `app/contracts/settings.py` — `Settings` (pydantic-settings) reading env (Section G).
9. `app/api/main.py` — FastAPI skeleton stub (Section H).
10. `scripts/spike_api.py` — live API capture (Section I).
11. `fixtures/**` — example requests, plans, tidy, responses, and `fixtures/raw/notes.md` (Section J).
12. `docs/schemas/*.json` — exported JSON Schemas (Section H, acceptance).
13. `tests/contracts/**` — model and fixture tests (Section K).
14. `pyproject.toml`, `.env.example`, README stub.

---

## Section A: enums (`enums.py`)

Use `enum.StrEnum`. Values that map to the CT.gov API **mirror the API's controlled vocabulary exactly** so no translation layer is needed.

**`Operation`** (the closed query-class set):
`time_trend`, `categorical_distribution`, `comparison`, `geographic_distribution`, `cooccurrence_network`, `numeric_distribution`, `numeric_relationship`

**`VizType`**:
`bar_chart`, `grouped_bar_chart`, `time_series`, `scatter_plot`, `histogram`, `choropleth_map`, `network_graph`

**`CategoricalField`** (dimensions we can group on):
`phase`, `overall_status`, `study_type`, `lead_sponsor_class`, `intervention_type`, `country`, `condition`

**`NumericField`** (for histogram/scatter):
`enrollment_count`, `duration_days`

**`Measure`**:
`trial_count` (default). Reserve `enrollment_sum`, `enrollment_mean` for later; define them but the executor only implements `trial_count` in v1.

**`Phase`** (API values): `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, `NA`

**`OverallStatus`** (API values, common subset): `RECRUITING`, `NOT_YET_RECRUITING`, `ACTIVE_NOT_RECRUITING`, `ENROLLING_BY_INVITATION`, `COMPLETED`, `SUSPENDED`, `TERMINATED`, `WITHDRAWN`, `UNKNOWN`
> Note in a docstring: the authoritative full set comes from the API enums endpoint; the retrieval worktree may extend this.

**`StudyType`** (API values): `INTERVENTIONAL`, `OBSERVATIONAL`, `EXPANDED_ACCESS`

**`SponsorClass`** (API agency-class values): `INDUSTRY`, `NIH`, `FED`, `OTHER_GOV`, `INDIV`, `NETWORK`, `AMBIG`, `OTHER`, `UNKNOWN`

**`InterventionType`** (API values): `DRUG`, `BIOLOGICAL`, `DEVICE`, `PROCEDURE`, `BEHAVIORAL`, `DIETARY_SUPPLEMENT`, `RADIATION`, `GENETIC`, `DIAGNOSTIC_TEST`, `COMBINATION_PRODUCT`, `OTHER`

**`SeriesDimension`**: `drug`, `condition`, `sponsor`

**`NodeType`**: `sponsor`, `drug`, `condition`

**`EdgeSemantics`**: `co_occurrence_in_trial`

**`ChannelType`** (Vega-Lite encoding types): `nominal`, `ordinal`, `quantitative`, `temporal`

**`Renderer`**: `vega-lite`, `vega`, `graph`

**`RequestMode`**: `live`, `replay`

**`PipelineStage`** (for errors): `validation`, `planning`, `retrieval`, `transform`, `visualization`

---

## Section B: request (`request.py`)

**`RequestOptions`**
| Field | Type | Default | Notes |
|---|---|---|---|
| `mode` | `RequestMode` | `live` | `replay` reads cached responses + recorded plans |
| `max_studies` | `int` | `2000` | page-budget cap for client-side aggregation; validate 1..10000 |
| `force_refresh` | `bool` | `false` | bypass cache in live mode |
| `debug` | `bool` | `false` | when true, echo the `AnalysisPlan` in `meta.plan` |

**`VisualizationRequest`**
| Field | Type | Required | Validation |
|---|---|---|---|
| `query` | `str` | yes | strip; min length 1 |
| `drug_name` | `str \| None` | no | optional hint to the planner |
| `condition` | `str \| None` | no | optional hint |
| `sponsor` | `str \| None` | no | optional hint |
| `phase` | `Phase \| None` | no | optional hint |
| `country` | `str \| None` | no | optional hint |
| `start_year` | `int \| None` | no | 1900..2100 |
| `end_year` | `int \| None` | no | 1900..2100; if both set, `start_year <= end_year` (model validator) |
| `options` | `RequestOptions` | no | defaults to `RequestOptions()` |

The optional structured fields are hints. The planner may use them to disambiguate; they do not bypass the planner.

---

## Section C: the AnalysisPlan IR (`plan.py`)

This is the central object. Nested models first.

**`Entities`**
| Field | Type | Notes |
|---|---|---|
| `drug` | `str \| None` | maps to `query.intr` |
| `condition` | `str \| None` | maps to `query.cond` |
| `sponsor` | `str \| None` | maps to `query.spons` |
| `terms` | `list[str]` | general terms -> `query.term`; default `[]` |

**`Filters`**
| Field | Type | Notes |
|---|---|---|
| `statuses` | `list[OverallStatus]` | default `[]` -> `filter.overallStatus` |
| `phases` | `list[Phase]` | default `[]` -> `filter.phase` |
| `study_type` | `StudyType \| None` | |
| `countries` | `list[str]` | default `[]` |
| `start_year` | `int \| None` | applied during transform (date bucketing), not always server-side |
| `end_year` | `int \| None` | |

**`SeriesSpec`** (for comparisons)
| Field | Type | Notes |
|---|---|---|
| `dimension` | `SeriesDimension` | the thing being compared (e.g., condition) |
| `values` | `list[str]` | the compared values (e.g., `["melanoma","lung cancer"]`); min length 2 |

**`NetworkSpec`** (for co-occurrence)
| Field | Type | Default | Notes |
|---|---|---|---|
| `node_types` | `list[NodeType]` | | `[sponsor, drug]` for bipartite, `[drug]` for drug-drug |
| `edge_semantics` | `EdgeSemantics` | `co_occurrence_in_trial` | |
| `min_edge_weight` | `int` | `1` | drop edges below this trial count |
| `max_nodes` | `int` | `50` | readability/perf cap; validate 2..200 |
| `precompute_layout` | `bool` | `true` | server-side `spring_layout` |

**`AnalysisPlan`**
| Field | Type | Default | Notes |
|---|---|---|---|
| `operation` | `Operation` | | the query class |
| `entities` | `Entities` | `Entities()` | |
| `filters` | `Filters` | `Filters()` | |
| `group_by` | `CategoricalField \| None` | | the categorical axis for distribution/comparison |
| `series` | `SeriesSpec \| None` | | required for `comparison` |
| `numeric_x` | `NumericField \| None` | | required for `numeric_distribution` and `numeric_relationship` |
| `numeric_y` | `NumericField \| None` | | required for `numeric_relationship` |
| `time_granularity` | `Literal["year","month"]` | `year` | for `time_trend` |
| `measure` | `Measure` | `trial_count` | |
| `network` | `NetworkSpec \| None` | | required for `cooccurrence_network` |
| `proposed_viz` | `VizType` | | the planner's suggestion |
| `interpretation` | `str` | | one-sentence restatement, surfaced in `meta.query_interpretation` |
| `assumptions` | `list[str]` | `[]` | e.g., "interpreted 'recent' as since 2021" |

**Operation-to-required-fields matrix (enforce with a `model_validator`):**

| Operation | Requires | Sets `proposed_viz` to |
|---|---|---|
| `time_trend` | (nothing beyond entities/filters) | `time_series` |
| `categorical_distribution` | `group_by` | `bar_chart` |
| `comparison` | `group_by` and `series` | `grouped_bar_chart` |
| `geographic_distribution` | `group_by == country` | `choropleth_map` |
| `cooccurrence_network` | `network` | `network_graph` |
| `numeric_distribution` | `numeric_x` | `histogram` |
| `numeric_relationship` | `numeric_x` and `numeric_y` | `scatter_plot` |

The validator raises a `ValueError` (surfaced as a pydantic `ValidationError`) when a required field for the chosen operation is missing. This is a core "validation/constraints" rubric win: an invalid plan cannot be constructed.

---

## Section D: data and provenance (`data.py`)

**`Citation`** (the deep-citation unit)
| Field | Type | Notes |
|---|---|---|
| `nct_id` | `str` | e.g., `NCT01234567` |
| `excerpt` | `str` | exact text or field value from the API response supporting the datum |
| `field` | `str \| None` | source field path, e.g., `protocolSection.designModule.phases` |

**`DataPoint`** (internal tidy unit, transform layer)
| Field | Type | Notes |
|---|---|---|
| `dims` | `dict[str, str \| int \| float]` | e.g., `{"phase":"PHASE3"}` or `{"year":2021,"series":"melanoma"}` |
| `measure` | `str` | measure name, e.g., `trial_count` |
| `value` | `float` | the computed value |
| `citations` | `list[Citation]` | default `[]` |

**`TidyDataset`**
| Field | Type | Notes |
|---|---|---|
| `points` | `list[DataPoint]` | |
| `dimension_names` | `list[str]` | the dim keys present, for the viz layer |
| `measure_name` | `str` | |

**`ChartDatum`** (wire form for chart `data`): a model with `model_config = ConfigDict(extra="allow")` and one explicit field `citations: list[Citation] = []`. Dimension and measure keys live in the allowed extras, so a record serializes as e.g. `{"phase":"PHASE3","trial_count":78,"citations":[...]}`. Vega-Lite ignores the `citations` key.

**`GraphNode`**
| Field | Type | Notes |
|---|---|---|
| `id` | `str` | stable id, e.g., `drug:pembrolizumab` |
| `label` | `str` | display label |
| `type` | `NodeType` | |
| `weight` | `float` | e.g., trial count the node participates in |
| `x` | `float \| None` | precomputed layout coord (optional) |
| `y` | `float \| None` | |
| `citations` | `list[Citation]` | default `[]` |

**`GraphEdge`**
| Field | Type | Notes |
|---|---|---|
| `source` | `str` | node id |
| `target` | `str` | node id |
| `weight` | `float` | co-occurrence trial count |
| `citations` | `list[Citation]` | default `[]` |

**`GraphData`**: `{ nodes: list[GraphNode], edges: list[GraphEdge] }`

### Section D2: retrieval-to-transform interface

These two models cross the retrieval/transform boundary, so they must be frozen here for those worktrees to build in parallel. The retrieval worktree owns the parsing from raw API JSON into `StudyRecord` (centralizing all API-shape and messy-data handling); the transform worktree consumes clean typed records.

**`StudyRecord`** (one flat, normalized study; built by retrieval, consumed by transform)
| Field | Type | Notes |
|---|---|---|
| `nct_id` | `str` | `protocolSection.identificationModule.nctId` |
| `brief_title` | `str \| None` | used as a citation excerpt fallback |
| `phases` | `list[Phase]` | parsed from `designModule.phases`; may be empty |
| `overall_status` | `OverallStatus \| None` | |
| `study_type` | `StudyType \| None` | |
| `lead_sponsor_name` | `str \| None` | |
| `lead_sponsor_class` | `SponsorClass \| None` | |
| `start_date` | `datetime.date \| None` | tolerant-parsed; `None` if unparseable |
| `start_date_raw` | `str \| None` | the original string, for excerpts and debugging |
| `completion_date` | `datetime.date \| None` | tolerant-parsed |
| `intervention_types` | `list[InterventionType]` | may be empty |
| `intervention_names` | `list[str]` | may be empty |
| `conditions` | `list[str]` | may be empty |
| `countries` | `list[str]` | deduped from `locations[].country`; may be empty |
| `enrollment_count` | `int \| None` | from `designModule.enrollmentInfo.count` |

`StudyRecord` should be tolerant: every list defaults to `[]`, every scalar is nullable. It never raises on missing API fields; absence becomes null/empty. This is where the "real-world data handling" rubric credit is earned.

**`RetrievalResult`** (returned by the retrieval entrypoint)
| Field | Type | Notes |
|---|---|---|
| `studies` | `list[StudyRecord]` | the (projected, normalized) records |
| `total_matched` | `int \| None` | from the API `countTotal` when available |
| `studies_analyzed` | `int` | how many records were actually fetched and parsed |
| `data_timestamp` | `str \| None` | CT.gov `dataTimestamp` at fetch time |
| `warnings` | `list[str]` | e.g., parse failures, truncation at `max_studies` |

Both live in `app/contracts/data.py` and are re-exported from `__init__.py`. Transform consumes `list[StudyRecord]`; the scalar fields on `RetrievalResult` flow through the orchestrator into `Meta`.

---

## Section E: visualization spec (`viz.py`)

**`Channel`**
| Field | Type | Notes |
|---|---|---|
| `field` | `str` | the data field this channel reads |
| `type` | `ChannelType` | `nominal`/`ordinal`/`quantitative`/`temporal` |
| `title` | `str \| None` | axis/legend title |
| `sort` | `str \| list[str] \| None` | optional sort directive |

**`Encoding`** (chart semantic layer; matches the assignment's `encoding`)
| Field | Type | Notes |
|---|---|---|
| `x` | `Channel` | |
| `y` | `Channel` | |
| `color` | `Channel \| None` | the series channel for grouped/comparison |
| `column` | `Channel \| None` | optional facet |
| `size` | `Channel \| None` | optional |

**`GraphEncoding`** (documents node/edge channel mapping; fixed fields with defaults)
| Field | Type | Default |
|---|---|---|
| `node_id` | `str` | `id` |
| `node_label` | `str` | `label` |
| `node_group` | `str` | `type` |
| `node_size` | `str` | `weight` |
| `edge_source` | `str` | `source` |
| `edge_target` | `str` | `target` |
| `edge_weight` | `str` | `weight` |

**`VizHints`**
| Field | Type | Notes |
|---|---|---|
| `sort` | `str \| None` | e.g., `-y` for descending bars |
| `x_time_unit` | `str \| None` | e.g., `year` |
| `units` | `str \| None` | e.g., `trials` |
| `note` | `str \| None` | free-text rendering hint |

**`ChartVizSpec`**
| Field | Type | Notes |
|---|---|---|
| `kind` | `Literal["chart"]` | discriminator |
| `renderer` | `Renderer` | `vega-lite` or `vega` |
| `type` | `VizType` | |
| `title` | `str` | |
| `encoding` | `Encoding` | |
| `data` | `list[ChartDatum]` | |
| `vega_spec` | `dict` | concrete embedded Vega-Lite/Vega spec with data inlined under `data.values` |
| `hints` | `VizHints` | default `VizHints()` |

**`GraphVizSpec`**
| Field | Type | Notes |
|---|---|---|
| `kind` | `Literal["graph"]` | discriminator |
| `renderer` | `Literal[Renderer.graph]` | fixed `graph` |
| `type` | `Literal[VizType.network_graph]` | |
| `title` | `str` | |
| `encoding` | `GraphEncoding` | |
| `data` | `GraphData` | |
| `layout` | `Literal["precomputed","force"]` | `precomputed` if `x`/`y` set, else `force` |
| `hints` | `VizHints` | default `VizHints()` |

**`VizSpec`**: `Annotated[Union[ChartVizSpec, GraphVizSpec], Field(discriminator="kind")]`.

Rationale for the discriminator on `kind` rather than `renderer`: `renderer` has two values that both belong to `ChartVizSpec` (`vega-lite`, `vega`), so it cannot be a unique discriminator. `kind` is unique per member. See system-design.md, decision table.

---

## Section F: response and errors (`response.py`)

**`Meta`**
| Field | Type | Notes |
|---|---|---|
| `source` | `str` | default `"clinicaltrials.gov"` |
| `query_interpretation` | `str` | from `AnalysisPlan.interpretation` |
| `assumptions` | `list[str]` | default `[]` |
| `filters_applied` | `dict[str, Any]` | the concrete filters used |
| `total_studies_matched` | `int \| None` | from `countTotal` when available |
| `studies_analyzed` | `int` | how many records the aggregation actually consumed |
| `data_timestamp` | `str \| None` | CT.gov `dataTimestamp` |
| `warnings` | `list[str]` | default `[]`; e.g., "312 studies had unparseable start dates and were excluded" |
| `plan` | `AnalysisPlan \| None` | populated only when `options.debug` is true |

**`VisualizationResponse`**
| Field | Type | Notes |
|---|---|---|
| `request_id` | `str` | uuid4 string |
| `visualization` | `VizSpec` | |
| `meta` | `Meta` | |

**`ErrorDetail`**
| Field | Type | Notes |
|---|---|---|
| `type` | `str` | short machine code, e.g., `upstream_unavailable` |
| `stage` | `PipelineStage` | where it failed |
| `message` | `str` | human-readable |
| `details` | `dict[str, Any] \| None` | optional context |

**`ErrorResponse`**: `{ request_id: str, error: ErrorDetail }`

**HTTP status mapping (document in docstrings; integration enforces):** 200 success (including empty result sets, which carry a `warnings` entry rather than failing); 422 validation/planning input errors; 502 upstream CT.gov failures; 500 internal.

---

## Section G: settings (`settings.py`)

`Settings` via `pydantic-settings`, reading: `OPENAI_API_KEY` (str, no default, optional at import so replay mode works without it), `CTGOV_BASE_URL` (default `https://clinicaltrials.gov/api/v2`), `CACHE_DIR` (default `.cache`), `PLANNER_MODEL` (default `gpt-4.1`), `DEFAULT_MODE` (`RequestMode`, default `live`). Never raise at import for a missing key; the planner worktree raises a clear error only when a live planner call is actually attempted.

---

## Section H: FastAPI skeleton (`api/main.py`)

- Create the app with title and description (the description becomes the OpenAPI summary the grader sees).
- Permissive CORS (allow all origins) so the optional demo page can call it.
- `GET /health` -> `{"status": "ok"}`.
- `POST /visualize` typed with `VisualizationRequest` as the body and `response_model=VisualizationResponse`. For now it ignores the body and returns a hardcoded response loaded from `fixtures/responses/bar_chart_phases.json`. Add a docstring stating this is a Phase 0 stub to be replaced during integration.
- A module-level guard so `uvicorn app.api.main:app` runs.

Acceptance includes a small script or test that calls `model_json_schema()` on `VisualizationRequest`, `VisualizationResponse`, and `ErrorResponse` and writes them to `docs/schemas/{name}.json`.

---

## Section I: API spike (`scripts/spike_api.py`)

A standalone script (no API key needed; CT.gov is keyless) that:
1. Hits `GET /studies?query.intr=pembrolizumab&fields=NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,LeadSponsorClass,StartDate,LocationCountry&pageSize=50&countTotal=true&format=json` and saves the raw JSON to `fixtures/raw/studies_pembrolizumab.json`.
2. Hits a condition query (e.g., `query.cond=melanoma`, same fields, `pageSize=50`) and saves to `fixtures/raw/studies_melanoma.json`.
3. Fetches one full study record `GET /studies/{nctId}` and saves to `fixtures/raw/study_full.json`.
4. Probes whether `/stats/field/values?fields=Phase` accepts an additional `query.cond=melanoma` and whether the returned counts change; record the finding.
5. Hits `GET /version` and records `dataTimestamp`.
6. Writes `fixtures/raw/notes.md` documenting the confirmed exact field paths (casing included) for every field the transform layer needs, plus the stats-filter finding and the `pageSize`/`pageToken` behavior observed.

If the network is unavailable, the script must fail with a clear message; do not fabricate fixture data.

---

## Section J: fixtures (`fixtures/**`)

Hand-write these so they parse against the models (the tests in Section K validate them):
- `fixtures/requests/example_bar.json`, `example_time_series.json`, `example_comparison.json`.
- `fixtures/plans/{time_trend,categorical_distribution,comparison,geographic_distribution,cooccurrence_network,numeric_distribution,numeric_relationship}.json` — one valid `AnalysisPlan` each.
- `fixtures/tidy/{bar,time_series,comparison,network}.json` — example `TidyDataset` (and a `GraphData` for network).
- `fixtures/raw/study_records.json` — a hand-derived list of ~10 `StudyRecord` objects (normalized from the raw spike capture). This is the clean fixture the transform and viz worktrees test against, so it must validate against `StudyRecord`.
- `fixtures/responses/{bar_chart_phases,time_series_drug,grouped_bar_comparison,network_sponsors_drugs}.json` — full `VisualizationResponse`, schema-valid. `bar_chart_phases.json` is the one the stub endpoint serves.
- `fixtures/raw/**` — produced by the spike script.

Make the example values realistic (real-looking NCT IDs, plausible phase counts) so the fixtures double as demo data.

---

## Section K: tests (`tests/contracts/**`)

- **Round-trip:** each top-level model serializes to JSON and re-parses to an equal object.
- **Validator enforcement (negative tests):** constructing a `comparison` plan without `series` raises `ValidationError`; `numeric_relationship` without `numeric_y` raises; `end_year < start_year` raises; `query=""` raises.
- **Discriminated union:** a `ChartVizSpec` dict parses to `ChartVizSpec` and a `GraphVizSpec` dict to `GraphVizSpec` via the `VizSpec` adapter.
- **Fixture validity:** every file in `fixtures/plans`, `fixtures/tidy`, `fixtures/responses` loads and validates against its model. Parametrize over the directory.
- **Schema export:** `model_json_schema()` succeeds for request/response/error and the files land in `docs/schemas/`.
- **`extra="allow"` behavior:** a `ChartDatum` accepts arbitrary dimension keys plus a typed `citations` list.

---

## Requirements

### Must-have (P0)
- [ ] All models in Sections A to G implemented in `app/contracts/` and re-exported from `__init__.py`.
- [ ] The operation-to-required-fields validator (Section C matrix) enforced and covered by negative tests.
- [ ] `VizSpec` discriminated union resolves correctly to both members.
- [ ] FastAPI skeleton runs; `/health`, `POST /visualize` (stub), and `/docs` all work.
- [ ] JSON Schemas exported to `docs/schemas/`.
- [ ] Spike script captures real fixtures and writes `notes.md` with confirmed field paths and the stats-filter finding.
- [ ] All fixtures validate; `pytest` green.

### Nice-to-have (P1)
- [ ] `ruff check` and `mypy app/contracts` clean.
- [ ] A `make`-style task runner or `uv run` scripts documented in the README stub.

### Future considerations (P2)
- [ ] `enrollment_sum` / `enrollment_mean` measures (defined now, implemented later).
- [ ] A `vega` (non-Lite) renderer path (the union already permits it).

### Acceptance criteria (Given/When/Then)
- Given a `comparison` operation, When an `AnalysisPlan` is built without `series`, Then construction raises `ValidationError`.
- Given the stub server is running, When a client POSTs any valid `VisualizationRequest` to `/visualize`, Then it receives a 200 with a body that validates against `VisualizationResponse`.
- Given the spike script has run, When a developer opens `fixtures/raw/notes.md`, Then every field path in the system-design field list is present with confirmed casing, and the stats-filter question is answered yes or no.
- Given a fresh checkout, When a developer runs the setup and test commands below, Then everything passes with no manual steps.

---

## Verification commands

```
uv sync
uv run python -c "from app.contracts import *; print('contracts import ok')"
uv run pytest -q
uv run ruff check .            # P1
uv run mypy app/contracts      # P1
uv run python scripts/spike_api.py
uv run uvicorn app.api.main:app --port 8000 &
curl -s localhost:8000/health
curl -s -X POST localhost:8000/visualize -H 'content-type: application/json' -d @fixtures/requests/example_bar.json | head -c 400
```

---

## File ownership and boundaries

This worktree owns and may create: `app/contracts/**`, `app/api/**` (skeleton only), `fixtures/**`, `docs/schemas/**`, `scripts/spike_api.py`, `tests/contracts/**`, `pyproject.toml`, `.env.example`, README stub.

Do not implement planner, retrieval, transform, or viz logic. The `app/api/main.py` stub will have its internals replaced by the integration worktree in Phase 2; keep the endpoint signature and `response_model` stable so that swap is clean.

---

## Dependencies and chaining

- **Upstream:** none.
- **Blocks:** `retrieval`, `transform`, `viz`, `planner`, `integration`, `demo`. All of them import `app.contracts` and several test against `fixtures/`.
- **Merge gate:** this worktree must be merged to main before any Phase 1 worktree starts. That is the whole point of Phase 0.

---

## Open questions

| Question | Owner | Blocking? |
|---|---|---|
| uv vs pip/poetry | Taylor | non-blocking (PRD assumes uv; pip fallback fine) |
| Python 3.12 confirmed | Taylor | non-blocking |
| ruff + mypy in the gate now (P1) or later | Taylor | non-blocking |
| Fresh repo, or slot into an existing scaffold | Taylor | blocking for kickoff |
| Keep `meta.plan` debug echo, or drop it | Taylor | non-blocking (recommend keep) |

---

## Conductor handoff prompt

Paste this into the `contracts` worktree.

```
You are building the Phase 0 "contracts" worktree for a ClinicalTrials.gov query-to-visualization
backend. This worktree freezes the shared types every other worktree will import; do not implement
planner, retrieval, transform, or visualization logic.

First, read docs/system-design.md (architecture, the external API cheat sheet, repo layout) and
docs/prd-contracts.md (your full spec). The PRD is authoritative for every model, enum, field, and
validator. Build exactly what Sections A through K specify.

Stack: Python 3.12, Pydantic v2, FastAPI, pydantic-settings, httpx (spike script only), pytest;
ruff and mypy as a P1 gate; uv for env and deps.

Deliver:
1. app/contracts/ with enums.py, request.py, plan.py, data.py, viz.py, response.py, settings.py,
   and __init__.py re-exporting all public symbols. Enforce the operation-to-required-fields
   validator from PRD Section C. Implement VizSpec as a discriminated union on `kind`.
2. app/api/main.py: a FastAPI skeleton with GET /health, POST /visualize (typed with
   response_model=VisualizationResponse, returning the hardcoded fixtures/responses/bar_chart_phases.json),
   and working /docs. This stub is replaced later during integration; keep the signature stable.
3. scripts/spike_api.py per Section I: capture real CT.gov v2 responses to fixtures/raw/, probe the
   /stats filter question, fetch the version dataTimestamp, and write fixtures/raw/notes.md with
   confirmed field paths. CT.gov needs no API key. Fail loudly if offline; never fabricate data.
4. fixtures/ per Section J (hand-written, realistic, schema-valid), and docs/schemas/*.json exported
   via model_json_schema().
5. tests/contracts/ per Section K, including negative validator tests and fixture-validity tests
   parametrized over the fixture directories.

Acceptance: every command in the PRD "Verification commands" block passes on a fresh checkout with
no manual steps; pytest is green; the validator rejects the invalid plans listed in the acceptance
criteria; notes.md answers the stats-filter question.

Constraints: mirror the CT.gov controlled vocabularies exactly in the API-facing enums. Never raise
at import for a missing OPENAI_API_KEY. Stay within the files listed in "File ownership"; do not
touch other worktrees' directories.
```
