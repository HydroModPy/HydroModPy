"""Export the JSON Schema of ``HydroModPyConfig`` published with the documentation.

``docs/source/_static/hydromodpy-schema.json`` is the schema an editor or a
frontend reads to check a configuration file.
``tests/unit/docs/test_docs_config_consistency.py`` keeps the committed copy
equal to this export.

Usage::

    python -m tools.docs.schema_export
"""

from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.config.schema_export import editor_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_OUTPUT = REPO_ROOT / "docs" / "source" / "_static" / "hydromodpy-schema.json"


def export_schema(output_path: Path | None = None) -> Path:
    """Write the editor JSON Schema 2020-12 of ``HydroModPyConfig`` and return its path."""
    target = output_path or SCHEMA_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(editor_schema(), indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(export_schema())
