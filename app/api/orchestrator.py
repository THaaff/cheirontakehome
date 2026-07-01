"""The pipeline orchestrator: request -> plan -> retrieve -> transform -> viz -> validate.

This is the wiring brain. It owns no domain logic — it calls the imported stage
entrypoints in order, branches on the plan's operation (including the comparison
fan-out), threads the app-owned HTTP client through every retrieval so the
fan-out shares one connection pool, and folds the per-stage warnings into the
response ``Meta``. Each stage call is wrapped so a single stage-tagged
:class:`~app.api.errors.PipelineError` crosses back to the HTTP layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from app.api.errors import PipelineError
from app.contracts import (
    AnalysisPlan,
    GraphData,
    Meta,
    Operation,
    PipelineStage,
    RequestOptions,
    RetrievalResult,
    Settings,
    StudyRecord,
    TidyDataset,
    VisualizationRequest,
    VisualizationResponse,
    VizSpec,
)
from app.planner import PlanningError, plan_query
from app.retrieval import retrieve
from app.retrieval.errors import RetrievalError
from app.retrieval.query_builder import build_server_params
from app.transform import dispatch
from app.validation import validate_output
from app.viz import build_viz

logger = logging.getLogger(__name__)

# Keys that ``build_server_params`` adds for the transport itself, not filters.
_NON_FILTER_PARAMS = frozenset({"format", "fields"})

# Payload accepted by transform.dispatch: a flat record list for most operations,
# or a labeled per-series record list for a comparison.
_TransformPayload = list[StudyRecord] | list[tuple[str, list[StudyRecord]]]


@dataclass(frozen=True)
class _RetrMeta:
    """The scalar retrieval metadata that flows into the response ``Meta``."""

    total_matched: int | None
    studies_analyzed: int
    data_timestamp: str | None
    warnings: list[str]


async def run_pipeline(
    request: VisualizationRequest,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> VisualizationResponse:
    """Run the full pipeline for ``request`` and return a ``VisualizationResponse``.

    ``http_client`` is the app-lifecycle CT.gov client; it is passed into every
    ``retrieve`` call so a comparison fan-out's concurrent retrievals share one
    pool. When ``None`` (e.g. a standalone call), retrieval falls back to its own
    per-call client.
    """
    request_id = uuid4().hex
    options = request.options
    logger.info("request %s: starting pipeline (mode=%s)", request_id, options.mode)

    plan = await _plan(request, settings, request_id)
    logger.debug("request %s: operation=%s viz=%s", request_id, plan.operation, plan.proposed_viz)

    data: TidyDataset | GraphData
    if plan.operation is Operation.comparison:
        data, retr = await _comparison_path(plan, settings, options, http_client, request_id)
    else:
        result = await _retrieve(plan, settings, options, http_client, request_id)
        retr = _meta_from(result)
        data = _transform(plan, result.studies, request_id)

    viz_spec = _build_viz(data, plan, request_id)
    val_warnings = _validate(viz_spec, data, request_id)

    meta = Meta(
        query_interpretation=plan.interpretation,
        assumptions=plan.assumptions,
        filters_applied=_filters_applied(plan),
        total_studies_matched=retr.total_matched,
        studies_analyzed=retr.studies_analyzed,
        data_timestamp=retr.data_timestamp,
        warnings=[*retr.warnings, *data.warnings, *val_warnings],
        plan=plan if options.debug else None,
    )
    logger.info(
        "request %s: done (studies_analyzed=%s, warnings=%s)",
        request_id,
        retr.studies_analyzed,
        len(meta.warnings),
    )
    return VisualizationResponse(request_id=request_id, visualization=viz_spec, meta=meta)


# ---------------------------------------------------------------------------
# comparison fan-out
# ---------------------------------------------------------------------------


async def _comparison_path(
    plan: AnalysisPlan,
    settings: Settings,
    options: RequestOptions,
    http_client: httpx.AsyncClient | None,
    request_id: str,
) -> tuple[TidyDataset | GraphData, _RetrMeta]:
    """Fan out one sub-plan per series value, retrieve concurrently, merge meta.

    Each sub-plan injects one ``series.values`` entry into the entity slot named
    by ``series.dimension`` (drug/condition/sponsor), keeping ``group_by`` and
    ``filters``. The labeled ``(series_value, studies)`` pairs go to the
    comparison aggregation via ``dispatch``.
    """
    if plan.series is None:  # pragma: no cover - guaranteed by the AnalysisPlan validator
        raise PipelineError(
            stage=PipelineStage.transform,
            error_type="transform_failed",
            message="comparison plan is missing its series specification",
            request_id=request_id,
        )

    slot = plan.series.dimension.value  # "drug" | "condition" | "sponsor"
    values = plan.series.values
    sub_plans = [
        plan.model_copy(update={"entities": plan.entities.model_copy(update={slot: value})})
        for value in values
    ]

    coros: list[Coroutine[Any, Any, RetrievalResult]] = [
        _retrieve(sub_plan, settings, options, http_client, request_id) for sub_plan in sub_plans
    ]
    results: list[RetrievalResult] = list(await asyncio.gather(*coros))

    series_studies: list[tuple[str, list[StudyRecord]]] = [
        (value, result.studies) for value, result in zip(values, results, strict=True)
    ]
    data = _transform(plan, series_studies, request_id)
    return data, _merge_retr([_meta_from(result) for result in results])


def _merge_retr(metas: list[_RetrMeta]) -> _RetrMeta:
    """Merge per-series retrieval metadata into one carrier for the response."""
    studies_analyzed = sum(meta.studies_analyzed for meta in metas)

    totals = [meta.total_matched for meta in metas]
    total_matched = sum(t for t in totals if t is not None) if all(
        t is not None for t in totals
    ) else None

    seen: set[str] = set()
    warnings: list[str] = []
    for meta in metas:
        for warning in meta.warnings:
            if warning not in seen:
                seen.add(warning)
                warnings.append(warning)

    data_timestamp = next(
        (meta.data_timestamp for meta in metas if meta.data_timestamp is not None), None
    )
    return _RetrMeta(total_matched, studies_analyzed, data_timestamp, warnings)


# ---------------------------------------------------------------------------
# stage wrappers (native error -> one stage-tagged PipelineError)
# ---------------------------------------------------------------------------


async def _plan(
    request: VisualizationRequest, settings: Settings, request_id: str
) -> AnalysisPlan:
    try:
        return await plan_query(request, settings)
    except PlanningError as exc:
        raise PipelineError(
            stage=exc.stage,
            error_type=exc.reason,
            message=str(exc),
            details=exc.details or None,
            request_id=request_id,
        ) from exc


async def _retrieve(
    plan: AnalysisPlan,
    settings: Settings,
    options: RequestOptions,
    http_client: httpx.AsyncClient | None,
    request_id: str,
) -> RetrievalResult:
    try:
        return await retrieve(plan, settings, options, client=http_client)
    except RetrievalError as exc:
        raise PipelineError(
            stage=exc.stage,
            error_type="upstream_unavailable",
            message=exc.message,
            request_id=request_id,
        ) from exc


def _transform(
    plan: AnalysisPlan, payload: _TransformPayload, request_id: str
) -> TidyDataset | GraphData:
    try:
        return dispatch(plan, payload)
    except (ValueError, TypeError, AssertionError) as exc:
        raise PipelineError(
            stage=PipelineStage.transform,
            error_type="transform_failed",
            message=f"transform stage failed: {exc}",
            details={"error": str(exc)},
            request_id=request_id,
        ) from exc


def _build_viz(data: TidyDataset | GraphData, plan: AnalysisPlan, request_id: str) -> VizSpec:
    try:
        return build_viz(data, plan)
    except (TypeError, ValueError) as exc:
        raise PipelineError(
            stage=PipelineStage.visualization,
            error_type="visualization_failed",
            message=f"visualization stage failed: {exc}",
            details={"error": str(exc)},
            request_id=request_id,
        ) from exc


def _validate(viz_spec: VizSpec, data: TidyDataset | GraphData, request_id: str) -> list[str]:
    try:
        return validate_output(viz_spec, data)
    except PipelineError as exc:
        if exc.request_id is None:
            exc.request_id = request_id
        raise


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _meta_from(result: RetrievalResult) -> _RetrMeta:
    return _RetrMeta(
        total_matched=result.total_matched,
        studies_analyzed=result.studies_analyzed,
        data_timestamp=result.data_timestamp,
        warnings=list(result.warnings),
    )


def _filters_applied(plan: AnalysisPlan) -> dict[str, str]:
    """The concrete server-side filters used, for ``Meta.filters_applied``.

    Reuses the retrieval query builder so what we report exactly matches what was
    queried; the transport-only ``format``/``fields`` params are dropped.
    """
    params = build_server_params(plan)
    return {key: value for key, value in params.items() if key not in _NON_FILTER_PARAMS}
