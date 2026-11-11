"""The JSON Schemas of the stored formats of ``results``, as package data.

One ``<name>.<version>.json`` per format a run, a session, a plan or a
publication writes: ``outcome.v1.json``, ``session.v4.json``, ``phase.v2.json``,
``trial.v3.json``, ``plan.v2.json``, ``publication.v1.json``, ``ledger.v1.json``,
``checks.v2.json``, ``manifest.v4.json``, ``provenance.v2.json``, and of what ``hmp calibrate --format json`` prints,
``calibrate.v1.json``. ``manifest.v3.json`` stays beside them, frozen: it is the
schema of the seal of the 2.0.0 floor, which this code reads and never writes.
They are
generated from the Pydantic models of ``hydromodpy.results`` and
``hydromodpy.calibration`` with ``model_json_schema()`` and committed here, so a reader outside Python can
validate a document without importing anything. A test refuses a committed
file the model no longer reproduces.

A schema allows additional properties, at every depth, although the model
refuses them when it writes: a later 2.x may add a key, and a reader ignores
it. A field that can grow is a string with its words in ``x-hmp-vocabulary``.

This module reads the committed files and renders a schema from a model it is
given; it imports no model. The pairing of a file with its model is made by the
test that refreshes the files: the layer matrix gives ``schema`` no edge towards
``results``.

``tests/unit/schema/test_results_schemas_match_models.py`` refuses a committed file that
its model no longer reproduces, and run as a script it writes the files again.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Final

from pydantic import BaseModel

SCHEMA_FILENAMES: Final[tuple[str, ...]] = (
    "outcome.v1.json",
    "session.v4.json",
    "phase.v2.json",
    "trial.v3.json",
    "plan.v2.json",
    "publication.v1.json",
    "ledger.v1.json",
    "checks.v2.json",
    "calibrate.v1.json",
    "manifest.v4.json",
    "provenance.v2.json",
)
"""The files this package ships, one per model, in the order the models pair with them."""

FROZEN_SCHEMA_FILENAMES: Final[tuple[str, ...]] = ("manifest.v3.json",)
"""Files this package ships that no model generates: the schema of the reading floor."""


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
    """Return *node* with ``additionalProperties: true`` written on every object.

    Written whatever pydantic says, because its versions differ on a stdlib dataclass.
    """
    if isinstance(node, list):
        return [_open_to_additions(item) for item in node]
    if not isinstance(node, dict):
        return node
    opened = {key: _open_to_additions(value) for key, value in node.items()}
    if "properties" in opened:
        opened["additionalProperties"] = True
    return opened


def read_schema_text(filename: str) -> str:
    """Return the committed text of one schema file."""
    if filename not in SCHEMA_FILENAMES and filename not in FROZEN_SCHEMA_FILENAMES:
        raise KeyError(
            f"{filename!r} is not a shipped schema; shipped: "
            f"{SCHEMA_FILENAMES + FROZEN_SCHEMA_FILENAMES}"
        )
    return files(__name__).joinpath(filename).read_text(encoding="utf-8")


def read_schema(filename: str) -> dict[str, Any]:
    """Return one committed schema, parsed."""
    return json.loads(read_schema_text(filename))


__all__ = (
    "FROZEN_SCHEMA_FILENAMES",
    "SCHEMA_FILENAMES",
    "read_schema",
    "read_schema_text",
    "render_schema",
    "schema_filename",
)
