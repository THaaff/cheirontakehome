"""The retrieval-stage error type.

A persistent CT.gov failure (exhausted retries on 429/5xx, a transport error, or
a malformed upstream response) raises :class:`RetrievalError`. It carries the
frozen :class:`~app.contracts.enums.PipelineStage` value so the integration
worktree can map it to an HTTP 502 without re-deriving where it came from.
"""

from __future__ import annotations

from app.contracts import PipelineStage


class RetrievalError(Exception):
    """Raised on unrecoverable upstream failures during retrieval."""

    stage: PipelineStage = PipelineStage.retrieval

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
