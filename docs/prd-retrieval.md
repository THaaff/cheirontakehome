# PRD: Retrieval (Phase 1)

**Worktree:** `retrieval` · **Status:** ready after contracts merges · **Depends on:** `contracts` · **Blocks:** `integration`
**Runs concurrently with:** `transform`, `viz`, `planner` · **Read first:** `docs/system-design.md`, `docs/prd-contracts.md`

---

## Problem statement

The system needs real trial records to aggregate. This worktree turns an `AnalysisPlan` into ClinicalTrials.gov v2 API calls, pages through results, normalizes the messy response into clean `StudyRecord` objects, and returns a `RetrievalResult`. It is the only component that touches the external API, so it owns all API-shape knowledge, all messy-data handling, pagination, retries, and caching. It does not aggregate or visualize.

## Goals
1. A single async entrypoint `retrieve(plan, settings) -> RetrievalResult` that is correct against the live API and fully testable offline.
2. Robust handling of the documented real-world data problems (null/empty arrays, unnormalized dates) so downstream stages receive clean typed records.
3. Bounded, polite API usage: projection pushdown, a `max_studies` page budget, retries with backoff, and a cache that makes example runs deterministic and key-free.
4. `replay` mode that reads only from cache, so graders without network can reproduce outputs.

## Non-goals
1. **No aggregation.** Counting, bucketing, and co-occurrence are the transform worktree's job.
2. **No LLM calls.** Retrieval is fully deterministic.
3. **No server-side date math.** Year ranges are applied later in transform (which parses dates anyway). See the filter-locus rule below.
4. **No comparison fan-out.** Retrieval handles one plan (one parameter set) per call. The orchestrator issues multiple calls for comparisons.

## User stories
- As the **transform worktree**, I receive a `list[StudyRecord]` with parsed dates and null-safe lists, so I can aggregate without reparsing API JSON.
- As the **integration worktree**, I get a `RetrievalResult` whose scalar fields (`total_matched`, `data_timestamp`, `warnings`) drop straight into `Meta`.
- As a **grader without network**, I run any example in `replay` mode and get the same records the author saw.

---

## Scope and specification

### Module layout (this worktree owns `app/retrieval/**`, `tests/retrieval/**`)
- `app/retrieval/client.py` — async HTTP client, pagination, retries.
- `app/retrieval/query_builder.py` — `AnalysisPlan` -> CT.gov query params.
- `app/retrieval/parsing.py` — raw study dict -> `StudyRecord`; `parse_loose_date`.
- `app/retrieval/cache.py` — file-based cache, live/replay/force_refresh.
- `app/retrieval/__init__.py` — exports `retrieve`.

### Entrypoint
```python
async def retrieve(
    plan: AnalysisPlan,
    settings: Settings,
    options: RequestOptions,
    *,
    client: httpx.AsyncClient | None = None,
) -> RetrievalResult: ...
```
`options` supplies the per-request knobs this stage needs: `mode` (live/replay), `force_refresh`, and `max_studies`. Inject `client` for testing; create one internally if not provided.

### Query building (`AnalysisPlan` -> params)
Server-side params on `GET /studies`:

| Plan field | API param | Notes |
|---|---|---|
| `entities.drug` | `query.intr` | intervention search |
| `entities.condition` | `query.cond` | |
| `entities.sponsor` | `query.spons` | |
| `entities.terms` | `query.term` | join terms |
| `filters.statuses` | `filter.overallStatus` | multi-value; confirm separator from spike notes |
| `filters.phases` | `filter.phase` | multi-value |
| `filters.study_type` | `filter.*` if a clean param exists | else client-side post-filter |
| always | `fields` | projection pushdown (see below) |
| always | `pageSize` | `min(1000, remaining_budget)` |
| always | `countTotal=true` | first request only |
| always | `format=json` | |

**Filter-locus rule (important, keeps the system robust):** apply server-side only the params the spike confirmed work cleanly (`query.*`, `filter.overallStatus`, `filter.phase`). Apply `filters.countries` as a client-side post-filter on `StudyRecord.countries`. Leave `filters.start_year`/`end_year` to the transform stage (it parses dates). Document any param that falls back to client-side filtering in the returned `warnings` only if it actually changes the result set. Pushing year/country server-side is a P2 optimization, not v1.

**Projection pushdown:** always request only the fields the downstream needs. Start from this set and reconcile exact casing against `fixtures/raw/notes.md`:
`NCTId, BriefTitle, Phase, OverallStatus, StudyType, LeadSponsorName, LeadSponsorClass, StartDate, PrimaryCompletionDate, InterventionType, InterventionName, Condition, LocationCountry, EnrollmentCount`.

### Pagination
Loop on `nextPageToken`: first request sets `countTotal=true`, capture `totalCount`; continue passing `pageToken` until the token is absent or `studies_analyzed` reaches `options.max_studies`. `pageSize = min(1000, max_studies - fetched)`. Record truncation in `warnings` when the budget is hit before exhaustion.

### Retries and rate limits
Retry on 429 and 5xx with exponential backoff (a small manual loop or tenacity), capped at a few attempts; on persistent failure raise a retrieval-stage error (the orchestrator maps it to HTTP 502). Keep paging sequential or low-concurrency to be a good API citizen. Set a descriptive `User-Agent`.

### Parsing raw -> `StudyRecord` (`parsing.py`)
Null-safe extraction from `protocolSection`/`derivedSection` using the confirmed field paths. Every list defaults to `[]`; every scalar is nullable; never raise on a missing field. Map enumerated values straight onto the contract enums (they mirror the API vocabulary); if an unexpected value appears, coerce to the enum's `UNKNOWN`/`OTHER` member where one exists, else null, and add a one-line `warning` (deduplicated).

