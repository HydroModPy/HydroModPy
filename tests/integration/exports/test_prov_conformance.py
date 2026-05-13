"""Lightweight conformance tests for the PROV-O JSON-LD exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export import build_context
from hydromodpy.results.export.prov import (
    PROV_CONTEXT,
    build_prov_document,
    serialise_prov,
    write_prov,
)
from tests.integration.exports.conftest import populate_simulation


def test_prov_document_has_action_and_outputs(fair_catalog):
    sid = populate_simulation(fair_catalog)
    doc = build_prov_document(build_context(fair_catalog, sid))
    action = doc["createAction"]
    assert action["@id"] == "#action/simulation"
    assert "CreateAction" in action["@type"]
    assert action["result"], "expected at least one output entity"


def test_prov_serialised_jsonld_is_valid_json(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    doc = serialise_prov(build_context(fair_catalog, sid))
    assert doc["@context"] == PROV_CONTEXT
    assert isinstance(doc["@graph"], list)
    # round-trip via JSON.
    raw = json.dumps(doc)
    parsed = json.loads(raw)
    assert parsed["@graph"][0]["@id"] == "#action/simulation"


def test_prov_written_file_round_trip(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    out = write_prov(fair_catalog, sid, tmp_path)
    assert out.is_file()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert "@graph" in parsed


def test_prov_rdflib_round_trip(fair_catalog):
    rdflib = pytest.importorskip("rdflib")
    sid = populate_simulation(fair_catalog)
    doc = serialise_prov(build_context(fair_catalog, sid))
    g = rdflib.Graph()
    g.parse(data=json.dumps(doc), format="json-ld")
    assert len(g) > 0
