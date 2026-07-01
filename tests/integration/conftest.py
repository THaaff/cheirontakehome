"""Shared fixtures for the integration suite.

The pipeline runs behind FastAPI's ``TestClient`` (sync, but it drives the async
endpoint and the app lifespan). ``make_client`` injects a known plan (bypassing
the LLM planner) and points the settings dependency at a replay cache, so every
test is deterministic, key-free, and network-free.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.contracts import AnalysisPlan, RequestMode, Settings


@pytest.fixture
def replay_settings(tmp_path: Path) -> Settings:
    """Replay-mode settings pointed at an isolated tmp cache dir, key-free."""
    return Settings(
        cache_dir=str(tmp_path / "cache"),
        default_mode=RequestMode.replay,
        openai_api_key=None,
    )


@pytest.fixture
def make_client(
    replay_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., TestClient]]:
    """Factory building a TestClient that injects ``plan`` and replay settings.

    Monkeypatches ``app.api.orchestrator.plan_query`` (the name the orchestrator
    actually calls) to return the given plan, and overrides ``get_settings`` so
    retrieval reads the seeded replay cache. The client is entered so the app
    lifespan runs (creating ``app.state.http``); it is closed on teardown.
    """
    import app.api.orchestrator as orchestrator
    from app.api.main import app, get_settings

    entered: list[TestClient] = []

    def _factory(plan: AnalysisPlan, *, settings: Settings | None = None) -> TestClient:
        active = settings if settings is not None else replay_settings

        async def _fake_plan_query(request: object, settings: object) -> AnalysisPlan:
            return plan

        monkeypatch.setattr(orchestrator, "plan_query", _fake_plan_query)
        app.dependency_overrides[get_settings] = lambda: active
        client = TestClient(app)
        client.__enter__()
        entered.append(client)
        return client

    yield _factory

    for client in entered:
        client.__exit__(None, None, None)
    app.dependency_overrides.clear()
