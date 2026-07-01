"""Enumerations for the ClinicalTrials.gov query-to-visualization contracts.

All enums are :class:`enum.StrEnum`, so their members serialize as their string
values directly. Enums whose values cross the wire to the ClinicalTrials.gov v2
API **mirror that API's controlled vocabulary exactly** (e.g. ``PHASE3``,
``RECRUITING``, ``INDUSTRY``). That is a deliberate decision (see
``docs/system-design.md`` §6): identical values mean no translation layer is
needed between our types and the upstream API, removing a whole class of
mapping bugs.

Internal taxonomy enums (operations, viz types, channel types) use lowercase
snake_case / Vega-Lite-style values, since they never round-trip to CT.gov.
"""

from __future__ import annotations

import enum

# ---------------------------------------------------------------------------
# Internal taxonomy (never crosses the wire to CT.gov)
# ---------------------------------------------------------------------------


class Operation(enum.StrEnum):
    """The closed set of query classes the planner may choose from.

    Adding a new analytical capability is "add an enum value plus a handler",
    not "rewrite the agent". This closed world is what makes the planner a
    classifier and makes hallucination of intent impossible.
    """

    time_trend = "time_trend"
    categorical_distribution = "categorical_distribution"
    comparison = "comparison"
    geographic_distribution = "geographic_distribution"
    cooccurrence_network = "cooccurrence_network"
    numeric_distribution = "numeric_distribution"
    numeric_relationship = "numeric_relationship"


class VizType(enum.StrEnum):
    """The closed set of visualization types, one per operation."""

    bar_chart = "bar_chart"
    grouped_bar_chart = "grouped_bar_chart"
    time_series = "time_series"
    scatter_plot = "scatter_plot"
    histogram = "histogram"
    choropleth_map = "choropleth_map"
    network_graph = "network_graph"


class CategoricalField(enum.StrEnum):
    """Categorical dimensions we can group/distribute on."""

    phase = "phase"
    overall_status = "overall_status"
    study_type = "study_type"
    lead_sponsor_class = "lead_sponsor_class"
    intervention_type = "intervention_type"
    country = "country"
    condition = "condition"


class NumericField(enum.StrEnum):
    """Numeric fields for histogram / scatter operations."""

    enrollment_count = "enrollment_count"
    duration_days = "duration_days"


class Measure(enum.StrEnum):
    """The aggregated measure computed per group.

    ``trial_count`` is the only measure the executor implements in v1.
    ``enrollment_sum`` and ``enrollment_mean`` are defined now (so the contract
    is stable) but reserved for a later phase.
    """

    trial_count = "trial_count"
    enrollment_sum = "enrollment_sum"
    enrollment_mean = "enrollment_mean"


class SeriesDimension(enum.StrEnum):
    """The dimension along which a ``comparison`` operation contrasts series."""

    drug = "drug"
    condition = "condition"
    sponsor = "sponsor"


class NodeType(enum.StrEnum):
    """Node categories in a co-occurrence network."""

    sponsor = "sponsor"
    drug = "drug"
    condition = "condition"


class EdgeSemantics(enum.StrEnum):
    """The meaning of an edge in a co-occurrence network.

    ``co_occurrence_in_trial`` connects two nodes that appear in the *same*
    trial (sponsor↔drug for a bipartite network, drug↔drug for a drug network).
    ``shared_drug`` connects two *sponsors* that each ran a trial on the same
    drug — the only sensible edge for a sponsor-only network, since a trial has
    exactly one lead sponsor and so sponsors can never co-occur within one.
    """

    co_occurrence_in_trial = "co_occurrence_in_trial"
    shared_drug = "shared_drug"


class ChannelType(enum.StrEnum):
    """Vega-Lite encoding channel types."""

    nominal = "nominal"
    ordinal = "ordinal"
    quantitative = "quantitative"
    temporal = "temporal"


class Renderer(enum.StrEnum):
    """How the frontend should render the spec.

    ``vega-lite`` and ``vega`` are both *chart* renderers (hence ``renderer``
    cannot be the discriminator of :data:`~app.contracts.viz.VizSpec`);
    ``graph`` is the node/edge renderer.
    """

    vega_lite = "vega-lite"
    vega = "vega"
    graph = "graph"


class RequestMode(enum.StrEnum):
    """Execution mode. ``replay`` reads cached responses + recorded plans."""

    live = "live"
    replay = "replay"


class PipelineStage(enum.StrEnum):
    """The pipeline stage at which an error occurred (carried on errors)."""

    validation = "validation"
    planning = "planning"
    retrieval = "retrieval"
    transform = "transform"
    visualization = "visualization"


# ---------------------------------------------------------------------------
# CT.gov controlled vocabularies (values mirror the v2 API exactly)
# ---------------------------------------------------------------------------


class Phase(enum.StrEnum):
    """Trial phase. Values mirror CT.gov ``protocolSection.designModule.phases``."""

    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"
    NA = "NA"


class OverallStatus(enum.StrEnum):
    """Trial status. Values mirror CT.gov ``overallStatus`` (complete set).

    Covers both the recruitment statuses and the expanded-access / special
    statuses (the last five). This is the authoritative set confirmed against
    live data; completing it (rather than carrying a subset) keeps the principle
    that our enums mirror the controlled vocabulary exactly, so a
    ``categorical_distribution`` grouped by status reports distinct
    expanded-access statuses instead of collapsing them into one misleadingly
    fat ``UNKNOWN`` bucket. The retrieval parser still coerces any value outside
    this set to :attr:`UNKNOWN` with a deduplicated warning, so a future API
    addition never hard-fails — completion just narrows what falls through that
    safety net.
    """

    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    AVAILABLE = "AVAILABLE"
    NO_LONGER_AVAILABLE = "NO_LONGER_AVAILABLE"
    TEMPORARILY_NOT_AVAILABLE = "TEMPORARILY_NOT_AVAILABLE"
    APPROVED_FOR_MARKETING = "APPROVED_FOR_MARKETING"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


class StudyType(enum.StrEnum):
    """Study type. Values mirror CT.gov ``protocolSection.designModule.studyType``."""

    INTERVENTIONAL = "INTERVENTIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"
    EXPANDED_ACCESS = "EXPANDED_ACCESS"


class SponsorClass(enum.StrEnum):
    """Lead sponsor agency class. Values mirror CT.gov ``leadSponsor.class``."""

    INDUSTRY = "INDUSTRY"
    NIH = "NIH"
    FED = "FED"
    OTHER_GOV = "OTHER_GOV"
    INDIV = "INDIV"
    NETWORK = "NETWORK"
    AMBIG = "AMBIG"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class InterventionType(enum.StrEnum):
    """Intervention type. Values mirror CT.gov ``interventions[].type``."""

    DRUG = "DRUG"
    BIOLOGICAL = "BIOLOGICAL"
    DEVICE = "DEVICE"
    PROCEDURE = "PROCEDURE"
    BEHAVIORAL = "BEHAVIORAL"
    DIETARY_SUPPLEMENT = "DIETARY_SUPPLEMENT"
    RADIATION = "RADIATION"
    GENETIC = "GENETIC"
    DIAGNOSTIC_TEST = "DIAGNOSTIC_TEST"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    OTHER = "OTHER"
