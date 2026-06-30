# ctgov-viz — Phase 0: Contracts & Skeleton

Frozen shared types for a ClinicalTrials.gov query-to-visualization backend.
This worktree defines every Pydantic v2 model and enum that crosses a worktree
boundary, exports their JSON Schemas, stands up a FastAPI stub that returns the
real wire shape, and captures real CT.gov v2 fixtures. **It implements no
planner, retrieval, transform, or visualization logic** — those build later
against these frozen contracts.

See `docs/system-design.md` for the architecture and `docs/prd-contracts.md` for
the authoritative spec.

## Quick start

```bash
uv sync                                  # create the venv + install deps (Python 3.12)
uv run python -c "from app.contracts import *; print('contracts import ok')"
uv run pytest                            # full contract test suite
uv run ruff check .                      # lint (P1)
uv run mypy app/contracts                # type-check the frozen contracts (P1)
uv run python scripts/spike_api.py       # capture live CT.gov fixtures -> fixtures/raw/
uv run python scripts/export_schemas.py  # (re)export docs/schemas/*.json
```

Run the stub API:

```bash
uv run uvicorn app.api.main:app --port 8000
curl -s localhost:8000/health
curl -s -X POST localhost:8000/visualize \
  -H 'content-type: application/json' -d @fixtures/requests/example_bar.json | head -c 400
# Interactive docs: http://localhost:8000/docs
```

## What's here

| Path | Contents |
|---|---|
| `app/contracts/` | All shared models + enums (frozen). `__init__.py` re-exports everything. |
| `app/api/main.py` | FastAPI skeleton: `GET /health`, `POST /visualize` (stub), `/docs`. |
| `scripts/spike_api.py` | Live CT.gov v2 capture → `fixtures/raw/` + `notes.md`. |
| `scripts/export_schemas.py` | Exports JSON Schemas → `docs/schemas/`. |
| `fixtures/` | Hand-written, schema-valid example requests, plans, tidy datasets, responses; plus `raw/` captured from the API. |
| `docs/schemas/` | Exported JSON Schemas for the top-level wire types. |
| `tests/contracts/` | Round-trip, validator, discriminated-union, fixture-validity, schema-export, and API smoke tests. |

## Key contract facts

- **The `AnalysisPlan` IR** is the central object. A `model_validator` enforces
  the operation-to-required-fields matrix (PRD Section C): an invalid plan
  (e.g. a `comparison` with no `series`) cannot be constructed.
- **`VizSpec` is a discriminated union on `kind`** (`chart` vs `graph`), not on
  `renderer` — `renderer` has two chart values (`vega-lite`, `vega`) and so
  cannot be a unique discriminator.
- **API-facing enums mirror CT.gov's controlled vocabulary exactly** (`PHASE3`,
  `RECRUITING`, `INDUSTRY`, …) so no translation layer is needed.
- **`Settings` never raises at import for a missing `OPENAI_API_KEY`** — it's
  optional so `replay` mode works key-free. The planner uses OpenAI
  (`PLANNER_MODEL` default `gpt-4.1`).
- **The stats-filter question is settled** in `fixtures/raw/notes.md`:
  `/stats/field/values` rejects a `query.cond` filter (HTTP 400), so filtered
  distributions must be computed client-side by paging `/studies`.

## Stack

Python 3.12 · Pydantic v2 · FastAPI · pydantic-settings · httpx (spike only) ·
pytest · ruff + mypy (P1 gate) · uv for env & deps.
