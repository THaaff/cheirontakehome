"""Fixture validity — every fixture loads and validates against its model (Section K).

Parametrized over the fixture directories so a new fixture file is covered the
moment it is dropped in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FIXTURES_DIR, load_json
from pydantic import BaseModel, TypeAdapter

from app.contracts import (
    AnalysisPlan,
    GraphData,
    TidyDataset,
    VisualizationRequest,
    VisualizationResponse,
)

# Each directory's files validate against one model. The tidy directory mixes
# TidyDataset and GraphData, so it is keyed by filename.
DIR_MODEL: dict[str, type[BaseModel]] = {
    "requests": VisualizationRequest,
    "plans": AnalysisPlan,
    "responses": VisualizationResponse,
}

TIDY_MODEL_BY_NAME: dict[str, type[BaseModel]] = {
    "bar.json": TidyDataset,
    "time_series.json": TidyDataset,
    "comparison.json": TidyDataset,
    "network.json": GraphData,
}


def _files(subdir: str) -> list[Path]:
    return sorted((FIXTURES_DIR / subdir).glob("*.json"))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.mark.parametrize(("subdir", "model"), list(DIR_MODEL.items()))
def test_directory_has_fixtures(subdir: str, model: type[BaseModel]) -> None:
    assert _files(subdir), f"no fixtures found in fixtures/{subdir}"


@pytest.mark.parametrize(
    "path",
    [p for d in DIR_MODEL for p in _files(d)],
    ids=lambda p: _id(p),
)
def test_simple_directory_fixtures_validate(path: Path) -> None:
    model = DIR_MODEL[path.parent.name]
    TypeAdapter(model).validate_python(load_json(path))


@pytest.mark.parametrize(
    "path",
    _files("tidy"),
    ids=lambda p: _id(p),
)
def test_tidy_fixtures_validate(path: Path) -> None:
    model = TIDY_MODEL_BY_NAME.get(path.name)
    assert model is not None, f"no model mapping for tidy fixture {path.name}"
    TypeAdapter(model).validate_python(load_json(path))


def test_all_seven_operations_have_a_plan_fixture() -> None:
    from app.contracts import Operation

    names = {p.stem for p in _files("plans")}
    expected = {op.value for op in Operation}
    assert names == expected, f"missing/extra plan fixtures: {expected ^ names}"


def test_stub_response_fixture_is_the_bar_chart() -> None:
    # The API skeleton serves this exact file; keep it present and valid.
    path = FIXTURES_DIR / "responses" / "bar_chart_phases.json"
    assert path.exists()
    VisualizationResponse.model_validate(load_json(path))
