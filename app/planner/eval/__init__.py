"""Planner eval: a labeled query set plus a replay/live scoring harness.

The planner is built as a classifier/extractor, so it is judged like one. This
package holds ~15 labeled queries spanning all seven operations and a harness
that scores operation accuracy and key-field extraction. Real model outputs are
recorded once into ``recorded/`` so the eval (and CI) run deterministically with
no API key; ``--live`` re-queries and ``--record`` refreshes the fixtures.
"""

from __future__ import annotations
