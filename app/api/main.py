"""FastAPI skeleton (PRD Section H).

Phase 0 stub. ``POST /visualize`` ignores the request body and returns a single
hardcoded, schema-valid :class:`VisualizationResponse` loaded from
``fixtures/responses/bar_chart_phases.json``. The integration worktree (Phase 2)
replaces the *internals* of this endpoint with real orchestration; the endpoint
signature and ``response_model`` are frozen so that swap is clean.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.contracts import VisualizationRequest, VisualizationResponse

# Repo root is two levels up from app/api/main.py; fixtures live at the root.
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "responses" / "bar_chart_phases.json"
)

app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization API",
    version="0.1.0",
    description=(
        "Turns a natural-language question about clinical trials into a "
        "renderer-ready visualization spec (chart or network graph) backed by "
        "real ClinicalTrials.gov v2 data, with per-datum citations.\n\n"
        "**Phase 0 skeleton:** `POST /visualize` currently returns a single "
        "hardcoded, schema-valid response. The contract (request body and "
        "`response_model`) is frozen; the integration worktree wires in the real "
        "pipeline later."
    ),
)

# Permissive CORS so the optional static demo page can call the API from
# anywhere. `allow_credentials` stays False because it is incompatible with the
# `*` origin wildcard (browsers reject that combination).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _stub_response() -> VisualizationResponse:
    """Load and validate the hardcoded stub response once."""
    raw: dict[str, Any] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    return VisualizationResponse.model_validate(raw)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/visualize", response_model=VisualizationResponse)
def visualize(request: VisualizationRequest) -> VisualizationResponse:
    """Produce a visualization spec for a natural-language query.

    **Phase 0 stub:** the request body is validated (so the contract is
    exercised) but otherwise ignored; this always returns the hardcoded
    ``bar_chart_phases`` fixture. To be replaced during integration — keep the
    signature and ``response_model`` stable.
    """
    return _stub_response()


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=False)
