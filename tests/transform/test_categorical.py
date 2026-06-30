"""categorical_distribution: counts, multi-count semantics, and per-datum citations."""

from __future__ import annotations

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Operation,
    Phase,
    StudyRecord,
)
from app.transform import aggregate_categorical


def _plan(field: CategoricalField) -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.categorical_distribution,
        group_by=field,
        proposed_viz="bar_chart",
        interpretation="distribution",
    )


def _counts(dataset, dim: str) -> dict[str, int]:
    return {str(p.dims[dim]): int(p.value) for p in dataset.points}


def _ncts(dataset, dim: str, value: str) -> list[str]:
    point = next(p for p in dataset.points if p.dims[dim] == value)
    return [c.nct_id for c in point.citations]


def test_phase_multi_count(studies: list[StudyRecord]) -> None:
    dataset = aggregate_categorical(studies, _plan(CategoricalField.phase))
    counts = _counts(dataset, "phase")
    # PHASE2 appears in 7 trials, PHASE1 in 3, PHASE3 in 1 (one study has no phase).
    assert counts == {"PHASE2": 7, "PHASE1": 3, "PHASE3": 1}


def test_multi_count_study_appears_in_each_of_its_values(studies: list[StudyRecord]) -> None:
    dataset = aggregate_categorical(studies, _plan(CategoricalField.phase))
    # NCT06493552 is PHASE2 *and* PHASE3 — it must contribute to both buckets.
    assert "NCT06493552" in _ncts(dataset, "phase", "PHASE2")
    assert "NCT06493552" in _ncts(dataset, "phase", "PHASE3")


def test_study_without_the_field_is_excluded(studies: list[StudyRecord]) -> None:
    dataset = aggregate_categorical(studies, _plan(CategoricalField.phase))
    all_cited = {c.nct_id for p in dataset.points for c in p.citations}
    # NCT03695952 (observational, phases == []) contributes to no phase bucket.
    assert "NCT03695952" not in all_cited


def test_citations_match_contributors_exactly(studies: list[StudyRecord]) -> None:
    dataset = aggregate_categorical(studies, _plan(CategoricalField.phase))
    for point in dataset.points:
        value = point.dims["phase"]
        expected = {s.nct_id for s in studies if any(p.value == value for p in s.phases)}
        assert {c.nct_id for c in point.citations} == expected
        assert int(point.value) == len(expected)
        # Each cited excerpt is the value that produced the bucket.
        assert all(c.excerpt == value for c in point.citations)


def test_list_field_dedupes_within_a_study(studies: list[StudyRecord]) -> None:
    # NCT03240016 has intervention_types == [DRUG, DRUG]; it must count once for DRUG.
    dataset = aggregate_categorical(studies, _plan(CategoricalField.intervention_type))
    drug_ncts = _ncts(dataset, "intervention_type", "DRUG")
    assert drug_ncts.count("NCT03240016") == 1
    assert len(drug_ncts) == len(set(drug_ncts))


def test_scalar_field_counts_every_study_once(studies: list[StudyRecord]) -> None:
    dataset = aggregate_categorical(studies, _plan(CategoricalField.lead_sponsor_class))
    counts = _counts(dataset, "lead_sponsor_class")
    assert counts == {"OTHER": 5, "INDUSTRY": 4, "NETWORK": 1}
    assert sum(counts.values()) == len(studies)


def test_acceptance_scenario_phase2_is_five() -> None:
    # PRD acceptance: 3 studies Phase 2 only + 2 studies Phase 2 & 3 => Phase 2 count 5.
    synthetic = (
        [StudyRecord(nct_id=f"NCT0000000{i}", phases=[Phase.PHASE2]) for i in range(3)]
        + [
            StudyRecord(nct_id=f"NCT1000000{i}", phases=[Phase.PHASE2, Phase.PHASE3])
            for i in range(2)
        ]
        + [StudyRecord(nct_id=f"NCT2000000{i}", phases=[Phase.PHASE1]) for i in range(5)]
    )
    dataset = aggregate_categorical(synthetic, _plan(CategoricalField.phase))
    counts = _counts(dataset, "phase")
    assert counts["PHASE2"] == 5
    assert counts["PHASE3"] == 2
    assert counts["PHASE1"] == 5


def test_empty_input_is_safe() -> None:
    dataset = aggregate_categorical([], _plan(CategoricalField.phase))
    assert dataset.points == []
    assert dataset.warnings
    assert dataset.dimension_names == ["phase"]
