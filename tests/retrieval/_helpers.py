"""Offline test helpers for the retrieval suite.

No live API is ever hit: HTTP is served by an :class:`httpx.MockTransport` that
replays canned multi-page responses built from ``fixtures/raw/*.json``. Async
entrypoints are driven with :func:`run` (``asyncio.run``) so test functions stay
synchronous and no pytest-asyncio plugin is required.

This module is named ``_helpers`` (not ``conftest``) on purpose, so importing it
never collides with another test package's ``conftest``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx

from app.contracts import AnalysisPlan, Entities, RequestOptions, Settings
from app.retrieval import retrieve

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "fixtures" / "raw"

DEFAULT_VERSION = {"apiVersion": "2.0.5", "dataTimestamp": "2026-06-30T09:00:05"}


def load_raw(name: str) -> dict[str, Any]:
    """Load a ``fixtures/raw/<name>`` JSON file."""
    return json.loads((RAW_DIR / name).read_text(encoding="utf-8"))


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Drive a coroutine to completion in a fresh event loop."""
    return asyncio.run(coro)


def split_into_pages(raw: dict[str, Any], page_size: int) -> list[dict[str, Any]]:
    """Split a real ``/studies`` capture into sequential pages.

    Page 0 carries ``totalCount`` (the API returns it only on the first request);
    every page but the last carries a ``nextPageToken`` cursor.
    """
    studies = raw["studies"]
    total = raw.get("totalCount")
    chunks = [studies[i : i + page_size] for i in range(0, len(studies), page_size)]
    pages: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        page: dict[str, Any] = {"studies": chunk}
        if index == 0 and total is not None:
            page["totalCount"] = total
        if index < len(chunks) - 1:
            page["nextPageToken"] = f"PAGE{index + 2}"
        pages.append(page)
    return pages


def single_page_with_more(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """One full page that still advertises a next cursor (simulates a large match)."""
    return [
        {
            "totalCount": raw.get("totalCount"),
            "studies": raw["studies"],
            "nextPageToken": "PAGE2",
        },
        {"studies": raw["studies"]},
    ]


def _select_page(pages: list[dict[str, Any]], token: str | None) -> dict[str, Any]:
    if token is None:
        return pages[0]
    for index, page in enumerate(pages):
        if page.get("nextPageToken") == token:
            return pages[index + 1]
    raise AssertionError(f"unexpected pageToken {token!r}")


class FakeCTGov:
    """A fake CT.gov v2 endpoint backed by :class:`httpx.MockTransport`.

    Routes ``/version`` and paged ``/studies``; can fail the first ``fail_times``
    ``/studies`` calls (for retry tests) or raise on every request (to prove
    replay needs no network). Tracks per-endpoint call counts.
    """

    def __init__(
        self,
        *,
        pages: list[dict[str, Any]] | None = None,
        version: dict[str, Any] | None = None,
        fail_times: int = 0,
        fail_status: int = 503,
        error_on_any: bool = False,
    ) -> None:
        self.pages = pages or []
        self.version = version if version is not None else dict(DEFAULT_VERSION)
        self.fail_times = fail_times
        self.fail_status = fail_status
        self.error_on_any = error_on_any
        self.calls = 0  # every request, counted before any short-circuit
        self.version_calls = 0
        self.studies_calls = 0
        self.studies_requests: list[dict[str, str]] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.error_on_any:
            raise httpx.ConnectError("network is disabled for this test")
        path = request.url.path
        if path.endswith("/version"):
            self.version_calls += 1
            return httpx.Response(200, json=self.version)
        if path.endswith("/studies"):
            self.studies_calls += 1
            self.studies_requests.append(dict(request.url.params))
            if self.studies_calls <= self.fail_times:
                return httpx.Response(self.fail_status, text="simulated upstream error")
            token = request.url.params.get("pageToken")
            return httpx.Response(200, json=_select_page(self.pages, token))
        return httpx.Response(404, text=f"unexpected path {path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport)


def drug_plan(drug: str = "pembrolizumab") -> AnalysisPlan:
    """A minimal valid time_trend plan for a drug query."""
    return AnalysisPlan(
        operation="time_trend",  # type: ignore[arg-type]
        entities=Entities(drug=drug),
        proposed_viz="time_series",  # type: ignore[arg-type]
        interpretation="test",
    )


def execute(
    fake: FakeCTGov,
    plan: AnalysisPlan,
    settings: Settings,
    options: RequestOptions,
):
    """Run retrieve() over the fake transport, closing the injected client."""

    async def _go():
        async with fake.client() as client:
            return await retrieve(plan, settings, options, client=client)

    return run(_go())
