"""Retrieval stage: ``AnalysisPlan`` -> CT.gov ``/studies`` -> ``RetrievalResult``.

This is the only component that touches the external API. :func:`retrieve` builds
the server-side query, pages through results within the ``max_studies`` budget,
caches the raw pages (so re-parsing picks up parser fixes), parses each study into
a null-safe :class:`~app.contracts.data.StudyRecord`, applies the client-side
filters, and returns a :class:`~app.contracts.data.RetrievalResult` whose scalar
fields flow straight into the response ``Meta``.

Modes: ``live`` reads through / writes through the cache and hits the network;
``replay`` reads only from the cache and never touches the network;
``force_refresh`` bypasses the cache read and overwrites it.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.contracts import (
    AnalysisPlan,
    RequestMode,
    RequestOptions,
    RetrievalResult,
    Settings,
)
from app.retrieval import cache
from app.retrieval.client import fetch_all_pages, fetch_data_timestamp
from app.retrieval.errors import RetrievalError
from app.retrieval.parsing import parse_pages
from app.retrieval.query_builder import (
    apply_client_filters,
    build_server_params,
    residual_client_filters,
)
from app.retrieval.warnings import WarningsCollector

__all__ = ["retrieve"]

# Placeholder timestamp for the (rare) case where /version omits dataTimestamp,
# so live mode still produces a valid cache filename.
_UNKNOWN_TIMESTAMP = "unknown"


async def retrieve(
    plan: AnalysisPlan,
    settings: Settings,
    options: RequestOptions,
    *,
    client: httpx.AsyncClient | None = None,
) -> RetrievalResult:
    """Retrieve and normalize studies for ``plan`` into a :class:`RetrievalResult`.

    Inject ``client`` for testing (it is left open for the caller to close); when
    omitted, an :class:`httpx.AsyncClient` is created and closed internally.
    """
    warnings = WarningsCollector()
    server_params = build_server_params(plan)
    key = cache.cache_key_params(server_params, options.max_studies)

    if options.mode is RequestMode.replay:
        envelope = cache.read_latest(settings.cache_dir, key)
        if envelope is None:
            raise RetrievalError(
                f"replay mode: no cached pages for key {key!r} under "
                f"{settings.cache_dir}/{cache._STUDIES_SUBDIR}/{key}/ "
                f"(run once in live mode to populate the cache)."
            )
        data_timestamp: str | None = envelope.data_timestamp
        pages = envelope.pages
        truncated = envelope.truncated
    elif client is None:
        async with httpx.AsyncClient() as owned_client:
            data_timestamp, pages, truncated = await _live_fetch(
                owned_client, settings, options, server_params, key, warnings
            )
    else:
        data_timestamp, pages, truncated = await _live_fetch(
            client, settings, options, server_params, key, warnings
        )

    records, total_matched = parse_pages(pages, warnings)
    records = apply_client_filters(records, residual_client_filters(plan), warnings)

    if truncated:
        suffix = f" (total matched: {total_matched})." if total_matched is not None else "."
        warnings.add(
            f"Truncated at max_studies={options.max_studies}: more matching studies "
            f"exist than were fetched and analyzed{suffix}"
        )

    return RetrievalResult(
        studies=records,
        total_matched=total_matched,
        studies_analyzed=len(records),
        data_timestamp=data_timestamp,
        warnings=warnings.list(),
    )


async def _live_fetch(
    client: httpx.AsyncClient,
    settings: Settings,
    options: RequestOptions,
    server_params: dict[str, str],
    key: str,
    warnings: WarningsCollector,
) -> tuple[str | None, list[dict[str, Any]], bool]:
    """Resolve the data timestamp, then read-through or fetch+write the pages."""
    data_timestamp = await fetch_data_timestamp(client, settings)
    if data_timestamp is None:
        warnings.add(
            "CT.gov /version returned no dataTimestamp; using a placeholder for the cache key."
        )
    ts_for_key = data_timestamp or _UNKNOWN_TIMESTAMP

    if not options.force_refresh:
        cached = cache.read_exact(settings.cache_dir, key, ts_for_key)
        if cached is not None:
            return data_timestamp, cached.pages, cached.truncated

    pages, _total, truncated = await fetch_all_pages(
        client, settings, server_params, options.max_studies
    )
    cache.write(settings.cache_dir, key, ts_for_key, pages, truncated)
    return data_timestamp, pages, truncated
