"""Shared paths, loaders, and fixture pairings for the viz test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.contracts import AnalysisPlan, GraphData, TidyDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"
TIDY_DIR = FIXTURES_DIR / "tidy"
PLANS_DIR = FIXTURES_DIR / "plans"

# Each tidy/graph fixture paired with the plan whose operation drives its viz.
CHART_CASES: list[tuple[str, str]] = [
    ("bar.json", "categorical_distribution.json"),
    ("comparison.json", "comparison.json"),
    ("time_series.json", "time_trend.json"),
]
NETWORK_CASE: tuple[str, str] = ("network.json", "cooccurrence_network.json")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tidy(name: str) -> TidyDataset:
    return TidyDataset.model_validate(load_json(TIDY_DIR / name))


def load_graph(name: str) -> GraphData:
    return GraphData.model_validate(load_json(TIDY_DIR / name))


def load_plan(name: str) -> AnalysisPlan:
    return AnalysisPlan.model_validate(load_json(PLANS_DIR / name))


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR
