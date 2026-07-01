# PRD: Planner (Phase 1)

**Worktree:** `planner` · **Status:** ready after contracts merges · **Depends on:** `contracts` · **Blocks:** `integration`
**Runs concurrently with:** `retrieval`, `transform`, `viz` · **Read first:** `docs/system-design.md`, `docs/prd-contracts.md`

---

## Problem statement

This is the one stage where the LLM runs. It reads a natural-language query plus optional structured hints and emits a typed `AnalysisPlan`: which operation, which entities and filters, which grouping, which viz. It never sees trial data and never emits a data value. Its correctness determines whether the right query is run and the right chart is chosen, so it is built as a constrained classifier/extractor with a real eval set, not as a freeform agent.

## Goals
1. An entrypoint `plan_query(request, settings) -> AnalysisPlan` that uses OpenAI Structured Outputs so the model output is schema-conformant by construction.
2. High classification accuracy on the operation taxonomy and reliable entity extraction, measured by an eval set.
3. Graceful failure: model refusals, length cutoffs, and post-validation failures become a clean planning-stage error, never a crash or a fabricated plan.
4. Deterministic, key-free CI via recorded planner outputs (replay), with an opt-in live eval.

## Non-goals
1. **No data fetching, aggregation, or spec building.** The plan is the only output.
2. **No free-form tool use / ReAct loop.** One structured-output call (plus at most one retry).
3. **No viz authoring.** The planner only *proposes* a viz; the authoritative viz type is derived from the operation downstream.
4. **No emitting of counts or any numeric data values.**

## User stories
- As the **retrieval worktree**, I receive a plan whose entities/filters map cleanly onto API params.
- As the **transform/viz worktrees**, I receive an operation and grouping that unambiguously select an aggregation and a chart.
- As the **author**, I can run a 15-query eval and see operation-accuracy and extraction-accuracy numbers before trusting the planner.

---

## Scope and specification

### Module layout (owns `app/planner/**`, `tests/planner/**`)
- `app/planner/schema.py` — `PlannerOutput` (the structured-output target).
- `app/planner/prompt.py` — system prompt + few-shot examples.
- `app/planner/client.py` — OpenAI call, retry, refusal/length handling, mapping to `AnalysisPlan`.
- `app/planner/__init__.py` — exports `plan_query`.
- `app/planner/eval/` — eval query set and harness.

### Why a separate `PlannerOutput` schema (do not target `AnalysisPlan` directly)
OpenAI strict Structured Outputs has a known subset: it forces `additionalProperties:false`, treats optionals as nullable, requires all properties, and ignores several value constraints (`minLength`, numeric bounds, etc.). `AnalysisPlan` carries `Field` constraints, defaults, and a cross-field `model_validator`, which can surprise the schema converter and would not be enforced at decode time anyway. So:

1. Define `PlannerOutput`: a constraint-light mirror of `AnalysisPlan`. Reuse the constraint-light contract models (`Entities`, `Filters`) directly. For `series` and `network`, use plain local nested models with no `Field` bounds and no validators. Express every optional as `X | None`. No defaults that matter.
2. Call the model with `PlannerOutput` as the target.
3. Map and validate into the real IR: `AnalysisPlan.model_validate(planner_output.model_dump())`. This is where all contract constraints and the operation-to-required-fields validator actually run.

This cleanly separates "what we ask the model to emit" from "what we enforce," and removes all strict-mode-compatibility risk.

### The OpenAI call (`client.py`)
Async, using `AsyncOpenAI`. Representative shape (use whatever the installed SDK exposes; `responses.parse` is the current primary path, `chat.completions.parse` is equivalent):
```python
resp = await client.responses.parse(
    model=settings.PLANNER_MODEL,        # default "gpt-4.1"
    input=messages,                       # system + few-shots + user
    text_format=PlannerOutput,
    temperature=0,
)
parsed = resp.output_parsed              # a PlannerOutput, or None on refusal
```
Handle: a populated `refusal` -> planning-stage error; `LengthFinishReasonError` / truncation -> planning-stage error; `parsed is None` -> planning-stage error. Set `temperature=0` for deterministic classification.

**Client lifecycle:** prefer an injected client (the server passes an app-lifecycle `AsyncOpenAI` via the orchestrator). When none is injected, `_get_client` returns a module-level lazy singleton (created once, reused across calls, monkeypatchable for tests), never a fresh client per call (that leaks an httpx pool per request and defeats keep-alive/TLS reuse). Optionally expose `async def aclose()` to close the singleton; the eval harness can call it in a `finally`. Do not close async clients via `atexit` (no running loop).

### Validation and retry
After parsing, build `AnalysisPlan`. On `ValidationError`, retry once, appending the validation error text to the prompt as a correction signal. On a second failure, raise a planning-stage error (orchestrator maps to HTTP 422). Cap the model at one retry; do not loop.

### Prompt design (`prompt.py`)
- System prompt: state the role (translate a clinical-trials question into a structured plan), enumerate the seven operations with one-line selection guidance each, list the groupable `CategoricalField`s and the `SeriesDimension`s, and state the hard rule that the model must not invent data and must fill `interpretation` (one sentence) and `assumptions` (any inference it made, e.g., resolving "recent").
- Pass the request's optional structured hints (`drug_name`, `condition`, `sponsor`, `phase`, `country`, `start_year`, `end_year`) into the user message as explicit context the model may use.
- Few-shots: one worked example per operation, mapping a representative query to a correct `PlannerOutput`. Keep them in `prompt.py` as typed objects so they cannot drift from the schema.
- Operation selection cues to encode: time words and "per year/over time" -> `time_trend`; "distribution/breakdown across X" -> `categorical_distribution`; "compare A vs B" or "across two conditions" -> `comparison` (set `series`); "which countries/where" -> `geographic_distribution`; "network/relationship/co-occurrence/combination" -> `cooccurrence_network` (set `network`); single-numeric "distribution of enrollment" -> `numeric_distribution`; two-numeric "X vs Y" -> `numeric_relationship`.

