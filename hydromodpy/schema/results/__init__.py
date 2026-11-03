"""The JSON Schemas of the stored formats of ``results``, as package data.

One ``<name>.<version>.json`` per format a run, a session, a plan or a
publication writes: ``outcome.v1.json``, ``session.v4.json``, ``phase.v2.json``,
``trial.v2.json``, ``plan.v1.json``, ``publication.v1.json``, ``ledger.v1.json``,
``checks.v2.json``, ``manifest.v3.json``, ``provenance.v2.json``, and of what ``hmp calibrate --format json`` prints,
``calibrate.v1.json``. They are
generated from the Pydantic models of ``hydromodpy.results`` and
``hydromodpy.calibration`` with ``model_json_schema()`` and committed here, so a reader outside Python can
validate a document without importing anything. A test refuses a committed
file the model no longer reproduces.

A schema allows additional properties, at every depth, although the model
refuses them when it writes: a later 2.x may add a key, and a reader ignores
it. A field that can grow is a string with its words in ``x-hmp-vocabulary``.

This module reads and writes files; it imports no model. The pairing of a
file with its model is made by the caller, which passes the models in: the
layer matrix gives ``schema`` no edge towards ``results``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

SCHEMA_FILENAMES: Final[tuple[str, ...]] = (
    "outcome.v1.json",
    "session.v4.json",
    "phase.v2.json",
    "trial.v2.json",
    "plan.v1.json",
    "publication.v1.json",
    "ledger.v1.json",
    "checks.v2.json",
    "calibrate.v1.json",
    "manifest.v3.json",
    "provenance.v2.json",
)
"""The files this package ships."""


def schema_filename(schema_id: str) -> str:
    """Return the file name of a schema id: ``hydromodpy.outcome.v1`` gives ``outcome.v1.json``."""
    prefix = "hydromodpy."
    if not schema_id.startswith(prefix):
        raise ValueError(f"a results schema id starts with {prefix!r}, not {schema_id!r}")
    return f"{schema_id[len(prefix) :]}.json"


def render_schema(model: type[BaseModel]) -> str:
    """Return the JSON Schema of *model* as the exact text the file carries."""
    document = _open_to_additions(model.model_json_schema())
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _open_to_additions(node: Any) -> Any:
    """Return *node* with every ``additionalProperties: false`` made ``true``."""
    if isinstance(node, list):
        return [_open_to_additions(item) for item in node]
    if not isinstance(node, dict):
        return node
    opened = {key: _open_to_additions(value) for key, value in node.items()}
    if opened.get("additionalProperties") is False:
        opened["additionalProperties"] = True
    return opened


def write_schemas(target_dir: str | Path, models: Mapping[str, type[BaseModel]]) -> list[Path]:
    """Write one file per ``{schema_id: model}`` under *target_dir* and return the paths."""
    directory = Path(target_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for schema_id, model in models.items():
        path = directory / schema_filename(schema_id)
        path.write_text(render_schema(model), encoding="utf-8")
        written.append(path)
    return written


def read_schema_text(filename: str) -> str:
    """Return the committed text of one schema file."""
    if filename not in SCHEMA_FILENAMES:
        raise KeyError(f"{filename!r} is not a shipped schema; shipped: {SCHEMA_FILENAMES}")
    return files(__name__).joinpath(filename).read_text(encoding="utf-8")


def read_schema(filename: str) -> dict[str, Any]:
    """Return one committed schema, parsed."""
    return json.loads(read_schema_text(filename))


__all__ = [
    "SCHEMA_FILENAMES",
    "read_schema",
    "read_schema_text",
    "render_schema",
    "schema_filename",
    "write_schemas",
]
