"""Eval CLI: ``python -m app.planner.eval [--live] [--record]``.

Default (no flags) runs in replay over the committed recordings — deterministic,
no network, no API key. ``--live`` re-queries the model (needs ``OPENAI_API_KEY``)
and ``--record`` writes each raw output back into ``recorded/`` for replay.
Exits non-zero if the eval cannot run or if operation accuracy is below the bar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.contracts import Settings

from .harness import (
    OPERATION_ACCURACY_THRESHOLD,
    EvalResult,
    operation_accuracy,
    run_live,
    run_replay,
    summarize,
)
from .queries import EVAL_CASES


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.planner.eval", description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="re-query the model live (needs OPENAI_API_KEY) instead of replaying recordings",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="with --live, write each raw output into recorded/ for deterministic replay",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    results: list[EvalResult]
    if args.live:
        settings = Settings()
        if not settings.openai_api_key:
            print(
                "error: --live needs OPENAI_API_KEY (set it in the environment or .env).",
                file=sys.stderr,
            )
            return 1
        results = asyncio.run(run_live(settings, EVAL_CASES, record=args.record))
    else:
        if args.record:
            print("error: --record only applies with --live.", file=sys.stderr)
            return 1
        results = run_replay(EVAL_CASES)

    print(summarize(results))

    if any(r.error is not None for r in results):
        print("\nFAILED: some cases errored (see above).", file=sys.stderr)
        return 1
    score = operation_accuracy(results)
    if score < OPERATION_ACCURACY_THRESHOLD:
        print(
            f"\nFAILED: operation accuracy {score}/{len(results)} "
            f"is below the bar of {OPERATION_ACCURACY_THRESHOLD}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
