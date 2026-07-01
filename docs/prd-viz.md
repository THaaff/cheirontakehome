# PRD: Visualization Builder (Phase 1)

**Worktree:** `viz` · **Status:** ready after contracts merges · **Depends on:** `contracts` · **Blocks:** `integration`
**Runs concurrently with:** `retrieval`, `transform`, `planner` · **Read first:** `docs/system-design.md`, `docs/prd-contracts.md`

---

## Problem statement

This worktree turns a `TidyDataset` or `GraphData` plus an `AnalysisPlan` into a `VizSpec`: the semantic encoding the assignment requires (`type`/`title`/`encoding`/`data`) plus a concrete, ready-to-render embedded spec (Vega-Lite for charts, an own nodes/edges spec for networks), with per-datum citations preserved. It is deterministic and built around a registry so adding a chart type is one entry, not a pipeline change. This is where the "breadth without one-off hacks" and "frontend-friendly I/O" rubric credit is earned.

## Goals
1. A viz registry keyed by viz type, with one builder per type, dispatched by a viz type derived from `plan.operation` (authoritative; `plan.proposed_viz` is advisory).
2. Every chart builder emits a valid Vega-Lite v5 spec with data inlined under `data.values`, plus a matching semantic `Encoding`, plus citations carried on each `ChartDatum`.
3. A network builder that emits a `GraphVizSpec` (nodes/edges, optional precomputed layout) renderable without Vega-Lite.

## Non-goals
1. **No data fetching or aggregation.** Inputs are already-aggregated tidy/graph data.
2. **No LLM calls.**
3. **No frontend application.** The optional demo page is a separate worktree.
4. **No reliance on `proposed_viz`** for correctness; derive the viz type from the operation.

## User stories
- As the **frontend engineer / grader**, I get a spec I can drop into `vega-embed` (charts) or a documented nodes/edges renderer (network) without guessing.
- As the **integration worktree**, I call one `build_viz(data, plan) -> VizSpec` and get a schema-valid spec back.

---

## Scope and specification

### Module layout (owns `app/viz/**`, `tests/viz/**`)
- `app/viz/registry.py` — `VIZ_BUILDERS: dict[VizType, Callable]` and `build_viz(data, plan) -> VizSpec`.
- `app/viz/charts.py` — chart builders (bar, grouped bar, time series, scatter, histogram, choropleth).
- `app/viz/network.py` — the network builder.
- `app/viz/vega_templates.py` — hand-built Vega-Lite v5 spec dicts (no extra dependency; transparent and controllable).
- `app/viz/__init__.py` — exports `build_viz`.

### Viz-type derivation
`build_viz` maps `plan.operation` to the authoritative `VizType` (per the contracts operation matrix), then dispatches through the registry. `geographic_distribution` maps to `choropleth_map` with a documented fallback to a ranked `bar_chart` when country names cannot be mapped to geo ids (see below).

### Chart builders (each returns a `ChartVizSpec`)
For each: flatten `TidyDataset` points into `ChartDatum` records (dimension keys + the measure key + `citations`), set the semantic `Encoding` (channels with `field`/`type`/`title`), and build the embedded Vega-Lite dict with the same records inlined under `data.values`. `ChartDatum` is `extra="allow"`, so dimension/measure fields sit alongside `citations`, which Vega-Lite ignores.

| Viz type | Mark / encoding | Notes |
|---|---|---|
| `bar_chart` | `bar`; x = group field (nominal), y = trial_count (quantitative) | sort `-y` |
| `grouped_bar_chart` | `bar`; x = group field, y = count, color = series; `xOffset` by series | from comparison datasets |
| `time_series` | `line` (or area); x = period (temporal), y = count | set time unit from `time_granularity` |
| `histogram` | `bar`; x = bin range (ordinal/quantitative), y = count | bins pre-computed in transform |
| `scatter_plot` | `point`; x = numeric_x (quantitative), y = numeric_y (quantitative) | one mark per study; P2 |
| `choropleth_map` | `geoshape`; color = count | see geo note |

**Geo note:** CT.gov gives country *names*; Vega-Lite choropleth keys on geo ids. Map names to ISO/topojson ids via a small lookup; reference a world topojson (e.g., the standard vega world-110m). When a country name does not resolve, fall back to a ranked `bar_chart` of counts by country and set a `VizHints.note` explaining the fallback. Keep geo P1 and the fallback always available.

