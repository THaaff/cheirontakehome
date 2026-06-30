"""The eval runs in replay — offline, key-free, and above the accuracy bar."""

from __future__ import annotations

import pytest

from app.contracts import AnalysisPlan, CategoricalField, Operation, VizType
from app.planner.eval.harness import (
    OPERATION_ACCURACY_THRESHOLD,
    operation_accuracy,
    recorded_ids,
    run_replay,
    score_plan,
)
from app.planner.eval.queries import EVAL_CASES


def test_eval_set_spans_all_operations() -> None:
    covered = {c.expected_operation for c in EVAL_CASES}
    assert covered == set(Operation)
    assert len(EVAL_CASES) >= 15


def test_score_plan_detects_operation_and_extraction() -> None:
    """Harness scoring works without any recordings present."""
    case = next(c for c in EVAL_CASES if c.id == "comparison_sponsor_two_conditions")

    good = AnalysisPlan(
        operation=Operation.comparison,
        group_by=CategoricalField.lead_sponsor_class,
        series={"dimension": "condition", "values": ["melanoma", "lung cancer"]},  # type: ignore[arg-type]
        proposed_viz=VizType.grouped_bar_chart,
        interpretation="x",
    )
    result = score_plan(case, good)
    assert result.operation_ok and result.extraction_ok

    wrong = AnalysisPlan(
        operation=Operation.categorical_distribution,
        group_by=CategoricalField.phase,
        proposed_viz=VizType.bar_chart,
        interpretation="x",
    )
    bad = score_plan(case, wrong)
    assert not bad.operation_ok
    assert not bad.extraction_ok


def test_replay_runs_offline_and_meets_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_ids = {c.id for c in EVAL_CASES}
    missing = expected_ids - recorded_ids()
    if missing:
        pytest.skip(
            f"{len(missing)} recordings not captured yet; run "
            "`uv run python -m app.planner.eval --live --record`"
        )

    # Guard: replay must never construct an OpenAI client or hit the network.
    def _boom(settings: object) -> object:
        raise AssertionError("replay must not call the network")

    monkeypatch.setattr("app.planner.client._get_client", _boom)

    results = run_replay(EVAL_CASES)
    errored = [r.error for r in results if r.error]
    assert not errored, errored
    assert operation_accuracy(results) >= OPERATION_ACCURACY_THRESHOLD
