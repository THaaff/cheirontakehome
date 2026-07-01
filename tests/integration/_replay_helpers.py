"""Offline helpers for the integration suite.

No live API or key is ever used: the pipeline runs in replay mode against a cache
this module seeds from ``fixtures/raw/*.json``. Named ``_helpers`` (not
``conftest``) so importing it never collides with another test package's conftest;
pytest adds this directory to ``sys.path`` because the package has no
``__init__.py`` (matching ``tests/retrieval``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.contracts import AnalysisPlan, StudyRecord
from app.retrieval import cache
from app.retrieval.query_builder import build_server_params

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "fixtures" / "raw"
PLANS_DIR = REPO_ROOT / "fixtures" / "plans"

# Matches fixtures/raw/notes.md and the retrieval suite's DEFAULT_VERSION, so
# replay assertions on meta.data_timestamp are deterministic.
DATA_TIMESTAMP = "2026-06-30T09:00:05"

_STUDY_LIST = TypeAdapter(list[StudyRecord])


def load_raw(name: str) -> dict[str, Any]:
    """Load a raw CT.gov capture from ``fixtures/raw/<name>``."""
    return json.loads((RAW_DIR / name).read_text(encoding="utf-8"))


def load_plan(name: str) -> AnalysisPlan:
    """Load an example ``AnalysisPlan`` fixture from ``fixtures/plans/<name>``."""
    return AnalysisPlan.model_validate_json((PLANS_DIR / name).read_text(encoding="utf-8"))


def load_studies(name: str = "study_records.json") -> list[StudyRecord]:
    """Load the clean parsed ``StudyRecord`` fixture (for validator unit tests)."""
    return _STUDY_LIST.validate_json((RAW_DIR / name).read_text(encoding="utf-8"))


def split_into_pages(raw: dict[str, Any], page_size: int = 1000) -> list[dict[str, Any]]:
    """Split a real ``/studies`` capture into the paged shape retrieval expects.

    Page 0 carries ``totalCount``; every page but the last carries a cursor. This
    mirrors ``tests/retrieval/_helpers.split_into_pages``.
    """
    studies = raw["studies"]
    total = raw.get("totalCount")
    chunks = [studies[i : i + page_size] for i in range(0, len(studies), page_size)] or [[]]
    pages: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        page: dict[str, Any] = {"studies": chunk}
        if index == 0 and total is not None:
            page["totalCount"] = total
        if index < len(chunks) - 1:
            page["nextPageToken"] = f"PAGE{index + 2}"
        pages.append(page)
    return pages


def empty_pages(total: int = 0) -> list[dict[str, Any]]:
    """A single well-formed page carrying zero studies (for the zero-study test)."""
    return [{"studies": [], "totalCount": total}]


# Must match RequestOptions.max_studies' default so a request with no explicit
# budget looks up the entry these helpers seed.
_DEFAULT_MAX_STUDIES = 25000


def seed_cache(
    cache_dir: str,
    plan: AnalysisPlan,
    raw_name: str | None = None,
    max_studies: int = _DEFAULT_MAX_STUDIES,
    *,
    pages: list[dict[str, Any]] | None = None,
) -> str:
    """Seed the replay cache for ``plan`` and return the cache key.

    Uses the exact key expression retrieval uses
    (``cache_key_params(build_server_params(plan), max_studies)``), so the seeded
    entry is always the one replay looks up. Provide either ``raw_name`` (loaded
    and split) or ``pages`` directly.
    """
    if pages is None:
        if raw_name is None:
            raise ValueError("seed_cache needs either raw_name or pages")
        pages = split_into_pages(load_raw(raw_name))
    key = cache.cache_key_params(build_server_params(plan), max_studies)
    cache.write(cache_dir, key, DATA_TIMESTAMP, pages, truncated=False)
    return key


def sub_plan_for_series(plan: AnalysisPlan, value: str) -> AnalysisPlan:
    """Reproduce the orchestrator's comparison sub-plan for one series value."""
    slot = plan.series.dimension.value if plan.series else ""
    entities = plan.entities.model_copy(update={slot: value})
    return plan.model_copy(update={"entities": entities})


def seed_comparison(
    cache_dir: str, plan: AnalysisPlan, raw_name: str, max_studies: int = _DEFAULT_MAX_STUDIES
) -> list[str]:
    """Seed one cache entry per comparison series value (all from one raw fixture).

    ``build_server_params`` reads only ``entities``/``filters`` (never ``series``
    or ``group_by``), so the per-series keys match the orchestrator's fan-out even
    though every series shares the same raw data.
    """
    assert plan.series is not None
    return [
        seed_cache(cache_dir, sub_plan_for_series(plan, value), raw_name, max_studies)
        for value in plan.series.values
    ]
