"""System prompt and few-shot examples for the planner.

The prompt frames the model as a *classifier and extractor*, not an agent: it
picks one of seven operations, extracts entities/filters/grouping, and proposes
a viz. The few-shots are kept as typed :class:`PlannerOutput` objects (one per
operation) so they can never drift from the schema — they are serialized into
the conversation at call time.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from openai.types.responses import EasyInputMessageParam, ResponseInputItemParam

from app.contracts import (
    CategoricalField,
    EdgeSemantics,
    Entities,
    Filters,
    Measure,
    NodeType,
    NumericField,
    Operation,
    OverallStatus,
    SeriesDimension,
    VisualizationRequest,
    VizType,
)

from .schema import PlannerNetwork, PlannerOutput, PlannerSeries

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You translate a natural-language question about clinical trials into a structured \
analysis plan. You are a classifier and extractor, not a data analyst: you choose \
ONE operation, extract the entities and filters the question names, pick a grouping, \
and propose a visualization. You never fetch data, never compute a count, and never \
emit any numeric data value. Downstream deterministic code does all of that.

Choose exactly one `operation` using these cues:
- time_trend — counts over time; "per year", "over time", "trend", "since 20XX", \
"by year/month". Set time_granularity (year unless the question implies months). For a \
per-category breakdown over time ("per year per phase", "by phase over time", "trend by \
sponsor class"), ALSO set group_by to that categorical field — the result is one line per \
value. Leave group_by null for a single overall trend line.
- categorical_distribution — one categorical breakdown; "distribution of / breakdown \
of / how many across <category>" (phases, statuses, sponsor classes, etc.). Set group_by.
- comparison — contrasting two or more named values along a dimension; "compare A vs B", \
"A versus B", "across two conditions". Set BOTH group_by (the categorical axis) and \
series (dimension = drug | condition | sponsor; values = the compared items, >= 2).
- geographic_distribution — "which countries", "where", "by country/location". Set \
group_by = country.
- cooccurrence_network — relationships / co-occurrence / combinations / networks; \
"network of X and Y", "drug-drug combinations", "which sponsors work with which drugs". \
Set network. node_types = [sponsor, drug] for bipartite and [drug] for drug-drug (both \
edge_semantics = co_occurrence_in_trial); node_types = [sponsor] with edge_semantics = \
shared_drug for a sponsor-to-sponsor network ("which sponsors work on the same drugs", \
"sponsors developing similar drugs") — sponsors link when they run a trial on a shared drug.
- numeric_distribution — distribution of a SINGLE numeric field; "distribution of \
enrollment sizes", "how large are the trials". Set numeric_x.
- numeric_relationship — relationship between TWO numeric fields; "X vs Y", "enrollment \
vs duration", "does X correlate with Y". Set numeric_x and numeric_y.

Field vocabularies you may use:
- group_by (CategoricalField): phase, overall_status, study_type, lead_sponsor_class, \
intervention_type, country, condition.
- series.dimension (SeriesDimension): drug, condition, sponsor.
- numeric_x / numeric_y (NumericField): enrollment_count, duration_days.

Extraction rules:
- entities: drug -> entities.drug, condition -> entities.condition, sponsor -> \
entities.sponsor; otherwise general search terms -> entities.terms.
- filters: recruitment statuses (e.g. RECRUITING) -> filters.statuses; phases \
(PHASE1..PHASE4, EARLY_PHASE1, NA) -> filters.phases; INTERVENTIONAL/OBSERVATIONAL -> \
filters.study_type; countries -> filters.countries; year bounds -> filters.start_year / \
filters.end_year.
- time ranges: resolve RELATIVE ranges against today's date (given below), and record \
the resolution in `assumptions`. "the last N years" -> start_year = current_year - (N - 1) \
and end_year = current_year (an N-year window ending this year). "since 20XX" -> \
start_year = 20XX. A trend of how many trials there HAVE been is bounded by now: set \
end_year = current_year (for both "since 20XX" and past-tense questions like "have there \
been"/"were run") so trials with future, not-yet-started start dates don't appear. Only \
leave end_year open (null) or set it in the future when the question explicitly asks about \
upcoming/planned/projected trials.

Hard rules:
- Never invent data, counts, drugs, or conditions the question does not mention.
- Always write `interpretation`: one plain-English sentence restating what will be computed.
- Always populate `assumptions` with any inference you made (e.g. resolving "recent" to a \
start year, defaulting a granularity, or choosing a grouping the question only implied). \
Use an empty list only when you made no such inference.
- Use the user's structured hints when present; they disambiguate the question and do not \
replace your job of classifying and extracting.
"""

# ---------------------------------------------------------------------------
# Few-shots — one typed PlannerOutput per operation
# ---------------------------------------------------------------------------

