"""The labeled eval set: ~15 queries spanning all seven operations.

Each :class:`EvalCase` carries the query (plus any structured hints) and the
labels we assert: the expected ``operation`` (exact) and the key expected
extractions (entity substrings, ``group_by``, whether ``series``/``network`` is
set, numeric fields, a year floor). A few cases are intentionally ambiguous
(``ambiguous=True``) to exercise the planner's judgment and its ``assumptions``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts import (
    CategoricalField,
    NumericField,
    Operation,
    Phase,
    VisualizationRequest,
)


@dataclass(frozen=True)
class EvalCase:
    """One labeled query and the expectations the harness scores it against."""

    id: str
    query: str
    expected_operation: Operation

    # Optional structured hints passed on the request (mirror VisualizationRequest).
    drug_name: str | None = None
    condition_hint: str | None = None
    sponsor: str | None = None
    phase: Phase | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None

    # Key expected extractions (None = not scored for this case).
    expected_drug: str | None = None
    expected_condition: str | None = None
    expected_group_by: CategoricalField | None = None
    expects_series: bool = False
    expects_network: bool = False
    expected_numeric_x: NumericField | None = None
    expected_numeric_y: NumericField | None = None
    expected_start_year: int | None = None

    ambiguous: bool = False

    def to_request(self) -> VisualizationRequest:
        return VisualizationRequest(
            query=self.query,
            drug_name=self.drug_name,
            condition=self.condition_hint,
            sponsor=self.sponsor,
            phase=self.phase,
            country=self.country,
            start_year=self.start_year,
            end_year=self.end_year,
        )


EVAL_CASES: list[EvalCase] = [
    # --- time_trend -------------------------------------------------------
    EvalCase(
        id="time_trend_pembrolizumab",
        query="How has the number of trials for pembrolizumab changed per year since 2018?",
        expected_operation=Operation.time_trend,
        expected_drug="pembrolizumab",
        expected_start_year=2018,
    ),
    EvalCase(
        id="time_trend_diabetes_monthly",
        query="Show the monthly trend of new diabetes trials over time.",
        expected_operation=Operation.time_trend,
        expected_condition="diabetes",
    ),
    EvalCase(
        id="time_trend_recent_immunotherapy",
        query="Show recent immunotherapy trial activity over the last several years.",
        expected_operation=Operation.time_trend,
        ambiguous=True,
    ),
    # --- categorical_distribution ----------------------------------------
    EvalCase(
        id="categorical_melanoma_phase",
        query="What is the distribution of melanoma trials across phases?",
        expected_operation=Operation.categorical_distribution,
        expected_condition="melanoma",
        expected_group_by=CategoricalField.phase,
    ),
    EvalCase(
        id="categorical_covid_status",
        query="Break down COVID-19 trials by their recruitment status.",
        expected_operation=Operation.categorical_distribution,
        expected_condition="covid",
        expected_group_by=CategoricalField.overall_status,
    ),
    # --- comparison ------------------------------------------------------
    EvalCase(
        id="comparison_sponsor_two_conditions",
        query="Compare sponsor types for melanoma versus lung cancer.",
        expected_operation=Operation.comparison,
        expected_group_by=CategoricalField.lead_sponsor_class,
        expects_series=True,
    ),
    EvalCase(
        id="comparison_phase_two_drugs",
        query="Compare the phase distribution of trials for nivolumab versus pembrolizumab.",
        expected_operation=Operation.comparison,
        expected_group_by=CategoricalField.phase,
        expects_series=True,
    ),
    # --- geographic_distribution -----------------------------------------
    EvalCase(
        id="geographic_melanoma_recruiting",
        query="Which countries have the most actively recruiting melanoma trials?",
        expected_operation=Operation.geographic_distribution,
        expected_condition="melanoma",
        expected_group_by=CategoricalField.country,
    ),
    EvalCase(
        id="geographic_alzheimers",
        query="Where in the world are Alzheimer's disease trials being conducted?",
        expected_operation=Operation.geographic_distribution,
        expected_condition="alzheimer",
        expected_group_by=CategoricalField.country,
    ),
    # --- cooccurrence_network --------------------------------------------
    EvalCase(
        id="network_sponsors_drugs_melanoma",
        query="Show the network of sponsors and drugs that co-occur in melanoma trials.",
        expected_operation=Operation.cooccurrence_network,
        expected_condition="melanoma",
        expects_network=True,
    ),
    EvalCase(
        id="network_drug_combinations_breast",
        query="What drug combinations are commonly studied together in breast cancer trials?",
        expected_operation=Operation.cooccurrence_network,
        expected_condition="breast cancer",
        expects_network=True,
    ),
    # --- numeric_distribution --------------------------------------------
    EvalCase(
        id="numeric_distribution_enrollment",
        query="What is the distribution of enrollment sizes for melanoma trials?",
        expected_operation=Operation.numeric_distribution,
        expected_condition="melanoma",
        expected_numeric_x=NumericField.enrollment_count,
    ),
    EvalCase(
        id="numeric_distribution_duration",
        query="How long do diabetes trials typically run?",
        expected_operation=Operation.numeric_distribution,
        expected_condition="diabetes",
        expected_numeric_x=NumericField.duration_days,
        ambiguous=True,
    ),
    # --- numeric_relationship --------------------------------------------
    EvalCase(
        id="numeric_relationship_enrollment_duration",
        query=(
            "Is there a relationship between enrollment size and study duration "
            "in melanoma trials?"
        ),
        expected_operation=Operation.numeric_relationship,
        expected_condition="melanoma",
        expected_numeric_x=NumericField.enrollment_count,
        expected_numeric_y=NumericField.duration_days,
    ),
    EvalCase(
        id="numeric_relationship_enrollment_vs_duration",
        query="Plot enrollment against trial duration across lung cancer trials.",
        expected_operation=Operation.numeric_relationship,
        expected_condition="lung cancer",
        expected_numeric_x=NumericField.enrollment_count,
        expected_numeric_y=NumericField.duration_days,
    ),
]
