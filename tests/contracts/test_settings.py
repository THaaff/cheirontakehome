"""Settings never raises for a missing OPENAI_API_KEY (PRD Section G)."""

from __future__ import annotations

import importlib

from app.contracts import RequestMode, Settings


def test_settings_constructs_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # _env_file=None ignores any local .env so the test is hermetic.
    settings = Settings(_env_file=None)
    assert settings.openai_api_key is None
    assert settings.ctgov_base_url == "https://clinicaltrials.gov/api/v2"
    assert settings.cache_dir == ".cache"
    assert settings.planner_model == "gpt-4.1"
    assert settings.default_mode is RequestMode.live


def test_settings_reads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CTGOV_BASE_URL", "https://example.test/api/v2")
    monkeypatch.setenv("DEFAULT_MODE", "replay")
    settings = Settings(_env_file=None)
    assert settings.ctgov_base_url == "https://example.test/api/v2"
    assert settings.default_mode is RequestMode.replay


def test_importing_contracts_does_not_require_api_key(monkeypatch) -> None:
    # Importing the package must never raise even with no key in the environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import app.contracts as contracts

    importlib.reload(contracts)
    assert hasattr(contracts, "Settings")