### Network builder (returns a `GraphVizSpec`)
Pass `GraphData` straight through into `GraphVizSpec` with the fixed `GraphEncoding` (id/label/type/weight, source/target/weight). Set `layout="precomputed"` when nodes carry `x`/`y` (from transform's `spring_layout`), else `"force"` to signal the frontend should lay it out. Carry node/edge citations unchanged.

### Titles and hints
Generate a human-readable `title` from the plan (e.g., "Annual pembrolizumab trials since 2018", "Lead sponsor class by condition"). Populate `VizHints` (`sort`, `x_time_unit`, `units`, optional `note`).

---

## Requirements

### Must-have (P0)
- [ ] Registry + `build_viz` deriving viz type from `plan.operation`.
- [ ] `bar_chart`, `grouped_bar_chart`, `time_series` builders emitting valid Vega-Lite v5 with inlined data and matching `Encoding`, citations preserved on each datum.
- [ ] `network_graph` builder emitting a valid `GraphVizSpec` with correct `layout` flag and preserved citations.
- [ ] Every builder's output validates against the `VizSpec` discriminated union.

### Nice-to-have (P1)
- [ ] `choropleth_map` with the ranked-bar fallback; `histogram`.
- [ ] `ruff` + `mypy app/viz` clean.

### Future considerations (P2)
- [ ] `scatter_plot` polish; richer Vega (force layout) as an alternate renderer; theming.

### Acceptance criteria
- Given a `TidyDataset` of phase counts, When `build_viz` runs for a `categorical_distribution` plan, Then it returns a `ChartVizSpec` with `type==bar_chart`, `encoding.x.field` equal to the dimension name, `vega_spec["data"]["values"]` equal to the records, and each record carrying its `citations`.
- Given a comparison dataset with a `series` dimension, When `build_viz` runs, Then `encoding.color` is set to the series field and the Vega-Lite spec groups bars by series.
- Given `GraphData` with precomputed `x`/`y`, When `build_viz` runs for `cooccurrence_network`, Then it returns a `GraphVizSpec` with `layout=="precomputed"` and node/edge citations preserved.
- Given a choropleth where a country name does not resolve to a geo id, When `build_viz` runs, Then it returns a ranked `bar_chart` with a `VizHints.note` explaining the fallback.
- Given any builder output, When validated, Then it parses as a `VizSpec` and `encoding` fields all exist in `data`.

---

## Verification commands
```
uv run pytest tests/viz -q
uv run ruff check app/viz     # P1
uv run mypy app/viz           # P1
```
Tests load `fixtures/tidy/*.json` and the network fixture and assert: output validates as `VizSpec`; encoding field names exist in the data records; `vega_spec` has non-empty `data.values`; citations survive. Optionally validate `vega_spec` against the Vega-Lite JSON Schema with `jsonschema` (P1).

## File ownership and boundaries
Owns `app/viz/**` and `tests/viz/**`. Imports only from `app.contracts`. Does not modify contracts, retrieval, transform, or api. If a spec field is missing from the contracts, flag an amendment rather than adding it locally.

## Dependencies and chaining
Upstream: merged `contracts` (`TidyDataset`, `ChartDatum`, `GraphData`, `Encoding`/`GraphEncoding`, `VizSpec` union, `VizHints`, enums) and `fixtures/tidy/`. Blocks `integration`. Concurrent with `retrieval`, `transform`, `planner`.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Hand-built Vega-Lite dicts vs generating via altair | viz | non-blocking (recommend hand-built) |
| Which world topojson source for choropleth | viz | non-blocking (standard vega world-110m) |
| Validate `vega_spec` against the Vega-Lite schema in CI | viz | non-blocking (P1) |

## Conductor handoff prompt
```
You are building the "viz" worktree for a ClinicalTrials.gov query-to-visualization backend. It is
deterministic: no I/O, no LLM. Read docs/system-design.md (sections 4, 6, 8) and docs/prd-contracts.md
(Sections A, D, E), then build exactly what docs/prd-viz.md specifies.

You own app/viz/** and tests/viz/** only. Import shared types from app.contracts. Do not modify contracts
or other worktrees' directories.

Build a viz registry (dict keyed by VizType) and build_viz(data, plan) -> VizSpec that derives the
authoritative viz type from plan.operation (proposed_viz is advisory). Chart builders flatten TidyDataset
points into ChartDatum records (dimension + measure fields plus citations), set the semantic Encoding, and
emit a hand-built Vega-Lite v5 spec with the same records inlined under data.values: bar_chart,
grouped_bar_chart (color=series, xOffset), time_series (time unit from time_granularity), plus histogram
and choropleth (P1; choropleth maps country names to geo ids with a ranked-bar fallback when unmapped).
The network builder passes GraphData into a GraphVizSpec with the fixed GraphEncoding and sets
layout="precomputed" when nodes have x/y else "force", preserving citations. Generate readable titles and
VizHints.

Tests load fixtures/tidy/*.json and the network fixture and assert the output validates as VizSpec, that
encoding fields exist in the data, that vega_spec.data.values is populated, and that citations survive;
optionally validate vega_spec against the Vega-Lite JSON Schema. Acceptance: every command in the PRD
"Verification commands" block passes and every acceptance criterion holds. ruff and mypy on app/viz are P1.
```
