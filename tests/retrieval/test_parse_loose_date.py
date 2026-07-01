"""parse_loose_date: tolerant of the documented formats, fail-closed otherwise."""

from __future__ import annotations

from datetime import date

import pytest

from app.retrieval.parsing import parse_loose_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-01-15", date(2024, 1, 15)),
        ("2024-01", date(2024, 1, 1)),
        ("2024", date(2024, 1, 1)),
        ("January 2024", date(2024, 1, 1)),
        ("January 15, 2024", date(2024, 1, 15)),
        ("  2018-02-08  ", date(2018, 2, 8)),
    ],
)
def test_parses_documented_formats(raw: str, expected: date) -> None:
    assert parse_loose_date(raw) == expected


@pytest.mark.parametrize("raw", ["Fall 2018", "garbage", "", "   ", None])
def test_fails_closed_to_none(raw: str | None) -> None:
    assert parse_loose_date(raw) is None
