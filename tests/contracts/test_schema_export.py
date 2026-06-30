"""Schema export — model_json_schema() succeeds and files land in docs/schemas (Section K)."""

from __future__ import annotations

import json

import pytest
from conftest import DOCS_SCHEMAS_DIR
from export_schemas import EXPORTED_MODELS, export_schemas

from app.contracts import ErrorResponse, VisualizationRequest, VisualizationResponse


@pytest.mark.parametrize("model", [VisualizationRequest, VisualizationResponse, ErrorResponse])
def test_model_json_schema_succeeds(model: type) -> None:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    assert isinstance(schema, dict)
    assert schema.get("title") == model.__name__
    # A non-trivial object schema with properties.
    assert schema.get("type") == "object"
    assert "properties" in schema


def test_exported_models_cover_the_three_top_level_types() -> None:
    names = {m.__name__ for m in EXPORTED_MODELS}
    assert names == {"VisualizationRequest", "VisualizationResponse", "ErrorResponse"}


def test_export_writes_valid_schema_files() -> None:
    paths = export_schemas(DOCS_SCHEMAS_DIR)
    assert len(paths) == 3
    for path in paths:
        assert path.exists()
        assert path.parent == DOCS_SCHEMAS_DIR
        # Each file is valid JSON describing an object.
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["type"] == "object"
