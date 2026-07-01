"""Transform stage: clean ``StudyRecord``s + an ``AnalysisPlan`` -> tidy data / graph.

Pure and deterministic — no I/O, no network, no model. One aggregation function
per :class:`~app.contracts.Operation`, each returning a :class:`TidyDataset`
(or :class:`GraphData` for networks) with :class:`~app.contracts.Citation`
provenance attached to every datum, node, and edge. :func:`dispatch` routes a
plan to its function.
"""

from __future__ import annotations

from typing import cast

from app.contracts import AnalysisPlan, GraphData, Operation, StudyRecord, TidyDataset
from app.transform.aggregations import (
    aggregate_categorical,
    aggregate_comparison,
    aggregate_geographic,
    aggregate_numeric_distribution,
    aggregate_numeric_relationship,
    aggregate_time_trend,
)
from app.transform.network import build_cooccurrence_network
from app.transform.provenance import make_citation

__all__ = [
    "aggregate_time_trend",
    "aggregate_categorical",
    "aggregate_comparison",
    "aggregate_geographic",
    "aggregate_numeric_distribution",
    "aggregate_numeric_relationship",
    "build_cooccurrence_network",
    "make_citation",
    "cap_citations",
    "dispatch",
]


def cap_citations(
    data: TidyDataset | GraphData, limit: int | None
) -> TidyDataset | GraphData:
    """Trim every datum/node/edge citation list to ``limit`` entries.

    Counts are untouched — only the provenance *sample* is capped, so a
    full-corpus analysis stays exact while the serialized payload stays small.
    ``limit`` of ``None`` or ``<= 0`` is a no-op (uncapped). Order is preserved,
    so the retained citations are the first (deterministic) ones per datum.
    """

    if limit is None or limit <= 0:
        return data

    if isinstance(data, TidyDataset):
        points = [p.model_copy(update={"citations": p.citations[:limit]}) for p in data.points]
        return data.model_copy(update={"points": points})
    if isinstance(data, GraphData):
        nodes = [n.model_copy(update={"citations": n.citations[:limit]}) for n in data.nodes]
        edges = [e.model_copy(update={"citations": e.citations[:limit]}) for e in data.edges]
        return data.model_copy(update={"nodes": nodes, "edges": edges})
    return data  # pragma: no cover - dispatch only produces the two types above

# The orchestrator passes a labeled per-series record set for comparisons; every
# other operation receives the flat record list.
SeriesStudies = list[tuple[str, list[StudyRecord]]]
TransformPayload = list[StudyRecord] | SeriesStudies


def dispatch(plan: AnalysisPlan, payload: TransformPayload) -> TidyDataset | GraphData:
    """Route ``plan`` to its aggregation function over ``payload``.

    ``payload`` is ``list[tuple[series_value, records]]`` for a ``comparison``
    plan, and ``list[StudyRecord]`` for every other operation.
    """

    op = plan.operation

    if op is Operation.comparison:
        return aggregate_comparison(cast(SeriesStudies, payload), plan)

    studies = cast("list[StudyRecord]", payload)
    if op is Operation.time_trend:
        return aggregate_time_trend(studies, plan)
    if op is Operation.categorical_distribution:
        return aggregate_categorical(studies, plan)
    if op is Operation.geographic_distribution:
        return aggregate_geographic(studies, plan)
    if op is Operation.cooccurrence_network:
        return build_cooccurrence_network(studies, plan)
    if op is Operation.numeric_distribution:
        return aggregate_numeric_distribution(studies, plan)
    if op is Operation.numeric_relationship:
        return aggregate_numeric_relationship(studies, plan)

    raise AssertionError(f"unhandled operation: {op}")  # pragma: no cover
