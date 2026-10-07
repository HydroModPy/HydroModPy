"""The JSON Schema published with the documentation.

``docs/source/_static/hydromodpy-schema.json`` is the schema an editor or a
frontend reads to check a configuration file. It is exported from
``HydroModPyConfig``; this module checks that it is a valid JSON Schema
2020-12 document and that the committed copy is the one the code exports.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema.validators import Draft202012Validator

from tools.docs.schema_export import export_schema

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"


def test_exported_schema_is_valid_json_schema_2020_12(tmp_path: Path) -> None:
    schema_path = export_schema(tmp_path / "hydromodpy-schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_committed_schema_matches_generated(tmp_path: Path) -> None:
    fresh = export_schema(tmp_path / "hydromodpy-schema.json")
    expected = json.loads(fresh.read_text(encoding="utf-8"))
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == expected, (
        "docs/source/_static/hydromodpy-schema.json is stale. "
        "Run `python -m tools.docs.schema_export` to refresh."
    )
