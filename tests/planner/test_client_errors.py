"""Transport-level failures each become a clean PlanningError (no crash)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from openai import APIError, LengthFinishReasonError

from app.contracts import Settings, VisualizationRequest
from app.planner import PlanningError, plan_query

from .conftest import install_fake_client, make_resp


def _run(monkeypatch: pytest.MonkeyPatch, settings: Settings, result: object) -> PlanningError:
    install_fake_client(monkeypatch, [result])
    req = VisualizationRequest(query="trials for melanoma by phase")
    with pytest.raises(PlanningError) as excinfo:
        asyncio.run(plan_query(req, settings))
    return excinfo.value


def test_refusal_becomes_planning_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    err = _run(monkeypatch, settings, make_resp(refusal="I can't help with that."))
    assert err.reason == "refusal"
    assert err.details.get("refusal")


def test_length_cutoff_becomes_planning_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    err = _run(monkeypatch, settings, make_resp(incomplete_reason="max_output_tokens"))
    assert err.reason == "length"
    assert err.details.get("incomplete_reason") == "max_output_tokens"


def test_empty_parse_becomes_planning_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    err = _run(monkeypatch, settings, make_resp(parsed=None))
    assert err.reason == "empty"


def test_length_exception_becomes_planning_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    exc = LengthFinishReasonError(completion=SimpleNamespace(usage=None))  # type: ignore[arg-type]
    err = _run(monkeypatch, settings, exc)
    assert err.reason == "length"


def test_api_error_becomes_planning_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    exc = APIError("boom", request=None, body=None)  # type: ignore[arg-type]
    err = _run(monkeypatch, settings, exc)
    assert err.reason == "api_error"
