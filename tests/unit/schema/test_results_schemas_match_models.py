"""The committed JSON Schemas of the stored formats are what their models generate.

A generated artefact without a gate drifts. The pairing of a file with its
model is made here, not in ``hydromodpy.schema``, which may not import
``results``. Refresh the files with::

    python tests/unit/schema/test_results_schemas_match_models.py
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.results.checks import CHECKS_SCHEMA, Checks
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger
from hydromodpy.results.outcome import OUTCOME_SCHEMA, Outcome
from hydromodpy.results.plan_store import PLAN_SCHEMA, Plan
from hydromodpy.results.publication import PUBLICATION_SCHEMA, Publication
from hydromodpy.results.session.descriptor import SESSION_SCHEMA, SessionDescriptor
from hydromodpy.schema import results as shipped
from hydromodpy.schema.results import (
    SCHEMA_FILENAMES,
    read_schema,
    read_schema_text,
    render_schema,
    schema_filename,
    write_schemas,
)

MODELS: dict[str, type[BaseModel]] = {
    OUTCOME_SCHEMA: Outcome,
    SESSION_SCHEMA: SessionDescriptor,
    PLAN_SCHEMA: Plan,
    PUBLICATION_SCHEMA: Publication,
    LEDGER_SCHEMA: Ledger,
    CHECKS_SCHEMA: Checks,
}

SCHEMAS_DIR = Path(shipped.__file__).resolve().parent
REFRESH = "python tests/unit/schema/test_results_schemas_match_models.py"


def refresh() -> list[Path]:
    """Rewrite the committed files from the models."""
    return write_schemas(SCHEMAS_DIR, MODELS)


def test_the_six_shipped_files_are_the_six_models():
    assert tuple(schema_filename(schema_id) for schema_id in MODELS) == SCHEMA_FILENAMES


@pytest.mark.parametrize("schema_id", sorted(MODELS))
def test_the_committed_file_is_what_the_model_generates(schema_id: str) -> None:
    filename = schema_filename(schema_id)
    assert read_schema_text(filename) == render_schema(MODELS[schema_id]), (
        f"hydromodpy/schema/results/{filename} is stale. Run `{REFRESH}` to refresh."
    )


@pytest.mark.parametrize("schema_id", sorted(MODELS))
def test_a_committed_schema_forbids_unknown_members(schema_id: str) -> None:
    document = read_schema(schema_filename(schema_id))
    assert document["additionalProperties"] is False
    assert "properties" in document


def test_a_schema_id_maps_to_one_file_name():
    assert schema_filename("hydromodpy.outcome.v1") == "outcome.v1.json"
    with pytest.raises(ValueError, match="starts with"):
        schema_filename("outcome.v1")
    with pytest.raises(KeyError, match="not a shipped schema"):
        read_schema_text("manifest.v2.json")


def test_write_schemas_writes_one_file_per_model(tmp_path):
    written = write_schemas(tmp_path, MODELS)
    assert sorted(p.name for p in written) == sorted(SCHEMA_FILENAMES)
    assert (tmp_path / "checks.v1.json").read_text(encoding="utf-8") == render_schema(Checks)


if __name__ == "__main__":
    for path in refresh():
        print(path)
