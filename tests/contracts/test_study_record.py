"""Retrieval->transform interface: StudyRecord / RetrievalResult (PRD Section D2)."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import FIXTURES_DIR, load_json
from pydantic import TypeAdapter, ValidationError

from app.contracts import RetrievalResult, StudyRecord

STUDY_RECORDS_FIXTURE = FIXTURES_DIR / "raw" / "study_records.json"


def test_study_record_is_tolerant_to_absence() -> None:
    """Only nct_id is required; every list defaults to [] and every scalar to None."""
    rec = StudyRecord(nct_id="NCT00000000")
    assert rec.nct_id == "NCT00000000"
    assert rec.phases == []
    assert rec.intervention_types == []
    assert rec.intervention_names == []
    assert rec.conditions == []
    assert rec.countries == []
    assert rec.brief_title is None
    assert rec.overall_status is None
    assert rec.study_type is None
    assert rec.lead_sponsor_class is None
    assert rec.start_date is None
    assert rec.start_date_raw is None
    assert rec.completion_date is None
    assert rec.enrollment_count is None


def test_study_record_requires_nct_id() -> None:
    with pytest.raises(ValidationError):
        StudyRecord()  # type: ignore[call-arg]


def test_study_record_parses_iso_dates() -> None:
    rec = StudyRecord(nct_id="NCT1", start_date="2018-02-08")  # type: ignore[arg-type]
    assert rec.start_date == date(2018, 2, 8)


def test_retrieval_result_requires_studies_analyzed() -> None:
    with pytest.raises(ValidationError):
        RetrievalResult(studies=[])  # type: ignore[call-arg]


def test_retrieval_result_defaults() -> None:
    result = RetrievalResult(studies_analyzed=0)
    assert result.studies == []
    assert result.total_matched is None
    assert result.data_timestamp is None
    assert result.warnings == []


def test_study_records_fixture_validates_as_list() -> None:
    records = TypeAdapter(list[StudyRecord]).validate_python(load_json(STUDY_RECORDS_FIXTURE))
    assert len(records) >= 10  # PRD Section J: ~10 hand-derived records
    assert all(r.nct_id.startswith("NCT") for r in records)


def test_study_records_fixture_exercises_messy_data_paths() -> None:
    """The hand-derived fixture deliberately covers the tolerant-handling cases."""
    records = TypeAdapter(list[StudyRecord]).validate_python(load_json(STUDY_RECORDS_FIXTURE))
    by_id = {r.nct_id: r for r in records}

    # An observational study with empty phases and no interventions.
    cohort = by_id["NCT03695952"]
    assert cohort.phases == []
    assert cohort.intervention_names == []
    assert cohort.study_type is not None and cohort.study_type.value == "OBSERVATIONAL"

    # An unparseable start date: start_date is None but the raw string is preserved.
    messy = by_id["NCT03666325"]
    assert messy.start_date is None
    assert messy.start_date_raw == "Fall 2018"

    # A multi-phase trial.
    assert any(len(r.phases) > 1 for r in records)
