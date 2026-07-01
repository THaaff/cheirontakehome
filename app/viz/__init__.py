"""The viz worktree: tidy/graph data + a plan -> a renderer-ready VizSpec.

Deterministic and registry-driven: no I/O, no LLM. The single public entrypoint
is :func:`build_viz`; the registry tables are exposed for introspection and
testing.

    from app.viz import build_viz
    spec = build_viz(tidy_dataset, analysis_plan)
"""

from __future__ import annotations

from .registry import (
    OPERATION_TO_VIZ,
    VIZ_BUILDERS,
    build_viz,
    viz_type_for,
)

__all__ = [
    "build_viz",
    "viz_type_for",
    "VIZ_BUILDERS",
    "OPERATION_TO_VIZ",
]