### Eval (`eval/`)
- A set of ~15 queries spanning all seven operations (include a few ambiguous ones), each labeled with the expected `operation` and the key expected extractions (e.g., the drug or condition string, the `group_by`, whether `series`/`network` is set).
- The harness asserts operation accuracy and key-field extraction. Allow fuzzy matching on `interpretation` text; assert exact match on `operation` and on structural fields.
- **Reproducibility:** record real planner outputs for the eval queries once into `app/planner/eval/recorded/` so the eval and CI run in replay (no key, deterministic). A `--live` flag re-queries the model and is opt-in.

---

## Requirements

### Must-have (P0)
- [ ] `PlannerOutput` defined as a constraint-light, strict-mode-friendly schema; mapping into `AnalysisPlan` runs all contract validators.
- [ ] `plan_query()` calls OpenAI Structured Outputs and returns a valid `AnalysisPlan`.
- [ ] Refusal, length cutoff, and post-validation failure each produce a clean planning-stage error (no crash, no fabricated plan).
- [ ] One-retry-on-ValidationError implemented and tested.
- [ ] Eval harness runs in replay over recorded outputs with no API key; operation accuracy reported.

### Nice-to-have (P1)
- [ ] Operation accuracy >= 13/15 and correct extraction of the primary entity on the unambiguous queries.
- [ ] `ruff` + `mypy app/planner` clean.

### Future considerations (P2)
- [ ] Confidence/uncertainty signal in `assumptions` when the query is ambiguous.
- [ ] Provider abstraction so a local model could back the planner later.

### Acceptance criteria
- Given "trials for pembrolizumab per year since 2018", When `plan_query()` runs, Then `operation == time_trend`, `entities.drug` contains pembrolizumab, and `filters.start_year == 2018`.
- Given "compare sponsor types for melanoma vs lung cancer", When `plan_query()` runs, Then `operation == comparison`, `group_by == lead_sponsor_class`, and `series.values` has both conditions.
- Given the model returns a `PlannerOutput` that violates the operation matrix (e.g., comparison without series), When mapping into `AnalysisPlan`, Then one retry occurs and, if it still fails, a planning-stage error is raised.
- Given no `OPENAI_API_KEY`, When the eval runs in replay, Then it completes and reports accuracy with no network call.

---

## Verification commands
```
uv run pytest tests/planner -q                 # offline: mapping, retry, refusal, replay eval
uv run python -m app.planner.eval               # replay eval, prints accuracy
uv run python -m app.planner.eval --live        # opt-in, needs OPENAI_API_KEY
uv run ruff check app/planner                   # P1
uv run mypy app/planner                         # P1
```

## File ownership and boundaries
Owns `app/planner/**` and `tests/planner/**`. Imports only from `app.contracts`. Does not modify contracts (flag gaps), retrieval, transform, viz, or api. Never raises at import for a missing key; raise only when a live call is attempted.

## Dependencies and chaining
Upstream: merged `contracts` (`VisualizationRequest`, `AnalysisPlan` + nested models, enums, `Settings`). Blocks `integration`. Concurrent with `retrieval`, `transform`, `viz`. Requires the `OPENAI_API_KEY` for live runs only; the user has an OpenAI key.

## Open questions
| Question | Owner | Blocking? |
|---|---|---|
| Confirm `gpt-4.1` is available on the account | Taylor | non-blocking (env-configurable; `gpt-4.1-mini` fallback) |
| Few-shots inline vs external file | planner | non-blocking (recommend inline typed objects) |
| `responses.parse` vs `chat.completions.parse` | planner | non-blocking (use installed SDK's current path) |

## Conductor handoff prompt
```
You are building the "planner" worktree for a ClinicalTrials.gov query-to-visualization backend. This
is the only stage that calls an LLM. Read docs/system-design.md (sections 3 and 6 on the model-plans-
code-executes principle) and docs/prd-contracts.md (Sections A, B, C), then build exactly what
docs/prd-planner.md specifies.

You own app/planner/** and tests/planner/** only. Import shared types from app.contracts; do not modify
contracts or other worktrees' directories.

Build plan_query(request, settings) -> AnalysisPlan using OpenAI Structured Outputs. Do NOT target
AnalysisPlan directly: define a constraint-light PlannerOutput schema (reuse Entities and Filters from
contracts; plain local nested models for series/network; optionals as X|None; no Field bounds, no
validators), call the model with text_format=PlannerOutput at temperature 0 (default model gpt-4.1,
env-configurable), then map into the real IR with AnalysisPlan.model_validate(...) so all contract
validators run. Handle refusals, length cutoffs, and post-validation failures as clean planning-stage
errors; retry once on ValidationError feeding the error back, then fail. Write a system prompt that
enumerates the seven operations with selection cues and one typed few-shot per operation, and pass the
request's optional structured hints into the prompt.

Build an eval over ~15 labeled queries spanning all operations; record real outputs once into
app/planner/eval/recorded/ so the eval and CI run in replay with no API key, with a --live opt-in flag.
Never raise at import for a missing OPENAI_API_KEY. Acceptance: every command in the PRD "Verification
commands" block passes; the acceptance criteria hold; tests run offline. ruff and mypy on app/planner
are P1.
```
