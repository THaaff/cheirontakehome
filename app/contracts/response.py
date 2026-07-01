"""Top-level response and error models (PRD Section F).

HTTP status mapping (the integration worktree enforces this; documented here so
the contract is self-describing):

* **200** — success, *including empty result sets*. An empty result carries a
  ``meta.warnings`` entry rather than failing; never a silent blank chart.
* **422** — validation / planning input errors.
* **502** — upstream ClinicalTrials.gov failures.
* **500** — internal errors.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import PipelineStage
from .plan import AnalysisPlan
from .viz import VizSpec


class Meta(BaseModel):
    """Response metadata: interpretation, provenance counts, and warnings."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="clinicaltrials.gov")
    query_interpretation: str = Field(description="From AnalysisPlan.interpretation.")
    assumptions: list[str] = Field(default_factory=list)
    filters_applied: dict[str, Any] = Field(
        default_factory=dict, description="The concrete filters used."
    )
    total_studies_matched: int | None = Field(
        default=None, description="From countTotal when available."
    )
    studies_analyzed: int = Field(
        description="How many records the aggregation actually consumed."
    )
    data_timestamp: str | None = Field(default=None, description="CT.gov dataTimestamp.")
    citation_cap: int | None = Field(
        default=None,
        description=(
            "Per-datum citation limit applied to this response (None if uncapped). "
            "A datum whose measure value exceeds this shows a representative sample; "
            "the full set is reachable via the datum's ClinicalTrials.gov query."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description='e.g. "312 studies had unparseable start dates and were excluded".',
    )
    plan: AnalysisPlan | None = Field(
        default=None, description="Populated only when options.debug is true."
    )


class VisualizationResponse(BaseModel):
    """The successful response envelope."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="uuid4 string.")
    visualization: VizSpec
    meta: Meta


class ErrorDetail(BaseModel):
    """Structured error detail carrying the failing pipeline stage."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="Short machine code, e.g. upstream_unavailable.")
    stage: PipelineStage = Field(description="Where it failed.")
    message: str = Field(description="Human-readable.")
    details: dict[str, Any] | None = Field(default=None, description="Optional context.")


class ErrorResponse(BaseModel):
    """The error response envelope."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    error: ErrorDetail
