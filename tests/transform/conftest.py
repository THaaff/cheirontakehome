"""Fixtures for the transform test suite.

Helpers are exposed as pytest fixtures (not importable module functions) so the
suite never imports a bare ``conftest`` module — that keeps it from colliding
with the contracts suite's conftest during a full ``pytest`` run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.contracts import AnalysisPlan, StudyRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"

_STUDY_LIST = TypeAdapter(list[StudyRecord])


@pytest.fixture
def studies() -> list[StudyRecord]:
    """The clean 10-record fixture from contracts."""

    raw = (FIXTURES_DIR / "raw" / "study_records.json").read_text(encoding="utf-8")
    return _STUDY_LIST.validate_python(json.loads(raw))


@pytest.fixture
def load_plan() -> Callable[[str], AnalysisPlan]:
    """Return a loader for the example ``AnalysisPlan`` fixtures by stem name."""

    def _load(name: str) -> AnalysisPlan:
        text = (FIXTURES_DIR / "plans" / f"{name}.json").read_text(encoding="utf-8")
        return AnalysisPlan.model_validate_json(text)

    return _load
