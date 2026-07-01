"""Stage-tagged pipeline errors and the FastAPI handlers that map them to HTTP.

One exception type crosses the orchestrator boundary — :class:`PipelineError`,
tagged with the :class:`~app.contracts.PipelineStage` that failed. The handlers
turn it (and FastAPI's own body-validation error) into the contract's
:class:`~app.contracts.ErrorResponse` envelope, so *every* error the service
emits has the shape ``{request_id, error: {type, stage, message, details}}`` —
including malformed-input errors, which would otherwise return FastAPI's default
``{"detail": [...]}`` body.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contracts import ErrorDetail, ErrorResponse, PipelineStage


class PipelineError(Exception):
    """A uniform, stage-tagged pipeline failure.

    The orchestrator wraps every stage call so exactly one of these reaches the
    handler; ``stage`` selects the HTTP status. ``request_id`` is carried for log
    correlation and to echo the originating request in the error body.
    """

    def __init__(
        self,
        stage: PipelineStage,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.error_type = error_type
        self.message = message
        self.details = details
        self.request_id = request_id


# Stage -> HTTP status. Planner input problems and body validation are the
# client's fault (422); a CT.gov outage is an upstream failure (502); a transform
# or visualization/validation failure is an internal bug (500).
_STAGE_STATUS: dict[PipelineStage, int] = {
    PipelineStage.validation: 422,
    PipelineStage.planning: 422,
    PipelineStage.retrieval: 502,
    PipelineStage.transform: 500,
    PipelineStage.visualization: 500,
}


def _error_response(status_code: int, request_id: str, detail: ErrorDetail) -> JSONResponse:
    body = ErrorResponse(request_id=request_id, error=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def _handle_request_validation(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Malformed request body -> 422 in the ErrorResponse shape (stage=validation)."""
    detail = ErrorDetail(
        type="invalid_request",
        stage=PipelineStage.validation,
        message="Request body failed validation.",
        details={"errors": jsonable_encoder(exc.errors())},
    )
    return _error_response(422, uuid4().hex, detail)


async def _handle_pipeline_error(request: Request, exc: PipelineError) -> JSONResponse:
    """Stage-tagged pipeline failure -> its mapped HTTP status, ErrorResponse shape."""
    status_code = _STAGE_STATUS.get(exc.stage, 500)
    request_id = exc.request_id or uuid4().hex
    detail = ErrorDetail(
        type=exc.error_type,
        stage=exc.stage,
        message=exc.message,
        details=exc.details,
    )
    return _error_response(status_code, request_id, detail)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort guard so an unforeseen error still returns the contract shape.

    ``PipelineStage`` has no ``internal`` member; the last deterministic stage is
    output assembly, so an unclassified failure is reported as ``visualization``.
    """
    detail = ErrorDetail(
        type="internal_error",
        stage=PipelineStage.visualization,
        message="An unexpected internal error occurred.",
        details={"error": str(exc)},
    )
    return _error_response(500, uuid4().hex, detail)


def register_exception_handlers(app: FastAPI) -> None:
    """Register the handlers that emit the contract ErrorResponse envelope.

    Registering a ``RequestValidationError`` handler overrides FastAPI's default
    422 body so even malformed input uses the contract shape. FastAPI dispatches
    by most-specific exception type, so the broad ``Exception`` handler never
    shadows the specific ones.
    """
    app.add_exception_handler(RequestValidationError, _handle_request_validation)  # type: ignore[arg-type]
    app.add_exception_handler(PipelineError, _handle_pipeline_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)
