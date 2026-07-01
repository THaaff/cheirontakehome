"""Validation stage: semantic checks on the final visualization spec.

Owned by the integration worktree. Exposes :func:`validate_output`, which the
orchestrator runs as the last deterministic step before assembling the response.
"""

from __future__ import annotations

from .validators import validate_output

__all__ = ["validate_output"]
