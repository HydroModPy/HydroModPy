"""The committed JSON Schemas of the stored formats are what their models generate.

A generated artifact without a gate drifts. The pairing of a file with its
model is made here, not in ``hydromodpy.schema``, which may not import
``results``. Refresh the files with::

    python tests/unit/schema/test_results_schemas_match_models.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.report import CALIBRATE_SCHEMA, CalibrationResult
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger
from hydromodpy.results.outcome import OUTCOME_SCHEMA, Outcome
from hydromodpy.results.plan_store import PLAN_SCHEMA, Plan
from hydromodpy.results.publication import PUBLICATION_SCHEMA, Publication
from hydromodpy.results.record.checks import CHECKS_SCHEMA, Checks
from hydromodpy.results.record.manifest import MANIFEST_DOCUMENT_SCHEMA, RunSeal
from hydromodpy.results.record.record import PROVENANCE_DOCUMENT_SCHEMA, RunProvenance
from hydromodpy.results.session.descriptor import SESSION_SCHEMA, SessionDescriptor
from hydromodpy.results.session.journal import TRIAL_SCHEMA, TrialLine
from hydromodpy.results.session.phase import PHASE_SCHEMA, PhaseDescriptor
from hydromodpy.schema import results as shipped
from hydromodpy.schema.results import read_schema, read_schema_text, render_schema, schema_filename

MODELS: dict[str, type[BaseModel]] = {
    OUTCOME_SCHEMA: Outcome,
    SESSION_SCHEMA: SessionDescriptor,
    PHASE_SCHEMA: PhaseDescriptor,
    TRIAL_SCHEMA: TrialLine,
    PLAN_SCHEMA: Plan,
    PUBLICATION_SCHEMA: Publication,
    LEDGER_SCHEMA: Ledger,
    CHECKS_SCHEMA: Checks,
    CALIBRATE_SCHEMA: CalibrationResult,
    MANIFEST_DOCUMENT_SCHEMA: RunSeal,
    PROVENANCE_DOCUMENT_SCHEMA: RunProvenance,
}

SCHEMAS_DIR = Path(shipped.__file__).resolve().parent
REFRESH = "python tests/unit/schema/test_results_schemas_match_models.py"


def refresh() -> list[Path]:
    """Rewrite the committed files from the models."""
    written = []
    for schema_id, model in MODELS.items():
        path = SCHEMAS_DIR / schema_filename(schema_id)
        path.write_text(render_schema(model), encoding="utf-8")
        written.append(path)
    return written


@pytest.mark.parametrize("schema_id", sorted(MODELS))
def test_the_committed_file_is_what_the_model_generates(schema_id: str) -> None:
    filename = schema_filename(schema_id)
    assert read_schema_text(filename) == render_schema(MODELS[schema_id]), (
        f"hydromodpy/schema/results/{filename} is stale. Run `{REFRESH}` to refresh."
    )


def _closed_objects(node: Any) -> list[Any]:
    """Return every object of a schema that does not say it takes additional properties."""
    if isinstance(node, list):
        return [found for item in node for found in _closed_objects(item)]
    if not isinstance(node, dict):
        return []
    own = [node] if "properties" in node and node.get("additionalProperties") is not True else []
    return own + [found for value in node.values() for found in _closed_objects(value)]


@pytest.mark.parametrize("schema_id", sorted(MODELS))
def test_a_committed_schema_allows_what_a_later_version_adds(schema_id: str) -> None:
    document = read_schema(schema_filename(schema_id))
    assert document["additionalProperties"] is True
    assert "properties" in document
    assert _closed_objects(document) == []


@pytest.mark.parametrize(
    ("filename", "field", "word"),
    [
        ("session.v4.json", "status", "partial"),
        ("phase.v2.json", "status", "aborted"),
        ("trial.v3.json", "status", "crashed"),
        ("outcome.v1.json", "written_by", "trap"),
        ("publication.v1.json", "kind", "project"),
    ],
)
def test_a_field_that_can_grow_is_a_string_with_its_words(
    filename: str, field: str, word: str
) -> None:
    member = read_schema(filename)["properties"][field]
    assert member["type"] == "string" and "enum" not in member
    assert word in member["x-hmp-vocabulary"]


def test_a_schema_id_maps_to_one_file_name():
    assert schema_filename("hydromodpy.outcome.v1") == "outcome.v1.json"
    with pytest.raises(ValueError, match="starts with"):
        schema_filename("outcome.v1")
    with pytest.raises(KeyError, match="not a shipped schema"):
        read_schema_text("manifest.v2.json")


if __name__ == "__main__":
    for path in refresh():
        print(path)
