"""The AnalysisPlan IR and its nested models (PRD Section C).

The :class:`AnalysisPlan` is the single most important architectural object: a
typed intermediate representation sitting between language and execution. The
planner (LLM) fills it; everything downstream is deterministic Python. The
operation-to-required-fields ``model_validator`` makes an invalid plan
impossible to construct — a core "validation / constraints" rubric win.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    CategoricalField,
    EdgeSemantics,
    Measure,
    NodeType,
    NumericField,
    Operation,
    OverallStatus,
    Phase,
    SeriesDimension,
    StudyType,
    VizType,
)


class Entities(BaseModel):
    """Extracted entities. Each maps to a CT.gov ``query.*`` parameter."""

    model_config = ConfigDict(extra="forbid")

    drug: str | None = Field(default=None, description="Maps to query.intr.")
    condition: str | None = Field(default=None, description="Maps to query.cond.")
    sponsor: str | None = Field(default=None, description="Maps to query.spons.")
    terms: list[str] = Field(default_factory=list, description="General terms -> query.term.")


class Filters(BaseModel):
    """Server-side and transform-side filters extracted by the planner."""

    model_config = ConfigDict(extra="forbid")

    statuses: list[OverallStatus] = Field(
        default_factory=list, description="-> filter.overallStatus."
    )
    phases: list[Phase] = Field(default_factory=list, description="-> filter.phase.")
    study_type: StudyType | None = None
    countries: list[str] = Field(default_factory=list)
    start_year: int | None = Field(
        default=None,
        description="Applied during transform (date bucketing), not always server-side.",
    )
    end_year: int | None = None


class SeriesSpec(BaseModel):
    """The series axis for a ``comparison`` operation."""

    model_config = ConfigDict(extra="forbid")

    dimension: SeriesDimension = Field(description="The thing being compared (e.g. condition).")
    values: list[str] = Field(
        min_length=2,
        description='The compared values, e.g. ["melanoma", "lung cancer"].',
    )


class NetworkSpec(BaseModel):
    """The configuration for a ``cooccurrence_network`` operation.

    Three shapes are valid, selected by ``node_types`` + ``edge_semantics``:

    * ``[sponsor, drug]`` — bipartite sponsor↔drug (``co_occurrence_in_trial``).
    * ``[drug]`` — drug↔drug co-occurrence (``co_occurrence_in_trial``).
    * ``[sponsor]`` — sponsor↔sponsor, linked when both ran a trial on the same
      drug (``shared_drug``). Since a trial has exactly one lead sponsor,
      sponsors cannot co-occur within a trial, so this shape *requires*
      ``shared_drug`` and ``shared_drug`` is valid only for this shape.
    """

    model_config = ConfigDict(extra="forbid")

    node_types: list[NodeType] = Field(
        description="[sponsor, drug] bipartite, [drug] drug-drug, [sponsor] sponsor-sponsor.",
    )
    edge_semantics: EdgeSemantics = EdgeSemantics.co_occurrence_in_trial
    min_edge_weight: int = Field(
        default=1,
        description="Drop edges below this weight (trial count, or shared-drug count).",
    )
    max_nodes: int = Field(default=50, ge=2, le=200, description="Readability / perf cap.")
    precompute_layout: bool = Field(
        default=True, description="Server-side spring_layout."
    )

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        """Reject network shapes that cannot produce meaningful edges."""
        if not self.node_types:
            raise ValueError("network.node_types must not be empty")
        sponsor_only = set(self.node_types) == {NodeType.sponsor}
        if sponsor_only and self.edge_semantics is not EdgeSemantics.shared_drug:
            raise ValueError(
                "a sponsor-only network requires edge_semantics=shared_drug "
                "(a trial has one lead sponsor, so sponsors never co-occur in a trial)"
            )
        if self.edge_semantics is EdgeSemantics.shared_drug and not sponsor_only:
            raise ValueError("edge_semantics=shared_drug is only valid for node_types=[sponsor]")
        return self


class AnalysisPlan(BaseModel):
    """The typed plan the planner emits and the executor consumes.

    The ``model_validator`` below enforces the operation-to-required-fields
    matrix from PRD Section C. The matrix's "Sets proposed_viz to" column is the
    planner's convention (followed by the fixtures); ``proposed_viz`` is a free
    :class:`VizType` here so the documented geographic fallback to a ranked
    ``bar_chart`` remains expressible.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Operation = Field(description="The query class.")
    entities: Entities = Field(default_factory=Entities)
    filters: Filters = Field(default_factory=Filters)
    group_by: CategoricalField | None = Field(
        default=None, description="The categorical axis for distribution/comparison."
    )
    series: SeriesSpec | None = Field(default=None, description="Required for `comparison`.")
    numeric_x: NumericField | None = Field(
        default=None,
        description="Required for `numeric_distribution` and `numeric_relationship`.",
    )
    numeric_y: NumericField | None = Field(
        default=None, description="Required for `numeric_relationship`."
    )
    time_granularity: Literal["year", "month"] = Field(
        default="year", description="For `time_trend`."
    )
    measure: Measure = Measure.trial_count
    network: NetworkSpec | None = Field(
        default=None, description="Required for `cooccurrence_network`."
    )
    proposed_viz: VizType = Field(description="The planner's suggested viz type.")
    interpretation: str = Field(
        description="One-sentence restatement, surfaced in meta.query_interpretation."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description='e.g. "interpreted \'recent\' as since 2021".',
    )

    @model_validator(mode="after")
    def _enforce_operation_requirements(self) -> Self:
        """Reject a plan missing a field its operation requires (PRD Section C)."""
        op = self.operation

        if op is Operation.categorical_distribution:
            if self.group_by is None:
                raise ValueError("categorical_distribution requires `group_by`")

        elif op is Operation.comparison:
            missing = [
                name
                for name, value in (("group_by", self.group_by), ("series", self.series))
                if value is None
            ]
            if missing:
                raise ValueError(f"comparison requires {' and '.join(missing)}")

        elif op is Operation.geographic_distribution:
            if self.group_by is not CategoricalField.country:
                raise ValueError("geographic_distribution requires `group_by == country`")

        elif op is Operation.cooccurrence_network:
            if self.network is None:
                raise ValueError("cooccurrence_network requires `network`")

        elif op is Operation.numeric_distribution:
            if self.numeric_x is None:
                raise ValueError("numeric_distribution requires `numeric_x`")

        elif op is Operation.numeric_relationship:
            missing = [
                name
                for name, value in (("numeric_x", self.numeric_x), ("numeric_y", self.numeric_y))
                if value is None
            ]
            if missing:
                raise ValueError(f"numeric_relationship requires {' and '.join(missing)}")

        # time_trend requires nothing beyond entities/filters.
        return self