`parse_loose_date(s: str | None) -> datetime.date | None` must tolerate at least: `2024-01-15`, `2024-01`, `2024`, `January 2024`, `January 15, 2024`. Use `dateutil` with sane defaults (day 1 when absent). Return `None` on failure; keep the raw string in `start_date_raw`. Count unparseable dates and surface the count in `warnings`.

### Caching (`cache.py`)
File-based under `settings.CACHE_DIR`. Key = stable hash of (normalized params + `data_timestamp` from `/version`). `live`: read-through, write-through; `force_refresh`: bypass read, overwrite. `replay`: read-only, raise a clear error if the key is missing. Cache the raw API pages (not the parsed records), so a re-parse picks up parser fixes.

---

## Requirements

### Must-have (P0)
- [ ] `retrieve()` returns a valid `RetrievalResult` against the live API for a drug query and a condition query.
- [ ] Query builder maps every `AnalysisPlan` entity/filter field per the table and the filter-locus rule.
- [ ] Parser produces null-safe `StudyRecord`s and never raises on missing fields; `parse_loose_date` passes the date-format cases above.
- [ ] Pagination respects `max_studies` and records truncation; `countTotal` populates `total_matched`.
- [ ] Cache supports live/replay/force_refresh; replay needs no network.
- [ ] Retries on 429/5xx; persistent failure raises a retrieval-stage error.

### Nice-to-have (P1)
- [ ] Low-concurrency parallel paging behind a flag.
- [ ] `ruff` + `mypy app/retrieval` clean.

### Future considerations (P2)
- [ ] Push year and country filters server-side once the spike confirms reliable params.
- [ ] Use `/stats/field/values` for unfiltered global distributions as a fast path.

### Acceptance criteria
- Given a plan with `entities.drug="pembrolizumab"`, When `retrieve()` runs live, Then `studies` is non-empty, every record validates as `StudyRecord`, and `total_matched` is set.
- Given a study record whose API `StartDate` is `"January 2024"`, When parsed, Then `start_date == date(2024,1,1)` and `start_date_raw == "January 2024"`.
- Given a study record missing the interventions array, When parsed, Then `intervention_names == []` with no exception.
- Given `options.mode="replay"` and a cached key, When `retrieve()` runs with the network disabled, Then it returns the cached result; if the key is missing it raises a clear error.
- Given `options.max_studies=50` against a query with thousands of matches, When `retrieve()` runs, Then `studies_analyzed == 50` and `warnings` notes truncation.

---

## Verification commands
```
uv run pytest tests/retrieval -q
uv run ruff check app/retrieval         # P1
uv run mypy app/retrieval               # P1
# live smoke (needs network, no API key):
uv run python -c "import asyncio; from app.contracts import *; from app.retrieval import retrieve; from app.contracts.settings import Settings; \
print(asyncio.run(retrieve(AnalysisPlan(operation='time_trend', entities=Entities(drug='pembrolizumab'), proposed_viz='time_series', interpretation='x'), Settings(), RequestOptions())).studies_analyzed)"
```
Tests use `respx` (or a fake `httpx` transport) to serve canned multi-page responses built from `fixtures/raw/*.json`; no live calls in CI.

---

## File ownership and boundaries
Owns `app/retrieval/**` and `tests/retrieval/**`. Imports only from `app.contracts`. Does not modify `app/api/**`, `app/transform/**`, `app/viz/**`, or `app/contracts/**`. If a needed field is missing from `StudyRecord`, do not add it locally; flag it for a contracts amendment.

## Dependencies and chaining
Upstream: merged `contracts` (needs `AnalysisPlan`, `StudyRecord`, `RetrievalResult`, enums, `Settings`, and `fixtures/raw/`). Blocks `integration`. Concurrent with `transform`, `viz`, `planner`.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Exact multi-value separator for `filter.overallStatus`/`filter.phase` | spike notes | resolved in Phase 0 |
| Is there a clean server-side `study_type` filter param | spike notes | non-blocking (post-filter fallback) |
| Paging concurrency level | retrieval | non-blocking (default sequential) |

## Conductor handoff prompt
```
You are building the "retrieval" worktree for a ClinicalTrials.gov query-to-visualization backend.
Read docs/system-design.md (the CT.gov v2 cheat sheet in section 7) and docs/prd-contracts.md
(Sections A, C, D2, G), then build exactly what docs/prd-retrieval.md specifies.

You own app/retrieval/** and tests/retrieval/** only. Import shared types from app.contracts; do not
add fields to contracts (flag gaps instead) and do not touch other worktrees' directories.

Deliver an async retrieve(plan, settings, *, client=None) -> RetrievalResult that: builds CT.gov v2
/studies queries from the AnalysisPlan per the mapping table and the filter-locus rule (status/phase
server-side; country client-side; years deferred to transform); uses projection pushdown via fields=;
paginates on nextPageToken respecting options.max_studies with countTotal on the first call; retries
429/5xx with backoff; parses raw study JSON into null-safe StudyRecords with a tolerant date parser
(parse_loose_date); and caches raw pages with live/replay/force_refresh modes (replay needs no network).

Confirm exact field-path casing and the filter separator against fixtures/raw/notes.md. CT.gov needs no
API key. Tests must run offline using respx or a fake httpx transport over fixtures/raw/*.json; never
hit the live API in CI. Acceptance: every command in the PRD "Verification commands" block passes and
every acceptance criterion holds. ruff and mypy on app/retrieval are P1.
```
