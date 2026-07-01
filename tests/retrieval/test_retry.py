"""Retry/backoff: 429 + 5xx retried, transport errors retried, 4xx not."""

from __future__ import annotations

import pytest
from _helpers import FakeCTGov, run

from app.contracts import Settings
from app.retrieval.client import BackoffPolicy, get_with_retries
from app.retrieval.errors import RetrievalError

_ZERO_BACKOFF = BackoffPolicy(base_delay=0.0, max_attempts=3)


def _get(fake: FakeCTGov):
    async def _go():
        async with fake.client() as client:
            return await get_with_retries(
                client, Settings(), "/studies", {}, backoff=_ZERO_BACKOFF
            )

    return run(_go())


def test_retries_5xx_then_succeeds() -> None:
    fake = FakeCTGov(pages=[{"totalCount": 5, "studies": []}], fail_times=2, fail_status=503)
    payload = _get(fake)
    assert payload["totalCount"] == 5
    assert fake.studies_calls == 3  # two failures + one success


def test_retries_429_then_succeeds() -> None:
    fake = FakeCTGov(pages=[{"totalCount": 7, "studies": []}], fail_times=1, fail_status=429)
    payload = _get(fake)
    assert payload["totalCount"] == 7
    assert fake.studies_calls == 2


def test_persistent_5xx_raises_retrieval_error() -> None:
    fake = FakeCTGov(pages=[{"studies": []}], fail_times=99, fail_status=503)
    with pytest.raises(RetrievalError, match="503"):
        _get(fake)
    assert fake.studies_calls == _ZERO_BACKOFF.max_attempts + 1


def test_non_429_4xx_is_not_retried() -> None:
    fake = FakeCTGov(pages=[{"studies": []}], fail_times=99, fail_status=400)
    with pytest.raises(RetrievalError, match="400"):
        _get(fake)
    assert fake.studies_calls == 1  # raised immediately, no retry


def test_transport_error_retried_then_raises() -> None:
    fake = FakeCTGov(error_on_any=True)
    with pytest.raises(RetrievalError):
        _get(fake)
    assert fake.calls == _ZERO_BACKOFF.max_attempts + 1
