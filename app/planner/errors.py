"""Planning-stage errors.

Every failure in the planner — a missing key, a model refusal, a length cutoff,
an empty parse, an upstream API error, or a plan that fails contract validation
even after one retry — surfaces as a single typed :class:`PlanningError`. The
orchestrator (integration worktree) catches it and maps it to HTTP 422; the
planner itself only raises. It never crashes and never returns a fabricated plan.
"""

from __future__ import annotations

from typing import Any, Literal

from app.contracts import PipelineStage

# The closed set of reasons a plan can fail. Carried on the error for logging and
# for the orchestrator to shape its response.
PlanningErrorReason = Literal[
    "missing_api_key",
    "refusal",
    "length",
    "empty",
    "validation",
    "api_error",
]


class PlanningError(Exception):
    """A clean, typed failure of the planning stage.

    Attributes:
        stage: Always :attr:`PipelineStage.planning`, for uniform error mapping.
        reason: A machine-readable cause from :data:`PlanningErrorReason`.
        details: Optional structured context (e.g. the validation error text).
    """

    stage: PipelineStage = PipelineStage.planning

    def __init__(
        self,
        message: str,
        *,
        reason: PlanningErrorReason,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason: PlanningErrorReason = reason
        self.details: dict[str, Any] = details or {}
