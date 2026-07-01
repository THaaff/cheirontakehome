"""``PlannerOutput`` — the constraint-light Structured-Outputs target.

We do **not** point OpenAI strict Structured Outputs at :class:`AnalysisPlan`
directly. Strict mode forces ``additionalProperties:false``, treats every
optional as nullable, requires all properties, and silently ignores value
constraints (``min_length``, numeric ``ge``/``le``). ``AnalysisPlan`` carries
``Field`` bounds and a cross-field ``model_validator`` that strict mode can
neither express nor enforce at decode time.

So this module mirrors ``AnalysisPlan`` with a *constraint-light* schema: the
already-light :class:`Entities` and :class:`Filters` are reused as-is, ``series``
and ``network`` become plain local models with no ``Field`` bounds and no
validators, and every optional is written ``X | None``. The model emits one of
these; :func:`app.planner.client.plan_query` then re-validates it into the real
IR via ``AnalysisPlan.model_validate(...)``, where every contract constraint
actually runs. This cleanly separates "what we ask the model to emit" from "what
we enforce" and removes all strict-mode-compatibility risk.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.contracts import (
    CategoricalField,
    EdgeSemantics,
    Entities,
    Filters,
    Measure,
    NodeType,
    NumericField,
    Operation,
    SeriesDimension,
    VizType,
)


class PlannerSeries(BaseModel):
    """Constraint-light mirror of ``SeriesSpec`` (no ``min_length`` on values).

    The ``min_length=2`` constraint lives on the real ``SeriesSpec`` and is
    enforced when we map into ``AnalysisPlan`` — a comparison whose series has
    fewer than two values fails validation there and triggers the single retry.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: SeriesDimension
    values: list[str]


class PlannerNetwork(BaseModel):
    """Constraint-light mirror of ``NetworkSpec`` (no numeric bounds, all optional).

    Every field except ``node_types`` is ``X | None`` with no default that
    matters; on mapping, ``None`` is dropped so the real ``NetworkSpec`` defaults
    apply, and ``max_nodes`` bounds (2..200) are enforced there.
    """

    model_config = ConfigDict(extra="forbid")

    node_types: list[NodeType]
    edge_semantics: EdgeSemantics | None = None
    min_edge_weight: int | None = None
    max_nodes: int | None = None
    precompute_layout: bool | None = None


class PlannerOutput(BaseModel):
    """The schema the LLM fills. A constraint-light mirror of ``AnalysisPlan``.

    Reuses :class:`Entities`/:class:`Filters` directly (already light). Optionals
    are ``X | None``; fields that carry a meaningful default on ``AnalysisPlan``
    (``time_granularity``, ``measure``) are optional here so the model may omit
    them and the IR default applies after mapping.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Operation
    entities: Entities
    filters: Filters
    group_by: CategoricalField | None = None
    series: PlannerSeries | None = None
    numeric_x: NumericField | None = None
    numeric_y: NumericField | None = None
    time_granularity: Literal["year", "month"] | None = None
    measure: Measure | None = None
    network: PlannerNetwork | None = None
    proposed_viz: VizType
    interpretation: str
    assumptions: list[str]
