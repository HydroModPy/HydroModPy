"""Lightweight conformance tests for the PROV-O JSON-LD exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export.prov import (
    PROV_CONTEXT,
    build_prov_document,
    serialise_prov,
    write_prov,
)
from tests.integration.exports.conftest import SIM_ID


def test_prov_document_has_action_and_outputs(fair_context):
    sid = SIM_ID
    doc = build_prov_document(fair_context)
    action = doc["createAction"]
    assert action["@id"] == "#action/simulation"
    assert "CreateAction" in action["@type"]
    assert action["result"], "expected at least one output entity"


def test_prov_serialised_jsonld_is_valid_json(fair_context, tmp_path: Path):
    sid = SIM_ID
    doc = serialise_prov(fair_context)
    assert doc["@context"] == PROV_CONTEXT
    assert isinstance(doc["@graph"], list)
    # round-trip via JSON.
    raw = json.dumps(doc)
    parsed = json.loads(raw)
    assert parsed["@graph"][0]["@id"] == "#action/simulation"


def test_prov_written_file_round_trip(fair_context, tmp_path: Path):
    sid = SIM_ID
    out = write_prov(fair_context, tmp_path)
    assert out.is_file()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert "@graph" in parsed


def test_prov_rdflib_round_trip(fair_context):
    rdflib = pytest.importorskip("rdflib")
    sid = SIM_ID
    doc = serialise_prov(fair_context)
    g = rdflib.Graph()
    g.parse(data=json.dumps(doc), format="json-ld")
    assert len(g) > 0


def test_prov_document_emits_software_agent_for_hydromodpy(fair_context):
    """A ``prov:SoftwareAgent`` node names HydroModPy with its version."""
    sid = SIM_ID
    doc = build_prov_document(fair_context)
    agents = [node for node in doc["activities"] if "prov:SoftwareAgent" in node.get("@type", [])]
    hmp_agent = next((a for a in agents if a["name"] == "HydroModPy"), None)
    assert hmp_agent is not None
    assert hmp_agent["softwareVersion"], "HydroModPy agent must carry its version"


def test_prov_activity_was_associated_with_agents(fair_context):
    """The simulation activity references every PROV agent via ``wasAssociatedWith``."""
    sid = SIM_ID
    doc = build_prov_document(fair_context)
    action = doc["createAction"]
    assert "prov:wasAssociatedWith" in action
    refs = {entry["@id"] for entry in action["prov:wasAssociatedWith"]}
    assert "#agent/hydromodpy" in refs


def test_prov_outputs_have_was_derived_from_when_inputs_exist(fair_context):
    """Output entities link to inputs via ``wasDerivedFrom`` -- when inputs are declared.

    The fixture may not seed any input entries; in that case the
    ``wasDerivedFrom`` field is intentionally omitted (an empty list would
    be misleading). The check is conditional on the presence of inputs.
    """
    sid = SIM_ID
    doc = build_prov_document(fair_context)
    activities = doc["activities"]
    inputs = [
        node for node in activities if "@id" in node and node["@id"].startswith("#entity/input/")
    ]
    outputs = [
        node for node in activities if "@id" in node and node["@id"].startswith("#entity/output/")
    ]
    assert outputs, "expected at least one output entity"
    if not inputs:
        for entity in outputs:
            assert "prov:wasDerivedFrom" not in entity, (
                "wasDerivedFrom must not appear when no inputs are declared"
            )
        return
    for entity in outputs:
        assert "prov:wasDerivedFrom" in entity
        assert entity["prov:wasDerivedFrom"], "wasDerivedFrom must not be empty"
