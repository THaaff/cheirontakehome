"""Cache behavior: live read/write-through, force_refresh, replay (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _helpers import FakeCTGov, drug_plan, execute, load_raw, split_into_pages

from app.contracts import RequestMode, RequestOptions, Settings
from app.retrieval.errors import RetrievalError


def _pages() -> list[dict]:
    return split_into_pages(load_raw("studies_pembrolizumab.json"), 25)


def _cache_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "studies").glob("*/*.json"))


def test_live_writes_through_then_serves_from_cache(tmp_path: Path) -> None:
    settings = Settings(cache_dir=str(tmp_path))

    first = execute(FakeCTGov(pages=_pages()), drug_plan(), settings, RequestOptions())
    assert first.studies_analyzed == 50
    assert _cache_files(tmp_path)  # write-through happened

    second_fake = FakeCTGov(pages=_pages())
    second = execute(second_fake, drug_plan(), settings, RequestOptions())
    assert second.studies_analyzed == 50
    assert second_fake.studies_calls == 0  # served from cache
    assert second_fake.version_calls >= 1  # /version still consulted in live mode


def test_force_refresh_bypasses_cache_read(tmp_path: Path) -> None:
    settings = Settings(cache_dir=str(tmp_path))
    execute(FakeCTGov(pages=_pages()), drug_plan(), settings, RequestOptions())  # prime

    refresh_fake = FakeCTGov(pages=_pages())
    result = execute(
        refresh_fake, drug_plan(), settings, RequestOptions(force_refresh=True)
    )
    assert result.studies_analyzed == 50
    assert refresh_fake.studies_calls == 2  # re-fetched despite a warm cache


def test_replay_reads_cache_with_network_disabled(tmp_path: Path) -> None:
    """Acceptance: replay returns the cached result with the network disabled."""
    settings = Settings(cache_dir=str(tmp_path))
    primed = execute(FakeCTGov(pages=_pages()), drug_plan(), settings, RequestOptions())

    offline = FakeCTGov(error_on_any=True)
    replayed = execute(
        offline, drug_plan(), settings, RequestOptions(mode=RequestMode.replay)
    )
    assert replayed.studies_analyzed == primed.studies_analyzed
    assert replayed.total_matched == primed.total_matched
    assert replayed.data_timestamp == primed.data_timestamp
    assert offline.version_calls == 0
    assert offline.studies_calls == 0


def test_replay_missing_key_raises_clear_error(tmp_path: Path) -> None:
    """Acceptance: a missing cache key raises a clear error in replay mode."""
    settings = Settings(cache_dir=str(tmp_path))
    offline = FakeCTGov(error_on_any=True)
    with pytest.raises(RetrievalError, match="replay"):
        execute(offline, drug_plan(), settings, RequestOptions(mode=RequestMode.replay))
