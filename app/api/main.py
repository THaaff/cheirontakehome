"""FastAPI application: the real ``POST /visualize`` wired to the pipeline.

Replaces the Phase 0 stub internals with :func:`app.api.orchestrator.run_pipeline`
while keeping the endpoint signature and ``response_model`` stable. The app owns
long-lived clients for its lifecycle (one CT.gov ``httpx.AsyncClient``; the OpenAI
client is the planner's own module singleton) and closes them on shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import app.planner.client as planner_client
from app.api.errors import register_exception_handlers
from app.api.orchestrator import run_pipeline
from app.contracts import Settings, VisualizationRequest, VisualizationResponse

# Single process-wide config object, sourced from env / .env. Tests override the
# `get_settings` dependency to point at a fixture cache and force replay mode.
settings = Settings()


def get_settings() -> Settings:
    """Settings dependency (override in tests via ``app.dependency_overrides``)."""
    return settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the CT.gov HTTP client for the app lifecycle; close clients on shutdown.

    A single ``AsyncClient`` gives the retrieval stage — and the comparison
    fan-out's concurrent retrievals — one shared connection pool with keep-alive
    and TLS reuse. The planner manages its own OpenAI client lazily (built only on
    a live call, so a replay-only server stays key-free); we close it here so the
    event loop tears down cleanly without an ``atexit`` hook.
    """
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    try:
        yield
    finally:
        await app.state.http.aclose()
        await planner_client.aclose()


app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization API",
    version="0.1.0",
    description=(
        "Turns a natural-language question about clinical trials into a "
        "renderer-ready visualization spec (chart or network graph) backed by "
        "real ClinicalTrials.gov v2 data, with per-datum citations.\n\n"
        "The model only plans; every number is computed deterministically from "
        "the API response. `replay` mode serves cached data with no key or network."
    ),
    lifespan=lifespan,
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

register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/visualize", response_model=VisualizationResponse)
async def visualize(
    request: VisualizationRequest,
    http_request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> VisualizationResponse:
    """Produce a visualization spec for a natural-language query.

    Runs the full pipeline (plan -> retrieve -> transform -> viz -> validate) and
    returns a render-ready :class:`VisualizationResponse`, or an ``ErrorResponse``
    (via the registered handlers) tagged with the stage that failed.
    """
    # Normally set by the lifespan; fall back to None so a bare TestClient (no
    # lifespan) still works — retrieval then creates its own per-call client.
    http_client = getattr(http_request.app.state, "http", None)
    return await run_pipeline(request, settings, http_client=http_client)


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=False)
