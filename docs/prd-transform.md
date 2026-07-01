# PRD: Transform (Phase 1)

**Worktree:** `transform` · **Status:** ready after contracts merges · **Depends on:** `contracts` · **Blocks:** `integration`
**Runs concurrently with:** `retrieval`, `viz`, `planner` · **Read first:** `docs/system-design.md`, `docs/prd-contracts.md`

---

## Problem statement

This worktree turns clean `StudyRecord`s plus an `AnalysisPlan` into a `TidyDataset` or `GraphData`, with provenance attached to every datum. It is pure and deterministic: no I/O, no network, no model. It is where every number in the final output is actually computed, and where the deep-citations bonus is realized by carrying contributing NCT IDs through each aggregation.

## Goals
1. One pure aggregation function per operation, each returning a tidy dataset (or graph) with `Citation`s attached to every datum, node, and edge.
2. Correct, well-documented handling of list-valued fields (multi-count), unparseable dates (excluded with a warning), and empty result sets.
3. A meaningful co-occurrence network (the rubric's high-value differentiator) built with networkx, with optional server-side layout.

## Non-goals
1. **No retrieval.** Inputs are already-fetched `StudyRecord`s. The orchestrator injects them.
2. **No Vega-Lite or spec building.** Output is tidy data / graph data; the viz worktree renders it.
3. **No LLM calls.**
4. **No comparison data fetching.** The orchestrator builds the per-series record sets (see the comparison contract below); this worktree only aggregates them.

## User stories
- As the **viz worktree**, I receive a `TidyDataset` with explicit `dimension_names` and `measure_name` (or a `GraphData`), so I can build encodings without guessing field names.
- As the **grader checking citations**, every bar, bucket, node, and edge carries the NCT IDs and field excerpts that produced it.

---

## Scope and specification

### Module layout (owns `app/transform/**`, `tests/transform/**`)
- `app/transform/aggregations.py` — the per-operation pure functions.
- `app/transform/network.py` — co-occurrence graph construction (networkx).
- `app/transform/provenance.py` — helper to build `Citation`s from `StudyRecord`s.
- `app/transform/__init__.py` — exports the functions and a dispatcher.

### The functions
All are pure and synchronous.

| Operation | Function | Signature (return) |
|---|---|---|
| time_trend | `aggregate_time_trend` | `(studies, plan) -> TidyDataset` |
| categorical_distribution | `aggregate_categorical` | `(studies, plan) -> TidyDataset` |
| comparison | `aggregate_comparison` | `(series_studies, plan) -> TidyDataset` |
| geographic_distribution | `aggregate_geographic` | `(studies, plan) -> TidyDataset` |
| cooccurrence_network | `build_cooccurrence_network` | `(studies, plan) -> GraphData` |
| numeric_distribution | `aggregate_numeric_distribution` | `(studies, plan) -> TidyDataset` |
| numeric_relationship | `aggregate_numeric_relationship` | `(studies, plan) -> TidyDataset` |

`series_studies` for comparison is `list[tuple[str, list[StudyRecord]]]` (series value -> its records), assembled by the orchestrator. A thin `dispatch(plan, payload)` may route by `plan.operation`.

**Comparison contract (document for integration):** for a `comparison` plan, the orchestrator creates one sub-plan per `series.values` entry, injecting the value into the entity slot named by `series.dimension` (`drug` -> `entities.drug`, `condition` -> `entities.condition`, `sponsor` -> `entities.sponsor`), keeping `group_by` and `filters`, retrieves each, and passes the labeled list here.

### Where warnings go
Aggregation warnings (studies excluded for unparseable dates, empty input, list-field multi-count notes) are returned on the result object via `TidyDataset.warnings` / `GraphData.warnings` (both default `[]`). This keeps every function's return type unchanged (`-> TidyDataset` / `-> GraphData`), keeps `build_viz` unaffected, and lets the orchestrator fold these into `meta.warnings` by reading `(graph or dataset).warnings`. Do not raise on excluded dates or empty input; record a one-line warning and return a valid (possibly empty) result.

### Aggregation rules
- **time_trend:** bucket `start_date` by `plan.time_granularity` (year default; month -> `YYYY-MM`). Apply the `filters.start_year`/`end_year` range here. Records with `start_date is None` are excluded and counted in a `warning`. `dims={"year": 2021}` (or `{"period": "2021-03"}`), `measure_name="trial_count"`. Include zero-count periods within the observed range so the line has no gaps.
- **categorical_distribution:** group by `plan.group_by`. For list-valued fields (`phase`, `intervention_type`, `condition`, `country`) a study contributes to every value it has (multi-count); state this in `assumptions` upstream and keep it consistent. `dims={"<field>": value}`, `measure_name="trial_count"`, sorted descending by value at the viz layer.
- **comparison:** within each series value, aggregate by `group_by` as above; tag each point with the series: `dims={"<group_by>": v, "series": series_value}`.
- **geographic_distribution:** group by `country` (multi-count across a trial's countries). `dims={"country": name}`. Keep the raw country name; ISO mapping for choropleth is the viz worktree's concern.
- **numeric_distribution:** bin `plan.numeric_x` (`enrollment_count`, or `duration_days` computed as `completion_date - start_date`). Choose bin width by Freedman-Diaconis with a sane fallback (or ~20 equal-width bins); emit one point per bin: `dims={"bin_start": a, "bin_end": b}`, `value=count`. Skip records missing the numeric.
- **numeric_relationship:** one point per study: `dims={"nct_id": id, "<numeric_x>": x, "<numeric_y>": y}`, `measure_name="study"`, `value=1`. Skip records missing either numeric. (P2; keep simple.)

### Provenance (`provenance.py`)
Every `DataPoint`/`GraphNode`/`GraphEdge` carries `citations`: for each contributing study, a `Citation(nct_id, excerpt, field)` where `excerpt` is the relevant field value (e.g., the phase string, the country, the sponsor name) or the `brief_title` fallback, and `field` is the source path. Total work is bounded by `max_studies`, so include all contributing citations in v1 (a per-datum cap is a P2 payload optimization).

### Network construction (`network.py`)
Build with networkx from `plan.network`:
- **node_types `[sponsor, drug]` (bipartite):** a node per distinct sponsor and per distinct drug (intervention name); an edge between a sponsor and a drug when a trial has both. Edge weight = number of such trials.
- **node_types `[drug]` (drug-drug combinations):** a node per distinct drug; an edge between two drugs co-occurring in the same trial. Edge weight = co-occurrence trial count.
- Apply `min_edge_weight`; cap to the top `max_nodes` by node weight (node weight = trials the node participates in). If `precompute_layout`, run `spring_layout` and set node `x`/`y`, and set `GraphVizSpec.layout` accordingly downstream. Node and edge `citations` carry the contributing NCT IDs.

---

## Requirements

### Must-have (P0)
- [ ] `aggregate_time_trend`, `aggregate_categorical`, `aggregate_comparison` implemented with correct counts and citations.
- [ ] Multi-count semantics for list-valued fields implemented and tested.
- [ ] Unparseable-date exclusion produces a `warning`; empty input produces an empty dataset plus a `warning`, never a crash.
- [ ] `build_cooccurrence_network` produces correct nodes/edges/weights with `min_edge_weight` and `max_nodes` honored and provenance attached.

### Nice-to-have (P1)
- [ ] `aggregate_geographic`, `aggregate_numeric_distribution` implemented.
- [ ] `ruff` + `mypy app/transform` clean.

### Future considerations (P2)
- [ ] `numeric_relationship` polish; per-datum citation caps; additional `Measure`s (`enrollment_sum`).

### Acceptance criteria
- Given 10 `StudyRecord`s where 3 have Phase 2 and 2 have both Phase 2 and Phase 3, When `aggregate_categorical` runs with `group_by=phase`, Then Phase 2 count is 5 and each datum lists exactly its contributing NCT IDs.
- Given records with some `start_date is None`, When `aggregate_time_trend` runs, Then those records are excluded and a `warning` reports the count, and year buckets within range have no gaps.
- Given a network plan with `min_edge_weight=2`, When `build_cooccurrence_network` runs, Then no edge with weight 1 appears and `len(nodes) <= max_nodes`.
- Given an empty `studies` list, When any aggregation runs, Then it returns an empty dataset with a `warning` and raises nothing.

---

## Verification commands
```
uv run pytest tests/transform -q
uv run ruff check app/transform     # P1
uv run mypy app/transform           # P1
```
Tests load `fixtures/raw/study_records.json` (the clean `StudyRecord` fixture from contracts) and assert counts, multi-count behavior, warnings, and network weights. Pure functions, no mocking required.

## File ownership and boundaries
Owns `app/transform/**` and `tests/transform/**`. Imports only from `app.contracts` (plus networkx). Does not modify contracts, retrieval, viz, or api. If `StudyRecord` lacks a needed field, flag a contracts amendment rather than adding it locally.

## Dependencies and chaining
Upstream: merged `contracts` (`StudyRecord`, `AnalysisPlan`, `TidyDataset`, `DataPoint`, `Citation`, `GraphData`/nodes/edges, enums) and `fixtures/raw/study_records.json`. Blocks `integration`. Concurrent with `retrieval`, `viz`, `planner`.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Bin-width strategy for histograms (Freedman-Diaconis vs fixed 20) | transform | non-blocking |
| Include zero-count periods in time series | transform | non-blocking (recommend yes) |
| Per-datum citation cap | Taylor | non-blocking (v1 includes all) |

## Conductor handoff prompt
```
You are building the "transform" worktree for a ClinicalTrials.gov query-to-visualization backend. It is
pure and deterministic: no I/O, no network, no LLM. Read docs/system-design.md (sections 4, 5, 8) and
docs/prd-contracts.md (Sections A, C, D, D2), then build exactly what docs/prd-transform.md specifies.

You own app/transform/** and tests/transform/** only. Import shared types from app.contracts (networkx is
allowed). Do not modify contracts or other worktrees' directories.

Implement one pure function per operation (time_trend, categorical_distribution, comparison,
geographic_distribution, cooccurrence_network, numeric_distribution, numeric_relationship) returning a
TidyDataset or GraphData with Citation provenance on every datum/node/edge. Honor: multi-count for
list-valued fields (phase, intervention_type, condition, country); exclusion of unparseable dates with a
warning; empty-input safety (empty dataset + warning, never a crash); the year-range filter in
time_trend; and the comparison input contract (orchestrator passes list[tuple[series_value, list[StudyRecord]]]).
Build a meaningful co-occurrence network with networkx (bipartite sponsor-drug and drug-drug), honoring
min_edge_weight and max_nodes, with optional spring_layout positions.

Tests load fixtures/raw/study_records.json and assert counts, multi-count behavior, warnings, and network
weights; no mocking needed. Acceptance: every command in the PRD "Verification commands" block passes and
every acceptance criterion holds. ruff and mypy on app/transform are P1.
```
