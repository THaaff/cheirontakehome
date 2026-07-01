"""Async CT.gov v2 HTTP client: ``/version``, paged ``/studies``, retries.

Keeps paging sequential to be a polite API citizen, sets a descriptive
``User-Agent``, and retries 429/5xx (and transient transport errors) with
exponential backoff before giving up with a :class:`RetrievalError`. CT.gov
needs no API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anyio
import httpx

from app.contracts import Settings
from app.retrieval.errors import RetrievalError

USER_AGENT = "ctgov-viz/0.1 (retrieval; +https://clinicaltrials.gov)"
_TIMEOUT = 30.0
_MAX_PAGE_SIZE = 1000


@dataclass
class BackoffPolicy:
    """Exponential backoff for retryable failures.

    ``base_delay=0`` disables sleeping entirely, which tests use to exercise the
    retry path instantly.
    """

    base_delay: float = 0.5
    factor: float = 2.0
    max_attempts: int = 4

    async def sleep(self, attempt: int) -> None:
        if self.base_delay > 0:
            await anyio.sleep(self.base_delay * self.factor**attempt)


_DEFAULT_BACKOFF = BackoffPolicy()


async def get_with_retries(
    client: httpx.AsyncClient,
    settings: Settings,
    path: str,
    params: dict[str, str],
    *,
    backoff: BackoffPolicy = _DEFAULT_BACKOFF,
) -> dict[str, Any]:
    """GET ``path`` and return the JSON object, retrying 429/5xx with backoff.

    A non-429 4xx is a request-shape bug, not a transient fault, so it raises
    immediately without retrying.
    """
    url = settings.ctgov_base_url.rstrip("/") + path
    attempt = 0
    while True:
        try:
            resp = await client.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT
            )
        except httpx.TransportError as exc:
            if attempt >= backoff.max_attempts:
                raise RetrievalError(f"CT.gov request to {path} failed: {exc}") from exc
            await backoff.sleep(attempt)
            attempt += 1
            continue

        status = resp.status_code
        if status == httpx.codes.OK:
            payload: Any = resp.json()
            if not isinstance(payload, dict):
                raise RetrievalError(f"CT.gov {path} returned non-object JSON.")
            return payload
        if status == httpx.codes.TOO_MANY_REQUESTS or 500 <= status < 600:
            if attempt >= backoff.max_attempts:
                raise RetrievalError(
                    f"CT.gov {path} returned HTTP {status} after {attempt + 1} attempts."
                )
            await backoff.sleep(attempt)
            attempt += 1
            continue
        raise RetrievalError(f"CT.gov {path} returned HTTP {status}: {resp.text[:200]}")


async def fetch_data_timestamp(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    backoff: BackoffPolicy = _DEFAULT_BACKOFF,
) -> str | None:
    """Return CT.gov's ``dataTimestamp`` from ``/version`` (``None`` if absent)."""
    payload = await get_with_retries(client, settings, "/version", {}, backoff=backoff)
    value = payload.get("dataTimestamp")
    return value if isinstance(value, str) else None


async def fetch_all_pages(
    client: httpx.AsyncClient,
    settings: Settings,
    server_params: dict[str, str],
    max_studies: int,
    *,
    backoff: BackoffPolicy = _DEFAULT_BACKOFF,
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """Page ``/studies`` until exhaustion or the ``max_studies`` budget is hit.

    Sets ``countTotal=true`` on the first request only and captures ``totalCount``.
    Returns ``(raw_pages, total_count, truncated)`` where ``truncated`` is true
    when the budget stopped paging while more results remained.
    """
    pages: list[dict[str, Any]] = []
    total: int | None = None
    token: str | None = None
    fetched = 0
    truncated = False

    while True:
        remaining = max_studies - fetched
        if remaining <= 0:
            truncated = token is not None
            break

        params = dict(server_params)
        params["pageSize"] = str(min(_MAX_PAGE_SIZE, remaining))
        if token is None:
            params["countTotal"] = "true"
        else:
            params["pageToken"] = token

        page = await get_with_retries(client, settings, "/studies", params, backoff=backoff)
        pages.append(page)

        if total is None:
            raw_total = page.get("totalCount")
            total = raw_total if isinstance(raw_total, int) else None

        studies = page.get("studies")
        fetched += len(studies) if isinstance(studies, list) else 0

        next_token = page.get("nextPageToken")
        token = next_token if isinstance(next_token, str) and next_token else None
        if token is None:
            break
        if fetched >= max_studies:
            truncated = True
            break

    return pages, total, truncated
