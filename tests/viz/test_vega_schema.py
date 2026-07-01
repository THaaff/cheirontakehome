"""Vega-Lite embedded-spec validation.

Two layers:

* an always-on deterministic *structural* check (no extra dependency), and
* an optional full JSON-Schema validation that runs only when ``jsonschema`` and
  a cached Vega-Lite schema file are both available (P1 in the PRD). It skips
  cleanly otherwise — no network access, no new dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import CHART_CASES, load_plan, load_tidy

from app.contracts import ChartVizSpec
from app.viz import build_viz
from app.viz.vega_templates import VEGA_LITE_SCHEMA

# Drop a vega-lite v5 schema here to enable the optional full validation.
CACHED_SCHEMA = Path(__file__).resolve().parent / "vega-lite-v5-schema.json"


def _all_chart_specs() -> list[ChartVizSpec]:
    specs: list[ChartVizSpec] = []
    for tidy_name, plan_name in CHART_CASES:
        spec = build_viz(load_tidy(tidy_name), load_plan(plan_name))
        assert isinstance(spec, ChartVizSpec)
        specs.append(spec)
    return specs


def _validate_internal(vega_spec: dict[str, Any]) -> None:
    assert vega_spec.get("$schema") == VEGA_LITE_SCHEMA
    assert "mark" in vega_spec, "vega spec must declare a mark"
    assert "encoding" in vega_spec and isinstance(vega_spec["encoding"], dict)
    data = vega_spec.get("data")
    assert isinstance(data, dict) and isinstance(data.get("values"), list) and data["values"], (
        "vega spec must inline non-empty data.values"
    )
    # Every encoding channel references a field (or is a tooltip channel list).
    for name, channel in vega_spec["encoding"].items():
        if isinstance(channel, dict):
            assert "field" in channel, f"channel {name!r} missing 'field'"


def test_internal_structural_validation() -> None:
    for spec in _all_chart_specs():
        _validate_internal(spec.vega_spec)


def test_full_jsonschema_validation_when_available() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    if not CACHED_SCHEMA.exists():
        pytest.skip("no cached Vega-Lite schema present (optional P1 check)")
    import json

    schema = json.loads(CACHED_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    for spec in _all_chart_specs():
        errors = sorted(validator.iter_errors(spec.vega_spec), key=str)
        assert not errors, f"vega spec failed schema: {errors[:3]}"
