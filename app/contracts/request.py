"""Inbound request models (PRD Section B).

These are the *only* shapes a client sends. The optional structured fields are
hints the planner may use to disambiguate; they never bypass the planner.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Phase, RequestMode


class RequestOptions(BaseModel):
    """Per-request execution knobs."""

    model_config = ConfigDict(extra="forbid")

    mode: RequestMode = Field(
        default=RequestMode.live,
        description="`replay` reads cached responses + recorded plans.",
    )
    max_studies: int = Field(
        default=25000,
        ge=1,
        le=50000,
        description=(
            "Page-budget cap for client-side aggregation. Defaults high enough to "
            "analyze the full match for a realistic single-entity query; a truly "
            "huge match still truncates at this ceiling (with a warning)."
        ),
    )
    force_refresh: bool = Field(
        default=False,
        description="Bypass cache in live mode.",
    )
    debug: bool = Field(
        default=False,
        description="When true, echo the AnalysisPlan in meta.plan.",
    )


class VisualizationRequest(BaseModel):
    """A natural-language query plus optional structured hints."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The natural-language question.")
    drug_name: str | None = Field(default=None, description="Optional hint to the planner.")
    condition: str | None = Field(default=None, description="Optional hint to the planner.")
    sponsor: str | None = Field(default=None, description="Optional hint to the planner.")
    phase: Phase | None = Field(default=None, description="Optional hint to the planner.")
    country: str | None = Field(default=None, description="Optional hint to the planner.")
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    options: RequestOptions = Field(default_factory=RequestOptions)

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty or whitespace-only")
        return stripped

    @model_validator(mode="after")
    def _check_year_range(self) -> Self:
        if (
            self.start_year is not None
            and self.end_year is not None
            and self.start_year > self.end_year
        ):
            raise ValueError("start_year must be <= end_year")
        return self
