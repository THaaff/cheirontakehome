#!/usr/bin/env python
"""Export JSON Schemas for the top-level wire types (PRD Section H).

Writes ``docs/schemas/{VisualizationRequest,VisualizationResponse,ErrorResponse}.json``
via Pydantic's ``model_json_schema()`` so a frontend engineer (or grader) can
understand the I/O without reading Python. Importable as a function so the
contracts test suite can call it directly.

Run::

    uv run python scripts/export_schemas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `python scripts/export_schemas.py` from anywhere: put the repo root
# (which contains the `app` package) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel  # noqa: E402

from app.contracts import ErrorResponse, VisualizationRequest, VisualizationResponse  # noqa: E402

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas"

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    VisualizationRequest,
    VisualizationResponse,
    ErrorResponse,
)


def export_schemas(out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    """Write one ``<ModelName>.json`` per top-level model. Returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in EXPORTED_MODELS:
        schema = model.model_json_schema()
        path = out_dir / f"{model.__name__}.json"
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in export_schemas():
        print(f"wrote {path}")
