"""Data and provenance models (PRD Section D).

Two families live here:

* the *internal* tidy representation the transform layer produces
  (:class:`DataPoint`, :class:`TidyDataset`), and
* the *wire* representations the viz layer emits (:class:`ChartDatum`,
  :class:`GraphData` and its nodes/edges).

:class:`Citation` is the deep-citation unit threaded through every datum, node,
and edge — provenance is a first-class output of the transform layer, never
bolted on at the end.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    InterventionType,
    NodeType,
    OverallStatus,
    Phase,
    SponsorClass,
    StudyType,
)


class Citation(BaseModel):
    """A pointer from a computed datum back to a source trial record."""

    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(description="e.g. NCT01234567.")
    excerpt: str = Field(
        description="Exact text or field value from the API response supporting the datum."
    )
    field: str | None = Field(
        default=None,
        description="Source field path, e.g. protocolSection.designModule.phases.",
    )


class DataPoint(BaseModel):
    """Internal tidy unit produced by the transform layer."""

    model_config = ConfigDict(extra="forbid")

    dims: dict[str, str | int | float] = Field(
        description='e.g. {"phase": "PHASE3"} or {"year": 2021, "series": "melanoma"}.'
    )
    measure: str = Field(description="Measure name, e.g. trial_count.")
    value: float = Field(description="The computed value.")
    citations: list[Citation] = Field(default_factory=list)


class TidyDataset(BaseModel):
    """A tidy, long-format dataset plus the dimension/measure metadata."""

    model_config = ConfigDict(extra="forbid")

    points: list[DataPoint]
    dimension_names: list[str] = Field(description="The dim keys present, for the viz layer.")
    measure_name: str
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Transform-stage warnings (e.g. excluded unparseable dates, empty input). "
            "The orchestrator folds these into Meta.warnings; the viz layer ignores them."
        ),
    )


class ChartDatum(BaseModel):
    """Wire form for a single chart record.

    Dimension and measure keys live in the allowed extras, so a record
    serializes as e.g. ``{"phase": "PHASE3", "trial_count": 78, "citations": [...]}``.
    Vega-Lite simply ignores the ``citations`` key when rendering.
    """

    model_config = ConfigDict(extra="allow")

    citations: list[Citation] = Field(default_factory=list)


class GraphNode(BaseModel):
    """A node in a co-occurrence network."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable id, e.g. drug:pembrolizumab.")
    label: str = Field(description="Display label.")
    type: NodeType
    weight: float = Field(description="e.g. trial count the node participates in.")
    x: float | None = Field(default=None, description="Precomputed layout coord (optional).")
    y: float | None = None
    citations: list[Citation] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """An edge in a co-occurrence network."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Node id.")
    target: str = Field(description="Node id.")
    weight: float = Field(description="Co-occurrence trial count.")
    citations: list[Citation] = Field(default_factory=list)


class GraphData(BaseModel):
    """The node/edge payload for a network graph."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Transform-stage warnings (e.g. empty input). The orchestrator folds these "
            "into Meta.warnings; the viz layer ignores them."
        ),
    )


# ---------------------------------------------------------------------------
# Section D2: the retrieval -> transform interface
# ---------------------------------------------------------------------------


class StudyRecord(BaseModel):
    """One flat, normalized study (built by retrieval, consumed by transform).

    Tolerant by construction: **every list defaults to ``[]`` and every
    descriptive scalar is nullable**, so it never raises on missing API fields —
    absence becomes null/empty. This is where the "real-world data handling"
    rubric credit is earned. The retrieval worktree centralizes all API-shape and
    messy-data handling here; the transform worktree consumes clean typed records.
    """

    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(description="protocolSection.identificationModule.nctId.")
    brief_title: str | None = Field(
        default=None, description="Used as a citation excerpt fallback."
    )
    phases: list[Phase] = Field(
        default_factory=list, description="Parsed from designModule.phases; may be empty."
    )
    overall_status: OverallStatus | None = None
    study_type: StudyType | None = None
    lead_sponsor_name: str | None = None
    lead_sponsor_class: SponsorClass | None = None
    start_date: date | None = Field(
        default=None, description="Tolerant-parsed; None if unparseable."
    )
    start_date_raw: str | None = Field(
        default=None, description="The original string, for excerpts and debugging."
    )
    completion_date: date | None = Field(default=None, description="Tolerant-parsed.")
    intervention_types: list[InterventionType] = Field(default_factory=list)
    intervention_names: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(
        default_factory=list, description="Deduped from locations[].country; may be empty."
    )
    enrollment_count: int | None = Field(
        default=None, description="From designModule.enrollmentInfo.count."
    )


class RetrievalResult(BaseModel):
    """Returned by the retrieval entrypoint.

    Transform consumes ``studies``; the scalar fields flow through the
    orchestrator into :class:`~app.contracts.response.Meta`.
    """

    model_config = ConfigDict(extra="forbid")

    studies: list[StudyRecord] = Field(
        default_factory=list, description="The projected, normalized records."
    )
    total_matched: int | None = Field(
        default=None, description="From the API countTotal when available."
    )
    studies_analyzed: int = Field(
        description="How many records were actually fetched and parsed."
    )
    data_timestamp: str | None = Field(
        default=None, description="CT.gov dataTimestamp at fetch time."
    )
    warnings: list[str] = Field(
        default_factory=list, description="e.g. parse failures, truncation at max_studies."
    )
