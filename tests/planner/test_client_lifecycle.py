"""_get_client caches one process-wide client; aclose() disposes it.

The rest of the suite monkeypatches ``_get_client`` wholesale, so this is the one
place the real factory (and its module-level cache) actually runs. Constructing
``AsyncOpenAI`` is offline; ``aclose`` closes it so no connection pool leaks.
"""

from __future__ import annotations

import asyncio

import app.planner.client as client_mod
from app.contracts import Settings


def test_get_client_caches_one_instance_and_aclose_disposes() -> None:
    settings = Settings(openai_api_key="sk-test")
    asyncio.run(client_mod.aclose())  # clean slate regardless of test ordering
    try:
        first = client_mod._get_client(settings)
        assert client_mod._get_client(settings) is first  # reused, not rebuilt
        assert client_mod._client is first
    finally:
        asyncio.run(client_mod.aclose())
    assert client_mod._client is None  # disposed -> next call rebuilds fresh
