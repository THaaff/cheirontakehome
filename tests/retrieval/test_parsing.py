"""parse_study / parse_pages: null-safe extraction and enum coercion."""

from __future__ import annotations

from datetime import date
from typing import Any

from _helpers import load_raw

from app.contracts import (
    InterventionType,
    OverallStatus,
    Phase,
    SponsorClass,
    StudyType,
)
from app.retrieval.parsing import parse_pages, parse_study
from app.retrieval.warnings import WarningsCollector


def _wrap(study: dict[str, Any]) -> dict[str, Any]:
    """A protocolSection envelope around the given module dict."""
    return {"protocolSection": study}


def test_parses_full_record_positive_path() -> None:
    """The full captured record exercises every populated field."""
    warnings = WarningsCollector()
    record = parse_study(load_raw("study_full.json"), warnings)

    assert record is not None
    assert record.nct_id == "NCT03240016"
    assert record.phases == [Phase.PHASE2]
    assert record.overall_status is OverallStatus.COMPLETED
    assert record.study_type is StudyType.INTERVENTIONAL
    assert record.lead_sponsor_name == "University of Michigan Rogel Cancer Center"
    assert record.lead_sponsor_class is SponsorClass.OTHER
    assert record.start_date == date(2018, 2, 8)
    assert record.start_date_raw == "2018-02-08"
    assert record.completion_date == date(2023, 6, 23)
    assert record.intervention_types == [InterventionType.DRUG, InterventionType.DRUG]
    assert record.intervention_names == ["Pembrolizumab", "Abraxane"]
    assert record.conditions == ["Urothelial Carcinoma"]
    assert record.countries == ["United States"]
    assert record.enrollment_count == 36
    assert warnings.list() == []


def test_missing_interventions_yields_empty_list_no_exception() -> None:
    """Acceptance: a study missing the interventions array parses to []."""
    warnings = WarningsCollector()
    record = parse_study(
        _wrap({"identificationModule": {"nctId": "NCT00000001"}}), warnings
    )
    assert record is not None
    assert record.intervention_names == []
    assert record.intervention_types == []
    assert record.conditions == []
    assert record.countries == []
    assert record.phases == []
    assert record.start_date is None
    assert record.start_date_raw is None


def test_study_without_nct_id_is_skipped() -> None:
    warnings = WarningsCollector()
    assert parse_study(_wrap({"statusModule": {"overallStatus": "RECRUITING"}}), warnings) is None
    assert any("nctId" in w for w in warnings.list())


def test_country_dedup_preserves_order() -> None:
    warnings = WarningsCollector()
    record = parse_study(
        _wrap(
            {
                "identificationModule": {"nctId": "NCT2"},
                "contactsLocationsModule": {
                    "locations": [
                        {"country": "United States"},
                        {"country": "France"},
                        {"country": "United States"},
                        {},
                        {"country": "France"},
                    ]
                },
            }
        ),
        warnings,
    )
    assert record is not None
    assert record.countries == ["United States", "France"]


def test_unparseable_start_date_keeps_raw() -> None:
    warnings = WarningsCollector()
    record = parse_study(
        _wrap(
            {
                "identificationModule": {"nctId": "NCT3"},
                "statusModule": {"startDateStruct": {"date": "Fall 2018"}},
            }
        ),
        warnings,
    )
    assert record is not None
    assert record.start_date is None
    assert record.start_date_raw == "Fall 2018"


def test_expanded_access_statuses_parse_first_class() -> None:
    """The completed OverallStatus set parses expanded-access values, no coercion.

    These two values appeared in live data and previously fell through to
    UNKNOWN-with-warning; now they resolve to first-class members silently.
    """
    for raw_status, expected in (
        ("NO_LONGER_AVAILABLE", OverallStatus.NO_LONGER_AVAILABLE),
        ("TEMPORARILY_NOT_AVAILABLE", OverallStatus.TEMPORARILY_NOT_AVAILABLE),
        ("AVAILABLE", OverallStatus.AVAILABLE),
        ("APPROVED_FOR_MARKETING", OverallStatus.APPROVED_FOR_MARKETING),
        ("WITHHELD", OverallStatus.WITHHELD),
    ):
        warnings = WarningsCollector()
        record = parse_study(
            _wrap(
                {
                    "identificationModule": {"nctId": "NCT_EA"},
                    "statusModule": {"overallStatus": raw_status},
                }
            ),
            warnings,
        )
        assert record is not None
        assert record.overall_status is expected
        assert warnings.list() == []  # first-class: no coercion warning


def _unknown_enum_study(nct_id: str) -> dict[str, Any]:
    return _wrap(
        {
            "identificationModule": {"nctId": nct_id},
            "statusModule": {"overallStatus": "FOO_STATUS"},
            "designModule": {"studyType": "WEIRD_TYPE", "phases": ["PHASE9", "PHASE2"]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"class": "ZZZ"}},
            "armsInterventionsModule": {
                "interventions": [{"type": "UNOBTAINIUM", "name": "x"}]
            },
        }
    )


def test_unknown_enum_values_are_coerced() -> None:
    warnings = WarningsCollector()
    record = parse_study(_unknown_enum_study("NCT4"), warnings)

    assert record is not None
    assert record.overall_status is OverallStatus.UNKNOWN
    assert record.lead_sponsor_class is SponsorClass.UNKNOWN
    assert record.study_type is None  # no catch-all member -> None
    assert record.intervention_types == [InterventionType.OTHER]
    assert record.phases == [Phase.PHASE2]  # PHASE9 dropped, PHASE2 kept
    assert warnings.list()  # warnings emitted


def test_enum_coercion_warnings_are_deduplicated() -> None:
    """Two studies with the same bad value produce one warning, not two."""
    warnings = WarningsCollector()
    records, total = parse_pages(
        [{"studies": [_unknown_enum_study("NCT5"), _unknown_enum_study("NCT6")]}],
        warnings,
    )
    assert total is None
    assert len(records) == 2
    status_warnings = [w for w in warnings.list() if "FOO_STATUS" in w]
    assert len(status_warnings) == 1


def test_parse_pages_reports_total_and_unparseable_dates() -> None:
    warnings = WarningsCollector()
    pages = [
        {
            "totalCount": 1234,
            "studies": [
                _wrap(
                    {
                        "identificationModule": {"nctId": "NCT7"},
                        "statusModule": {"startDateStruct": {"date": "Fall 2018"}},
                    }
                ),
                _wrap(
                    {
                        "identificationModule": {"nctId": "NCT8"},
                        "statusModule": {"startDateStruct": {"date": "2020-05-01"}},
                    }
                ),
            ],
        },
        {"studies": [_wrap({"identificationModule": {"nctId": "NCT9"}})]},
    ]
    records, total = parse_pages(pages, warnings)
    assert total == 1234
    assert [r.nct_id for r in records] == ["NCT7", "NCT8", "NCT9"]
    assert any("unparseable start dates" in w for w in warnings.list())
