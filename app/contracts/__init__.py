"""Frozen shared contracts for the CT.gov query-to-visualization backend.

This package is the single source of truth every other worktree imports. It is
frozen in Phase 0: planner, retrieval, transform, viz, and integration all build
against these types. Nothing here implements pipeline logic — only shapes and
the constraints intrinsic to them.

Import anything from the top level, e.g.::

    from app.contracts import AnalysisPlan, VisualizationResponse, VizSpec
"""

from __future__ import annotations

from .data import (
    ChartDatum,
    Citation,
    DataPoint,
    GraphData,
    GraphEdge,
    GraphNode,
    RetrievalResult,
    StudyRecord,
    TidyDataset,
)
from .enums import (
    CategoricalField,
    ChannelType,
    EdgeSemantics,
    InterventionType,
    Measure,
    NodeType,
    NumericField,
    Operation,
    OverallStatus,
    Phase,
    PipelineStage,
    Renderer,
    RequestMode,
    SeriesDimension,
    SponsorClass,
    StudyType,
    VizType,
)
from .plan import (
    AnalysisPlan,
    Entities,
    Filters,
    NetworkSpec,
    SeriesSpec,
)
from .request import RequestOptions, VisualizationRequest
from .response import ErrorDetail, ErrorResponse, Meta, VisualizationResponse
from .settings import Settings
from .viz import (
    Channel,
    ChartVizSpec,
    Encoding,
    GraphEncoding,
    GraphVizSpec,
    VizHints,
    VizSpec,
)

__all__ = [
    # enums
    "Operation",
    "VizType",
    "CategoricalField",
    "NumericField",
    "Measure",
    "Phase",
    "OverallStatus",
    "StudyType",
    "SponsorClass",
    "InterventionType",
    "SeriesDimension",
    "NodeType",
    "EdgeSemantics",
    "ChannelType",
    "Renderer",
    "RequestMode",
    "PipelineStage",
    # request
    "RequestOptions",
    "VisualizationRequest",
    # plan
    "Entities",
    "Filters",
    "SeriesSpec",
    "NetworkSpec",
    "AnalysisPlan",
    # data
    "Citation",
    "DataPoint",
    "TidyDataset",
    "ChartDatum",
    "GraphNode",
    "GraphEdge",
    "GraphData",
    "StudyRecord",
    "RetrievalResult",
    # viz
    "Channel",
    "Encoding",
    "GraphEncoding",
    "VizHints",
    "ChartVizSpec",
    "GraphVizSpec",
    "VizSpec",
    # response
    "Meta",
    "VisualizationResponse",
    "ErrorDetail",
    "ErrorResponse",
    # settings
    "Settings",
]
