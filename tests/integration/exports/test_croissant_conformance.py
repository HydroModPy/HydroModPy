"""Conformance tests for the Croissant MLCommons 1.0 exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export import build_croissant_manifest, write_croissant
from hydromodpy.results.export.croissant import (
    CROISSANT_CONFORMS,
    validate_manifest,
)
from tests.integration.exports.conftest import populate_ml_dataset

# Minimal JSON Schema (fallback when mlcroissant is missing): we cover the
# Croissant 1.0 contract surface that the tests rely on.
_CROISSANT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["@context", "@type", "conformsTo", "name", "description"],
    "properties": {
        "@context": {"type": "object"},
        "@type": {"const": "sc:Dataset"},
        "conformsTo": {"const": CROISSANT_CONFORMS},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "license": {"type": "string"},
        "distribution": {"type": "array"},
        "recordSet": {"type": "array"},
    },
}


def test_croissant_stub_when_table_empty(fair_catalog):
    manifest = build_croissant_manifest(fair_catalog)
    assert manifest["hydromodpy:stub"] is True
    assert manifest["conformsTo"] == CROISSANT_CONFORMS
    assert manifest["@type"] == "sc:Dataset"


def test_croissant_real_manifest_has_features_and_targets(fair_catalog):
    ds_id = populate_ml_dataset(fair_catalog)
    manifest = build_croissant_manifest(fair_catalog, ds_id)
    assert manifest.get("hydromodpy:stub") is None or manifest["hydromodpy:stub"] is False
    assert manifest["hydromodpy:features"] == ["recharge", "precipitation", "temperature"]
    assert manifest["hydromodpy:targets"] == ["head"]
    assert manifest["hydromodpy:catalogHash"] == "deadbeefcafebabe"


def test_croissant_json_schema_fallback(fair_catalog):
    ds_id = populate_ml_dataset(fair_catalog)
    manifest = build_croissant_manifest(fair_catalog, ds_id)
    pytest.importorskip("jsonschema")
    import jsonschema

    jsonschema.validate(instance=manifest, schema=_CROISSANT_SCHEMA)


def test_croissant_mlcroissant_validator(fair_catalog):
    pytest.importorskip("mlcroissant")
    ds_id = populate_ml_dataset(fair_catalog)
    manifest = build_croissant_manifest(fair_catalog, ds_id)
    ok, errors = validate_manifest(manifest)
    assert ok, errors


def test_croissant_stub_passes_mlcroissant(fair_catalog):
    pytest.importorskip("mlcroissant")
    manifest = build_croissant_manifest(fair_catalog)
    ok, errors = validate_manifest(manifest)
    assert ok, errors


def test_croissant_written_file_is_json(fair_catalog, tmp_path: Path):
    ds_id = populate_ml_dataset(fair_catalog)
    out = write_croissant(fair_catalog, ds_id, tmp_path)
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["hydromodpy:datasetId"] == ds_id


def test_croissant_unknown_dataset_returns_stub(fair_catalog):
    manifest = build_croissant_manifest(fair_catalog, "00000000-0000-0000-0000-000000000000")
    assert manifest["hydromodpy:stub"] is True
