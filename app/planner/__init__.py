"""The planner worktree: natural language -> validated ``AnalysisPlan``.

This is the only stage that calls an LLM. It targets a constraint-light
:class:`PlannerOutput` via OpenAI Structured Outputs, then re-validates into the
real :class:`~app.contracts.AnalysisPlan` so every contract validator runs.

Public surface::

    from app.planner import plan_query, PlanningError, PlannerOutput
"""

from __future__ import annotations

from .client import plan_query
from .errors import PlanningError
from .schema import PlannerOutput

__all__ = ["plan_query", "PlanningError", "PlannerOutput"]
