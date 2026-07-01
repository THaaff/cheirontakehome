"""Raw CT.gov v2 study JSON -> normalized :class:`StudyRecord`.

This module centralizes all messy-data handling. Extraction is null-safe: every
list defaults to ``[]``, every scalar is nullable, and parsing never raises on a
missing or malformed field — absence becomes ``None``/``[]``. Enumerated values
mirror the API vocabulary, so they map straight onto the contract enums; an
unexpected value is coerced to a catch-all member where one exists, otherwise
dropped (list) or nulled (scalar), with a de-duplicated warning.

Field paths are confirmed against ``fixtures/raw/notes.md`` / ``study_full.json``.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from dateutil import parser as _date_parser

from app.contracts import (
    InterventionType,
    OverallStatus,
    Phase,
    SponsorClass,
    StudyRecord,
    StudyType,
)
from app.retrieval.warnings import WarningsCollector

# Fill an absent day/month with 1 (the year is always present in real inputs).
_DATE_DEFAULT = datetime(2000, 1, 1)


def parse_loose_date(s: str | None) -> date | None:
    """Tolerantly parse an unnormalized CT.gov date string.

    Handles at least ``2024-01-15``, ``2024-01``, ``2024``, ``January 2024`` and
    ``January 15, 2024`` (day/month default to 1 when absent). Returns ``None``
    on anything it cannot confidently parse — fail-closed, with no fuzzy
    matching, so garbage like ``"Fall 2018"`` becomes ``None`` rather than a
    plausible-but-wrong date. The caller keeps the original string in
    ``StudyRecord.start_date_raw``.
    """
    if s is None or not s.strip():
        return None
    try:
        return _date_parser.parse(s.strip(), default=_DATE_DEFAULT, fuzzy=False).date()
    except (ValueError, OverflowError, TypeError):
        return None


def dig(data: Any, *keys: str) -> Any:
    """Walk nested dicts by ``keys``; return ``None`` at any missing/None step."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def coerce_enum[EnumT: StrEnum](
    enum_cls: type[EnumT],
    raw: Any,
    *,
    fallback: EnumT | None,
    field: str,
    warnings: WarningsCollector,
) -> EnumT | None:
    """Map ``raw`` onto ``enum_cls``; coerce unknowns to ``fallback`` or ``None``.

    ``None`` input returns ``None`` silently (an absent field is not a warning).
    An unrecognized non-null value warns once and falls back where a catch-all
    member exists (e.g. ``OTHER``/``UNKNOWN``), else is dropped.
    """
    if raw is None:
        return None
    try:
        return enum_cls(raw)
    except ValueError:
        if fallback is not None:
            warnings.add(f"Unknown {field} value {raw!r} coerced to {fallback.value}.")
            return fallback
        warnings.add(f"Unknown {field} value {raw!r} ignored (no matching enum member).")
        return None