FEW_SHOTS: list[tuple[str, PlannerOutput]] = [
    (
        "How has the number of trials for pembrolizumab changed per year since 2018?",
        PlannerOutput(
            operation=Operation.time_trend,
            entities=Entities(drug="pembrolizumab"),
            filters=Filters(start_year=2018, end_year=2026),
            time_granularity="year",
            measure=Measure.trial_count,
            proposed_viz=VizType.time_series,
            interpretation="Annual count of pembrolizumab trials since 2018.",
            assumptions=[
                "Interpreted 'since 2018' as start_year >= 2018, bucketed by year.",
                "Bounded end_year at the current year so not-yet-started trials are excluded.",
            ],
        ),
    ),
    (
        "How many brain cancer trials have there been per year per trial phase "
        "for the last five years?",
        PlannerOutput(
            operation=Operation.time_trend,
            entities=Entities(condition="brain cancer"),
            filters=Filters(start_year=2022, end_year=2026),
            group_by=CategoricalField.phase,
            time_granularity="year",
            measure=Measure.trial_count,
            proposed_viz=VizType.time_series,
            interpretation=(
                "Annual count of brain cancer trials by phase over the last five years."
            ),
            assumptions=[
                "Resolved 'the last five years' to start_year=2022, end_year=2026 "
                "against today's date.",
                "Past-tense ('have there been') bounds the range at the current year, "
                "so future-dated trials are excluded.",
            ],
        ),
    ),
    (
        "What is the distribution of melanoma trials across phases?",
        PlannerOutput(
            operation=Operation.categorical_distribution,
            entities=Entities(condition="melanoma"),
            filters=Filters(),
            group_by=CategoricalField.phase,
            proposed_viz=VizType.bar_chart,
            interpretation="Distribution of melanoma trials across clinical trial phases.",
            assumptions=[],
        ),
    ),
    (
        "Compare sponsor types for melanoma versus lung cancer.",
        PlannerOutput(
            operation=Operation.comparison,
            entities=Entities(),
            filters=Filters(),
            group_by=CategoricalField.lead_sponsor_class,
            series=PlannerSeries(
                dimension=SeriesDimension.condition, values=["melanoma", "lung cancer"]
            ),
            proposed_viz=VizType.grouped_bar_chart,
            interpretation="Sponsor-class mix compared across melanoma and lung cancer trials.",
            assumptions=[],
        ),
    ),
    (
        "Which countries have the most actively recruiting melanoma trials?",
        PlannerOutput(
            operation=Operation.geographic_distribution,
            entities=Entities(condition="melanoma"),
            filters=Filters(statuses=[OverallStatus.RECRUITING]),
            group_by=CategoricalField.country,
            proposed_viz=VizType.choropleth_map,
            interpretation="Countries with the most actively recruiting melanoma trials.",
            assumptions=[],
        ),
    ),
    (
        "Show the network of sponsors and drugs that co-occur in melanoma trials.",
        PlannerOutput(
            operation=Operation.cooccurrence_network,
            entities=Entities(condition="melanoma"),
            filters=Filters(),
            network=PlannerNetwork(
                node_types=[NodeType.sponsor, NodeType.drug],
                edge_semantics=EdgeSemantics.co_occurrence_in_trial,
                min_edge_weight=2,
                max_nodes=50,
                precompute_layout=True,
            ),
            proposed_viz=VizType.network_graph,
            interpretation="Network of sponsors and drugs co-occurring in melanoma trials.",
            assumptions=[],
        ),
    ),
    (
        "Which sponsors work on the same drugs in melanoma trials?",
        PlannerOutput(
            operation=Operation.cooccurrence_network,
            entities=Entities(condition="melanoma"),
            filters=Filters(),
            network=PlannerNetwork(
                node_types=[NodeType.sponsor],
                edge_semantics=EdgeSemantics.shared_drug,
                min_edge_weight=1,
                max_nodes=50,
                precompute_layout=True,
            ),
            proposed_viz=VizType.network_graph,
            interpretation="Network of melanoma sponsors linked by drugs they both study.",
            assumptions=[],
        ),
    ),
    (
        "What is the distribution of enrollment sizes for melanoma trials?",
        PlannerOutput(
            operation=Operation.numeric_distribution,
            entities=Entities(condition="melanoma"),
            filters=Filters(),
            numeric_x=NumericField.enrollment_count,
            proposed_viz=VizType.histogram,
            interpretation="Distribution of enrollment sizes across melanoma trials.",
            assumptions=[],
        ),
    ),
    (
        "Is there a relationship between enrollment size and study duration in melanoma trials?",
        PlannerOutput(
            operation=Operation.numeric_relationship,
            entities=Entities(condition="melanoma"),
            filters=Filters(),
            numeric_x=NumericField.enrollment_count,
            numeric_y=NumericField.duration_days,
            proposed_viz=VizType.scatter_plot,
            interpretation=(
                "Relationship between enrollment size and study duration for melanoma trials."
            ),
            assumptions=[],
        ),
    ),
]


# ---------------------------------------------------------------------------
# Message assembly
# ---------------------------------------------------------------------------


def _render_hints(request: VisualizationRequest) -> str:
    """Render the request's optional structured hints as explicit context."""
    pairs: list[tuple[str, object]] = [
        ("drug_name", request.drug_name),
        ("condition", request.condition),
        ("sponsor", request.sponsor),
        ("phase", request.phase),
        ("country", request.country),
        ("start_year", request.start_year),
        ("end_year", request.end_year),
    ]
    present = [f"- {name}: {value}" for name, value in pairs if value is not None]
    if not present:
        return ""
    return "\n\nStructured hints provided by the user (use them to disambiguate):\n" + "\n".join(
        present
    )


def _msg(role: Literal["system", "user", "assistant"], content: str) -> ResponseInputItemParam:
    return EasyInputMessageParam(role=role, content=content)


def build_input(request: VisualizationRequest) -> list[ResponseInputItemParam]:
    """Build the full Responses-API ``input``: system + few-shots + user query.

    Today's date is injected so the model can resolve relative time expressions
    ("the last five years", "recent") into concrete year bounds. This is the only
    non-deterministic part of the prompt — captures record the resulting plan, so
    replay is unaffected.
    """
    messages: list[ResponseInputItemParam] = [
        _msg("system", SYSTEM_PROMPT),
        _msg(
            "system",
            f"Today's date is {date.today().isoformat()}. "
            "Resolve every relative time expression against it.",
        ),
    ]
    for query, output in FEW_SHOTS:
        messages.append(_msg("user", query))
        messages.append(_msg("assistant", output.model_dump_json()))
    messages.append(_msg("user", request.query + _render_hints(request)))
    return messages
