"""Pagination budget math and truncation reporting (over a fake transport)."""

from __future__ import annotations

from pathlib import Path

from _helpers import (
    FakeCTGov,
    drug_plan,
    execute,
    load_raw,
    single_page_with_more,
    split_into_pages,
)

from app.contracts import RequestOptions, Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=str(tmp_path))


def test_collects_all_pages_until_exhausted(tmp_path: Path) -> None:
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_pembrolizumab.json"), 25))
    result = execute(fake, drug_plan(), _settings(tmp_path), RequestOptions(max_studies=2000))

    assert result.studies_analyzed == 50
    assert result.total_matched == 2892
    assert result.data_timestamp == "2026-06-30T09:00:05"
    assert fake.studies_calls == 2  # two pages
    assert not any("Truncated" in w for w in result.warnings)


def test_truncates_at_max_studies_50(tmp_path: Path) -> None:
    """Acceptance: max_studies=50 against thousands of matches -> 50 + truncation."""
    fake = FakeCTGov(pages=single_page_with_more(load_raw("studies_pembrolizumab.json")))
    result = execute(fake, drug_plan(), _settings(tmp_path), RequestOptions(max_studies=50))

    assert result.studies_analyzed == 50
    assert result.total_matched == 2892
    assert any("Truncated" in w and "max_studies=50" in w for w in result.warnings)
    assert fake.studies_calls == 1  # budget hit on the first page


def test_truncates_mid_pagination(tmp_path: Path) -> None:
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_pembrolizumab.json"), 25))
    result = execute(fake, drug_plan(), _settings(tmp_path), RequestOptions(max_studies=25))

    assert result.studies_analyzed == 25
    assert any("Truncated" in w for w in result.warnings)
    assert fake.studies_calls == 1


def test_first_request_sets_counttotal_and_budgeted_page_size(tmp_path: Path) -> None:
    """countTotal only on the first call; pageSize = min(1000, remaining budget)."""
    fake = FakeCTGov(pages=split_into_pages(load_raw("studies_pembrolizumab.json"), 25))
    execute(fake, drug_plan(), _settings(tmp_path), RequestOptions(max_studies=40))

    first = fake.studies_requests[0]
    assert first["countTotal"] == "true"
    assert first["pageSize"] == "40"  # min(1000, 40 - 0)
    second = fake.studies_requests[1]
    assert "countTotal" not in second  # only the first request
    assert "pageToken" in second
    assert second["pageSize"] == "15"  # min(1000, 40 - 25)