def _to_int(raw: Any) -> int | None:
    """Coerce an enrollment count to ``int``; never raise."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def _parse_study_inner(raw: dict[str, Any], warnings: WarningsCollector) -> StudyRecord | None:
    nct_id = dig(raw, "protocolSection", "identificationModule", "nctId")
    if not isinstance(nct_id, str) or not nct_id:
        warnings.add("Skipped a study record with no nctId.")
        return None

    phases: list[Phase] = []
    for raw_phase in dig(raw, "protocolSection", "designModule", "phases") or []:
        coerced = coerce_enum(Phase, raw_phase, fallback=None, field="phase", warnings=warnings)
        if coerced is not None:
            phases.append(coerced)

    intervention_types: list[InterventionType] = []
    intervention_names: list[str] = []
    for interv in dig(raw, "protocolSection", "armsInterventionsModule", "interventions") or []:
        if not isinstance(interv, dict):
            continue
        itype = coerce_enum(
            InterventionType,
            interv.get("type"),
            fallback=InterventionType.OTHER,
            field="intervention type",
            warnings=warnings,
        )
        if itype is not None:
            intervention_types.append(itype)
        name = interv.get("name")
        if isinstance(name, str) and name.strip():
            intervention_names.append(name)

    conditions = [
        c
        for c in (dig(raw, "protocolSection", "conditionsModule", "conditions") or [])
        if isinstance(c, str) and c.strip()
    ]

    raw_locations = dig(raw, "protocolSection", "contactsLocationsModule", "locations") or []
    country_iter = (loc.get("country") for loc in raw_locations if isinstance(loc, dict))
    countries = list(dict.fromkeys(c for c in country_iter if isinstance(c, str) and c.strip()))

    start_date_raw = dig(raw, "protocolSection", "statusModule", "startDateStruct", "date")
    completion_raw = dig(
        raw, "protocolSection", "statusModule", "primaryCompletionDateStruct", "date"
    )

    return StudyRecord(
        nct_id=nct_id,
        brief_title=dig(raw, "protocolSection", "identificationModule", "briefTitle"),
        phases=phases,
        overall_status=coerce_enum(
            OverallStatus,
            dig(raw, "protocolSection", "statusModule", "overallStatus"),
            fallback=OverallStatus.UNKNOWN,
            field="overall status",
            warnings=warnings,
        ),
        study_type=coerce_enum(
            StudyType,
            dig(raw, "protocolSection", "designModule", "studyType"),
            fallback=None,
            field="study type",
            warnings=warnings,
        ),
        lead_sponsor_name=dig(
            raw, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "name"
        ),
        lead_sponsor_class=coerce_enum(
            SponsorClass,
            dig(raw, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "class"),
            fallback=SponsorClass.UNKNOWN,
            field="sponsor class",
            warnings=warnings,
        ),
        start_date=parse_loose_date(start_date_raw),
        start_date_raw=start_date_raw if isinstance(start_date_raw, str) else None,
        completion_date=parse_loose_date(completion_raw),
        intervention_types=intervention_types,
        intervention_names=intervention_names,
        conditions=conditions,
        countries=countries,
        enrollment_count=_to_int(
            dig(raw, "protocolSection", "designModule", "enrollmentInfo", "count")
        ),
    )


def parse_study(raw: dict[str, Any], warnings: WarningsCollector) -> StudyRecord | None:
    """Parse one raw study dict into a :class:`StudyRecord`, or ``None`` to skip.

    Wrapped so an unexpected shape in a single record degrades to a skipped
    record plus a warning, never an exception that would kill the whole batch.
    """
    try:
        return _parse_study_inner(raw, warnings)
    except Exception as exc:  # noqa: BLE001 - defensive: one bad record must not abort the batch
        warnings.add(f"Skipped an unparseable study record ({type(exc).__name__}).")
        return None


def parse_pages(
    pages: list[dict[str, Any]], warnings: WarningsCollector
) -> tuple[list[StudyRecord], int | None]:
    """Parse every study across cached/fetched pages into ``StudyRecord``s.

    ``total_matched`` comes from the first page's ``totalCount`` (the API returns
    it only on the ``countTotal=true`` first request). Studies whose start date
    was present but unparseable are counted and surfaced as a single warning.
    """
    total_matched: int | None = None
    if pages:
        raw_total = pages[0].get("totalCount")
        total_matched = raw_total if isinstance(raw_total, int) else None

    records: list[StudyRecord] = []
    unparseable_dates = 0
    for page in pages:
        studies = page.get("studies") or []
        if not isinstance(studies, list):
            continue
        for raw_study in studies:
            if not isinstance(raw_study, dict):
                continue
            record = parse_study(raw_study, warnings)
            if record is None:
                continue
            if record.start_date_raw is not None and record.start_date is None:
                unparseable_dates += 1
            records.append(record)

    if unparseable_dates:
        warnings.add(
            f"{unparseable_dates} studies had unparseable start dates "
            f"(start_date is null; the raw string is preserved)."
        )
    return records, total_matched
