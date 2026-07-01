"""Histogram (P1) and scatter (P2) builders over inline datasets."""

from __future__ import annotations

from conftest import load_plan
from pydantic import TypeAdapter

from app.contracts import (
    ChartVizSpec,
    Citation,
    DataPoint,
    TidyDataset,
    VizSpec,
    VizType,
)
from app.viz import build_viz

_VIZ_ADAPTER = TypeAdapter(VizSpec)


def test_histogram_over_precomputed_bins() -> None:
    bins = ["0-99", "100-499", "500-999", "1000+"]
    points = [
        DataPoint(
            dims={"enrollment_bin": label},
            measure="trial_count",
            value=float(5 * (i + 1)),
            citations=[
                Citation(nct_id=f"NCT0001000{i}", excerpt=label, field="enrollmentInfo.count")
            ],
        )
        for i, label in enumerate(bins)
    ]
    tidy = TidyDataset(
        points=points, dimension_names=["enrollment_bin"], measure_name="trial_count"
    )

    spec = build_viz(tidy, load_plan("numeric_distribution.json"))
    assert isinstance(spec, ChartVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.type is VizType.histogram
    assert spec.encoding.x.field == "enrollment_bin"
    assert spec.vega_spec["mark"] == "bar"
    assert spec.vega_spec["data"]["values"]
    # Bin order is preserved as emitted by the transform layer.
    assert spec.encoding.x.sort == bins


def test_scatter_plot_one_point_per_study() -> None:
    points = [
        DataPoint(
            dims={"enrollment_count": float(n), "duration_days": float(n * 3)},
            measure="trial_count",
            value=1.0,
            citations=[
                Citation(nct_id=f"NCT0002000{i}", excerpt=str(n), field="enrollmentInfo.count")
            ],
        )
        for i, n in enumerate([50, 120, 300])
    ]
    tidy = TidyDataset(
        points=points,
        dimension_names=["enrollment_count", "duration_days"],
        measure_name="trial_count",
    )

    spec = build_viz(tidy, load_plan("numeric_relationship.json"))
    assert isinstance(spec, ChartVizSpec)
    _VIZ_ADAPTER.validate_python(spec.model_dump())
    assert spec.type is VizType.scatter_plot
    assert spec.encoding.x.field == "enrollment_count"
    assert spec.encoding.y.field == "duration_days"
    assert spec.vega_spec["mark"] == "point"
