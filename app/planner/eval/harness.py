"""Scoring harness for the planner eval, in replay (default) or live mode.

Replay loads a recorded :class:`PlannerOutput` per case and runs the *real*
mapping into :class:`AnalysisPlan` (so the contract validators run), then scores
operation accuracy (exact) and key-field extraction (substring for entities,
equality for structural fields). Live re-queries the model and, with
``record=True``, writes each raw output to ``recorded/`` for future replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.contracts import AnalysisPlan, Settings
from app.planner.client import _map_to_plan, aclose, plan_with_output
from app.planner.errors import PlanningError
from app.planner.schema import PlannerOutput

from .queries import EVAL_CASES, EvalCase

RECORDED_DIR = Path(__file__).resolve().parent / "recorded"

# Operation-accuracy bar from the PRD (>= 13/15).
OPERATION_ACCURACY_THRESHOLD = 13


@dataclass
class EvalResult:
    """The scored outcome for a single eval case."""

    case_id: str
    expected_operation: str
    actual_operation: str | None
    operation_ok: bool
    extraction_checks: list[tuple[str, bool]] = field(default_factory=list)
    error: str | None = None

    @property
    def extraction_ok(self) -> bool:
        return self.error is None and all(ok for _, ok in self.extraction_checks)


# ---------------------------------------------------------------------------
# Recording I/O
# ---------------------------------------------------------------------------


def recorded_path(case_id: str) -> Path:
    return RECORDED_DIR / f"{case_id}.json"


def recorded_ids() -> set[str]:
    if not RECORDED_DIR.is_dir():
        return set()
    return {p.stem for p in RECORDED_DIR.glob("*.json")}


def load_recorded(case_id: str) -> PlannerOutput:
    path = recorded_path(case_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"no recorded output for '{case_id}'. Run "
            "`uv run python -m app.planner.eval --live --record` to capture it."
        )
    return PlannerOutput.model_validate_json(path.read_text(encoding="utf-8"))


def save_recorded(case_id: str, output: PlannerOutput) -> None:
    RECORDED_DIR.mkdir(parents=True, exist_ok=True)
    recorded_path(case_id).write_text(output.model_dump_json(indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _check_substring(expected: str | None, actual: str | None) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    return expected.lower() in actual.lower()


def score_plan(case: EvalCase, plan: AnalysisPlan) -> EvalResult:
    """Score a mapped plan against a case's labels."""
    checks: list[tuple[str, bool]] = []

    if case.expected_drug is not None:
        checks.append(("drug", _check_substring(case.expected_drug, plan.entities.drug)))
    if case.expected_condition is not None:
        checks.append(
            ("condition", _check_substring(case.expected_condition, plan.entities.condition))
        )
    if case.expected_group_by is not None:
        checks.append(("group_by", plan.group_by is case.expected_group_by))
    if case.expects_series:
        checks.append(("series", plan.series is not None and len(plan.series.values) >= 2))
    if case.expects_network:
        checks.append(("network", plan.network is not None))
    if case.expected_numeric_x is not None:
        checks.append(("numeric_x", plan.numeric_x is case.expected_numeric_x))
    if case.expected_numeric_y is not None:
        checks.append(("numeric_y", plan.numeric_y is case.expected_numeric_y))
    if case.expected_start_year is not None:
        checks.append(("start_year", plan.filters.start_year == case.expected_start_year))

    return EvalResult(
        case_id=case.id,
        expected_operation=case.expected_operation.value,
        actual_operation=plan.operation.value,
        operation_ok=plan.operation is case.expected_operation,
        extraction_checks=checks,
    )


def _error_result(case: EvalCase, message: str) -> EvalResult:
    return EvalResult(
        case_id=case.id,
        expected_operation=case.expected_operation.value,
        actual_operation=None,
        operation_ok=False,
        error=message,
    )


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def run_replay(cases: list[EvalCase] | None = None) -> list[EvalResult]:
    """Score each case from its recorded output. No network, no API key."""
    results: list[EvalResult] = []
    for case in cases or EVAL_CASES:
        try:
            output = load_recorded(case.id)
            plan = _map_to_plan(output)
        except (FileNotFoundError, ValidationError) as exc:
            results.append(_error_result(case, f"{type(exc).__name__}: {exc}"))
            continue
        results.append(score_plan(case, plan))
    return results


async def run_live(
    settings: Settings,
    cases: list[EvalCase] | None = None,
    *,
    record: bool = False,
) -> list[EvalResult]:
    """Query the live model for each case; optionally record the raw output."""
    results: list[EvalResult] = []
    try:
        for case in cases or EVAL_CASES:
            try:
                output, plan = await plan_with_output(case.to_request(), settings)
            except PlanningError as exc:
                results.append(_error_result(case, f"PlanningError({exc.reason}): {exc}"))
                continue
            if record:
                save_recorded(case.id, output)
            results.append(score_plan(case, plan))
    finally:
        await aclose()
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def operation_accuracy(results: list[EvalResult]) -> int:
    return sum(1 for r in results if r.operation_ok)


def extraction_accuracy(results: list[EvalResult]) -> int:
    return sum(1 for r in results if r.extraction_ok)


def summarize(results: list[EvalResult]) -> str:
    lines: list[str] = []
    for r in results:
        if r.error is not None:
            lines.append(f"  ERROR  {r.case_id}: {r.error}")
            continue
        op_mark = "ok " if r.operation_ok else "MISS"
        failed = [name for name, ok in r.extraction_checks if not ok]
        extra = "" if not failed else f"  extraction misses: {', '.join(failed)}"
        detail = "" if r.operation_ok else f" (got {r.actual_operation})"
        lines.append(
            f"  [{op_mark}] {r.case_id}: expected {r.expected_operation}{detail}{extra}"
        )

    total = len(results)
    header = (
        f"Planner eval: {total} cases\n"
        f"  Operation accuracy:  {operation_accuracy(results)}/{total}\n"
        f"  Extraction accuracy: {extraction_accuracy(results)}/{total}"
    )
    return header + "\n" + "\n".join(lines)
