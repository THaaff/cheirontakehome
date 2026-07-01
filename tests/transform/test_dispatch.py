"""dispatch: each fixture plan routes to the correct output type."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.contracts import AnalysisPlan, GraphData, StudyRecord, TidyDataset
from app.transform import dispatch

_STUDY_OPS = [
    "time_trend",
    "categorical_distribution",
    "geographic_distribution",
    "numeric_distribution",
    "numeric_relationship",
]


@pytest.mark.parametrize("name", _STUDY_OPS)
def test_dispatch_study_ops_return_tidy(
    name: str,
    studies: list[StudyRecord],
    load_plan: Callable[[str], AnalysisPlan],
) -> None:
    result = dispatch(load_plan(name), studies)
    assert isinstance(result, TidyDataset)


def test_dispatch_comparison_returns_tidy(
    studies: list[StudyRecord],
    load_plan: Callable[[str], AnalysisPlan],
) -> None:
    payload = [("melanoma", studies), ("lung cancer", studies)]
    result = dispatch(load_plan("comparison"), payload)
    assert isinstance(result, TidyDataset)
    assert "series" in result.dimension_names


def test_dispatch_network_returns_graph(
    studies: list[StudyRecord],
    load_plan: Callable[[str], AnalysisPlan],
) -> None:
    result = dispatch(load_plan("cooccurrence_network"), studies)
    assert isinstance(result, GraphData)
