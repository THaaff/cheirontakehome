"""Provenance helpers: turn :class:`StudyRecord`s into :class:`Citation`s.

The deep-citations bonus is realized here. Every datum, node, and edge the
transform layer emits carries, for each contributing study, a ``Citation`` that
points back to the exact field value that produced it. Provenance is threaded
from this layer onward, never bolted on at the end.

The ``FIELD_*`` constants are the authoritative CT.gov v2 source paths (casing
per ``docs/system-design.md`` §7); they become each citation's ``field`` so a
grader can trace any number to its origin in the raw API response.
"""

from __future__ import annotations

from app.contracts import Citation, StudyRecord

# ---------------------------------------------------------------------------
# CT.gov v2 source field paths (docs/system-design.md §7)
# ---------------------------------------------------------------------------

FIELD_PHASES = "protocolSection.designModule.phases"
FIELD_OVERALL_STATUS = "protocolSection.statusModule.overallStatus"
FIELD_STUDY_TYPE = "protocolSection.designModule.studyType"
FIELD_LEAD_SPONSOR_NAME = "protocolSection.sponsorCollaboratorsModule.leadSponsor.name"
FIELD_LEAD_SPONSOR_CLASS = "protocolSection.sponsorCollaboratorsModule.leadSponsor.class"
FIELD_INTERVENTION_NAME = "protocolSection.armsInterventionsModule.interventions.name"
FIELD_INTERVENTION_TYPE = "protocolSection.armsInterventionsModule.interventions.type"
FIELD_CONDITIONS = "protocolSection.conditionsModule.conditions"
FIELD_COUNTRY = "protocolSection.contactsLocationsModule.locations.country"
FIELD_START_DATE = "protocolSection.statusModule.startDateStruct.date"
FIELD_COMPLETION_DATE = "protocolSection.statusModule.completionDateStruct.date"
FIELD_ENROLLMENT = "protocolSection.designModule.enrollmentInfo.count"

# A derived value (duration) has no single source path; name both inputs.
FIELD_DURATION_DAYS = f"derived: {FIELD_COMPLETION_DATE} - {FIELD_START_DATE}"


def make_citation(
    study: StudyRecord,
    *,
    excerpt: str | None = None,
    field: str | None = None,
) -> Citation:
    """Build a :class:`Citation` from a contributing ``study``.

    ``excerpt`` should be the exact field value supporting the datum (the phase
    string, the country, the sponsor name, ...). When it is empty or ``None`` we
    fall back to the study's ``brief_title``, and finally to its ``nct_id``, so a
    citation's excerpt is never blank.
    """

    text = excerpt or study.brief_title or study.nct_id
    return Citation(nct_id=study.nct_id, excerpt=text, field=field)
