"""Semantic output checks the type system cannot express.

The contract models guarantee a spec is *structurally* valid; they cannot
guarantee it is *meaningful* — that the encoding channels point at fields the
data actually contains, that the embedded Vega spec carries its inlined values,
that every graph edge connects real nodes, and that an empty result is a
deliberate (warned) outcome rather than a silent bug.

:func:`validate_output` returns soft warnings and raises
:class:`~app.api.errors.PipelineError` (tagged ``visualization``) on a hard
failure. Empty result sets are a normal outcome — allowed as long as an upstream
warning already explains them.
"""

from __future__ import annotations

from typing import Any, NoReturn

from pydantic import TypeAdapter, ValidationError

from app.contracts import (
    ChartVizSpec,
    Encoding,
    GraphData,
    GraphVizSpec,
    PipelineStage,
    TidyDataset,
    VizSpec,
)

# Built once: the discriminated-union adapter used as the final re-parse guard.
_VIZSPEC_ADAPTER: TypeAdapter[VizSpec] = TypeAdapter(VizSpec)


def _fail(error_type: str, message: str, details: dict[str, Any] | None = None) -> NoReturn:
    """Raise a visualization-stage :class:`PipelineError`.

    Imported lazily so the validation package never hard-depends on ``app.api``
    at import time (the orchestrator imports this module, not the reverse).
    """
    from app.api.errors import PipelineError

    raise PipelineError(
        stage=PipelineStage.visualization,
        error_type=error_type,
        message=message,
        details=details,
    )


def validate_output(viz_spec: VizSpec, data: TidyDataset | GraphData) -> list[str]:
    """Validate the final spec against its data. Return soft warnings, raise on hard.

    ``data`` is the :class:`TidyDataset` / :class:`GraphData` the transform stage
    produced; its ``warnings`` are the authoritative explanation for an empty
    result (a chart spec carries no warnings of its own).
    """
    # Hard: the spec must still parse as a VizSpec (final guard against a
    # hand-built or mutated spec that drifted from the contract).
    try:
        _VIZSPEC_ADAPTER.validate_python(viz_spec.model_dump())
    except ValidationError as exc:
        _fail("invalid_viz_spec", f"final spec failed VizSpec validation: {exc}")

    if isinstance(viz_spec, GraphVizSpec):
        return _validate_graph(viz_spec, data)
    if isinstance(viz_spec, ChartVizSpec):
        return _validate_chart(viz_spec, data)
    _fail("unknown_viz_kind", f"unknown visualization kind: {viz_spec!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------


def _validate_chart(spec: ChartVizSpec, data: TidyDataset | GraphData) -> list[str]:
    warnings: list[str] = []

    if not spec.data:
        # Empty is fine only if the transform explained it; otherwise a silent
        # blank chart is a bug. The embedded values array must still be present.
        _require_explained_emptiness(data)
        _check_vega_values(spec)
        return warnings

    # Hard: every encoding channel field must be a key present in the records.
    record_keys = _record_key_union(spec)
    missing = [
        (name, field)
        for name, field in _channel_fields(spec.encoding)
        if field not in record_keys
    ]
    if missing:
        _fail(
            "encoding_field_absent",
            "encoding references field(s) absent from the chart data: "
            + ", ".join(f"{name}={field!r}" for name, field in missing),
            details={"missing": dict(missing), "available": sorted(record_keys)},
        )

    # Hard: the embedded Vega spec must carry its inlined data.values array.
    _check_vega_values(spec)

    # Soft: citations are the provenance bonus — note gaps, never fail. A
    # zero-valued datum (e.g. a zero-filled period in a time trend) has nothing
    # to cite, so it is not a provenance gap.
    measure_field = spec.encoding.y.field if spec.encoding.y is not None else None
    if any(
        not datum.citations and not _is_zero_measure(datum, measure_field)
        for datum in spec.data
    ):
        warnings.append("some data points have no citations; provenance is incomplete.")
    return warnings


def _is_zero_measure(datum: Any, measure_field: str | None) -> bool:
    """True when the datum's measure value is zero (a legitimately empty bucket)."""
    if measure_field is None:
        return False
    return bool(datum.model_dump().get(measure_field) == 0)


def _record_key_union(spec: ChartVizSpec) -> set[str]:
    """Union of keys across all records (extras differ when dims are ragged)."""
    keys: set[str] = set()
    for datum in spec.data:
        keys |= set(datum.model_dump().keys())
    return keys


def _channel_fields(encoding: Encoding) -> list[tuple[str, str]]:
    """(channel_name, field) for every channel that is set."""
    channels = [
        ("x", encoding.x),
        ("y", encoding.y),
        ("color", encoding.color),
        ("column", encoding.column),
        ("size", encoding.size),
    ]
    return [(name, channel.field) for name, channel in channels if channel is not None]


def _vega_values(spec: ChartVizSpec) -> Any:
    data = spec.vega_spec.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("values")


def _check_vega_values(spec: ChartVizSpec) -> None:
    values = _vega_values(spec)
    if not isinstance(values, list):
        _fail(
            "vega_values_missing",
            "vega_spec['data']['values'] is missing or not a list",
        )


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------


def _validate_graph(spec: GraphVizSpec, data: TidyDataset | GraphData) -> list[str]:
    warnings: list[str] = []
    graph = spec.data

    if not graph.nodes:
        _require_explained_emptiness(data)
        return warnings

    # Hard: every edge endpoint must reference a node that exists.
    node_ids = {node.id for node in graph.nodes}
    dangling = [
        (edge.source, edge.target)
        for edge in graph.edges
        if edge.source not in node_ids or edge.target not in node_ids
    ]
    if dangling:
        _fail(
            "dangling_edge",
            f"{len(dangling)} edge(s) reference node ids absent from the graph",
            details={"dangling": dangling[:20], "node_count": len(node_ids)},
        )

    # Soft: provenance gaps on nodes/edges.
    if any(not node.citations for node in graph.nodes) or any(
        not edge.citations for edge in graph.edges
    ):
        warnings.append("some graph nodes/edges have no citations; provenance is incomplete.")
    return warnings


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def _require_explained_emptiness(data: TidyDataset | GraphData) -> None:
    """An empty result is a valid 200 only if an upstream warning explains it."""
    if not data.warnings:
        _fail(
            "silent_empty_result",
            "result set is empty but no upstream warning explains it; "
            "silent emptiness is a bug.",
        )
