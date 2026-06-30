"""ChartDatum extra="allow" behavior (PRD Section K)."""

from __future__ import annotations

from app.contracts import ChartDatum, Citation


def test_chart_datum_accepts_arbitrary_dimension_keys() -> None:
    datum = ChartDatum.model_validate(
        {
            "phase": "PHASE3",
            "trial_count": 78,
            "citations": [{"nct_id": "NCT02506153", "excerpt": "PHASE3"}],
        }
    )
    dumped = datum.model_dump()
    # Arbitrary dimension/measure keys are preserved via extra="allow".
    assert dumped["phase"] == "PHASE3"
    assert dumped["trial_count"] == 78
    # citations is a typed list of Citation.
    assert len(datum.citations) == 1
    assert isinstance(datum.citations[0], Citation)
    assert datum.citations[0].nct_id == "NCT02506153"


def test_chart_datum_defaults_citations_to_empty() -> None:
    datum = ChartDatum.model_validate({"year": 2021, "trial_count": 84})
    assert datum.citations == []
    dumped = datum.model_dump()
    assert dumped["year"] == 2021
    assert dumped["trial_count"] == 84


def test_chart_datum_roundtrip_preserves_extras() -> None:
    datum = ChartDatum.model_validate(
        {"lead_sponsor_class": "INDUSTRY", "series": "melanoma", "trial_count": 132}
    )
    reparsed = ChartDatum.model_validate_json(datum.model_dump_json())
    assert reparsed == datum
