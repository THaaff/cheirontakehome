"""Application settings (PRD Section G).

Read from the environment (and an optional ``.env`` file) via pydantic-settings.

``OPENAI_API_KEY`` is intentionally optional so ``replay`` mode works without
it. **Constructing ``Settings`` never raises for a missing key**; the planner
worktree raises a clear error only when a live planner call is actually
attempted. The contracts package never instantiates ``Settings`` at import time.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import RequestMode


class Settings(BaseSettings):
    """Process configuration, sourced from env vars (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str | None = None
    ctgov_base_url: str = "https://clinicaltrials.gov/api/v2"
    cache_dir: str = ".cache"
    planner_model: str = "gpt-4.1"
    default_mode: RequestMode = RequestMode.live
    # Cap the per-datum citation list in the response so a full-corpus analysis
    # (thousands of studies) does not bloat the payload. Counts stay exact — only
    # the citation *sample* is trimmed; each datum's measure value is the true
    # total, so the client can show "showing N of <total>". 0 disables the cap.
    max_citations_per_datum: int = 100
