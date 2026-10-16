"""Conformance tests for the RO-Crate v1.1 exporter.

Validation strategy:

1. Parse the rendered crate with the ``rocrate`` reference package
   (``ROCrate(directory)``). Failure to load means the JSON-LD does not
   satisfy the RO-Crate structural contract.
2. Run a JSON Schema check as a complementary, schema-level assertion on
   ``@context`` / ``conformsTo`` / required nodes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export import build_ro_crate, write_ro_crate
from hydromodpy.results.export.rocrate import (
    RO_CRATE_CONFORMS,
    RO_CRATE_METADATA_FILENAME,
)
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests.integration.exports.conftest import SIM_ID

# Minimal RO-Crate JSON Schema. Reference:
# https://www.researchobject.org/ro-crate/1.1/structure.html
_ROCRATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["@context", "@graph"],
    "properties": {
        "@context": {"oneOf": [{"type": "string"}, {"type": "array"}]},
        "@graph": {
            "type": "array",
            "minItems": 2,
            "contains": {
                "type": "object",
                "properties": {
                    "@id": {"const": RO_CRATE_METADATA_FILENAME},
                    "@type": {"type": "string"},
                    "conformsTo": {
                        "type": "object",
                        "required": ["@id"],
                        "properties": {"@id": {"const": RO_CRATE_CONFORMS}},
                    },
                    "about": {"type": "object"},
                },
                "required": ["@id", "@type", "conformsTo", "about"],
            },
        },
    },
}


def test_rocrate_payload_has_required_top_level_keys(fair_context):
    sid = SIM_ID
    payload = build_ro_crate(fair_context)
    assert payload["@context"]
    assert isinstance(payload["@graph"], list)
    descriptors = [n for n in payload["@graph"] if n.get("@id") == RO_CRATE_METADATA_FILENAME]
    assert len(descriptors) == 1
    assert descriptors[0]["conformsTo"]["@id"] == RO_CRATE_CONFORMS


def test_rocrate_dataset_node_present(fair_context):
    sid = SIM_ID
    payload = build_ro_crate(fair_context)
    datasets = [n for n in payload["@graph"] if n.get("@id") == "./"]
    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset["@type"] == "Dataset"
    assert dataset["identifier"] == sid
    assert "hasPart" in dataset
    assert dataset["wasGeneratedBy"] == {"@id": "#action/simulation"}


def test_rocrate_carries_assets(fair_context):
    sid = SIM_ID
    payload = build_ro_crate(fair_context)
    file_nodes = [n for n in payload["@graph"] if n.get("@type") == "File"]
    assert file_nodes, "expected at least one File node in the crate"
    keys = {n.get("@id") for n in file_nodes}
    # The field store should always be referenced.
    assert any(k.endswith(FIELDS_STORE_NAME) for k in keys)


def test_rocrate_carries_prov_action(fair_context):
    sid = SIM_ID
    payload = build_ro_crate(fair_context)
    actions = [
        n
        for n in payload["@graph"]
        if (
            n.get("@id") == "#action/simulation"
            or (isinstance(n.get("@type"), list) and "CreateAction" in n["@type"])
            or n.get("@type") == "CreateAction"
        )
    ]
    assert actions, "expected the simulation CreateAction node in the crate"


def test_rocrate_json_schema_fallback(fair_context):
    sid = SIM_ID
    payload = build_ro_crate(fair_context)
    pytest.importorskip("jsonschema")
    import jsonschema

    jsonschema.validate(instance=payload, schema=_ROCRATE_SCHEMA)


def test_rocrate_parsed_by_reference_library(fair_context, tmp_path: Path):
    """The serialised crate loads cleanly via the ResearchObject ``rocrate`` lib."""
    pytest.importorskip("rocrate")
    from rocrate.rocrate import ROCrate

    sid = SIM_ID
    target = tmp_path / "crate"
    target.mkdir()
    write_ro_crate(fair_context, target)

    crate = ROCrate(target)
    # Root dataset is mandatory in any conformant RO-Crate.
    assert crate.root_dataset is not None
    assert str(crate.root_dataset.id) == "./"

    entities = list(crate.get_entities())
    ids = {str(e.id) for e in entities}
    # ``ro-crate-metadata.json`` descriptor and ``./`` root dataset must both load.
    assert RO_CRATE_METADATA_FILENAME in ids
    assert "./" in ids
    # CreateAction node from the PROV layer must be reachable.
    assert "#action/simulation" in ids


def test_rocrate_written_file_is_utf8_json(fair_context, tmp_path: Path):
    sid = SIM_ID
    out = write_ro_crate(fair_context, tmp_path / "rc")
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["@graph"]
