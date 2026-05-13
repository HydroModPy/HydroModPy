"""Conformance tests for the RO-Crate v1.1 exporter.

Validation strategy:

1. Try the optional ``rocrate_validator`` package when installed (the
   official ResearchObject reference validator). This is rarely available
   on dev machines, so the suite degrades to:
2. JSON Schema validation of the JSON-LD payload against a minimal
   RO-Crate v1.1 schema (covers ``@context`` / ``conformsTo`` / required
   nodes).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export import build_context, build_ro_crate, write_ro_crate
from hydromodpy.results.export.rocrate import (
    RO_CRATE_CONFORMS,
    RO_CRATE_METADATA_FILENAME,
)
from tests.integration.exports.conftest import populate_simulation

# Minimal RO-Crate JSON Schema (fallback). Reference:
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


def _has_rocrate_validator() -> bool:
    try:
        import rocrate_validator  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def test_rocrate_payload_has_required_top_level_keys(fair_catalog):
    sid = populate_simulation(fair_catalog)
    payload = build_ro_crate(build_context(fair_catalog, sid))
    assert payload["@context"]
    assert isinstance(payload["@graph"], list)
    descriptors = [n for n in payload["@graph"] if n.get("@id") == RO_CRATE_METADATA_FILENAME]
    assert len(descriptors) == 1
    assert descriptors[0]["conformsTo"]["@id"] == RO_CRATE_CONFORMS


def test_rocrate_dataset_node_present(fair_catalog):
    sid = populate_simulation(fair_catalog)
    payload = build_ro_crate(build_context(fair_catalog, sid))
    datasets = [n for n in payload["@graph"] if n.get("@id") == "./"]
    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset["@type"] == "Dataset"
    assert dataset["identifier"] == sid
    assert "hasPart" in dataset
    assert dataset["wasGeneratedBy"] == {"@id": "#action/simulation"}


def test_rocrate_carries_assets(fair_catalog):
    sid = populate_simulation(fair_catalog)
    payload = build_ro_crate(build_context(fair_catalog, sid))
    file_nodes = [n for n in payload["@graph"] if n.get("@type") == "File"]
    assert file_nodes, "expected at least one File node in the crate"
    keys = {n.get("@id") for n in file_nodes}
    # Zarr archive should always be referenced.
    assert any(k.endswith(".zarr.zip") for k in keys)


def test_rocrate_carries_prov_action(fair_catalog):
    sid = populate_simulation(fair_catalog)
    payload = build_ro_crate(build_context(fair_catalog, sid))
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


def test_rocrate_json_schema_fallback(fair_catalog):
    sid = populate_simulation(fair_catalog)
    payload = build_ro_crate(build_context(fair_catalog, sid))
    pytest.importorskip("jsonschema")
    import jsonschema

    jsonschema.validate(instance=payload, schema=_ROCRATE_SCHEMA)


@pytest.mark.skipif(
    not _has_rocrate_validator(),
    reason="rocrate_validator not installed",
)
def test_rocrate_external_validator(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    target = tmp_path / "crate"
    target.mkdir()
    write_ro_crate(fair_catalog, sid, target)
    from rocrate_validator import services  # type: ignore[import-not-found]

    settings = services.ValidationSettings(rocrate_uri=str(target))
    report = services.validate(settings)
    assert not report.has_issues(), report


def test_rocrate_written_file_is_utf8_json(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    out = write_ro_crate(fair_catalog, sid, tmp_path / "rc")
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["@graph"]
