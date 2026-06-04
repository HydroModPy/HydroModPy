"""Unit tests for the W3C PROV-O JSON-LD builder.

These tests feed a synthetic :class:`FairExportContext` (real dataclasses,
no DuckDB) into the real ``build_prov_document`` / ``serialise_prov`` and
assert the PROV-O id wiring: which entity ``wasGeneratedBy`` which activity,
which entity is ``used`` by the simulation, and which agents the activity
``wasAssociatedWith``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    InputEntry,
)
from hydromodpy.results.export.prov import (
    PROV_CONTEXT,
    build_prov_document,
    serialise_prov,
)

pytestmark = pytest.mark.fast

_SIM_ID = "sim-abc-123"
_ACTION_ID = "#action/simulation"


def _make_context(
    *,
    inputs: tuple[InputEntry, ...],
    assets: tuple[AssetEntry, ...],
    solver_name: str | None = "modflow6",
    creator_name: str | None = "Jane Doe",
) -> FairExportContext:
    """Build a fully synthetic context with one run row and env."""
    return FairExportContext(
        sim_id=_SIM_ID,
        sim_row={
            "sim_id": _SIM_ID,
            "project": "demo",
            "started_at": "2020-01-01T00:00:00+00:00",
            "ended_at": "2020-01-01T01:00:00+00:00",
        },
        runs_env={
            "hostname": "node-01",
            "git_commit": "deadbeef",
            "rng_seed": 7,
        },
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name=creator_name,
        creator_email="jane@example.org" if creator_name else None,
        assets=assets,
        inputs=inputs,
        lockfile_path=None,
        solver_binary_sha256="a" * 64,
        solver_name=solver_name,
        solver_version="6.4.1" if solver_name else None,
        hydromodpy_version="1.2.3",
    )


def _input(role: str = "dem", name: str = "dem.tif") -> InputEntry:
    return InputEntry(
        role=role,
        category="raster",
        original_path=f"/tmp/ws/data/{name}",
        sha256="b" * 64,
        size_bytes=2048,
        source_type="download",
        source_ref="https://example.org/dem.tif",
        loader_name="rasterio",
        license="cc-by-4.0",
        data_provider="IGN",
        fetched_at="2019-12-31T00:00:00+00:00",
    )


def _asset(key: str = "zarr", rel: str = "results/fields.zarr") -> AssetEntry:
    return AssetEntry(
        key=key,
        relative_path=rel,
        media_type="application/x.zarr-store",
        roles=("data", "fields"),
        sha256="c" * 64,
        size_bytes=4096,
        description="Zarr store.",
    )


@pytest.fixture
def context() -> FairExportContext:
    return _make_context(inputs=(_input(),), assets=(_asset(),))


def _nodes_by_id(activities: list[dict]) -> dict[str, dict]:
    return {node["@id"]: node for node in activities if "@id" in node}


def test_create_action_anchor_and_type(context: FairExportContext) -> None:
    """The activity node uses the fixed RO-Crate anchor and dual PROV type."""
    action = build_prov_document(context)["createAction"]
    assert action["@id"] == _ACTION_ID
    assert action["@type"] == ["CreateAction", "prov:Activity"]
    assert action["startTime"] == "2020-01-01T00:00:00+00:00"
    assert action["prov:startedAtTime"] == "2020-01-01T00:00:00+00:00"
    assert action["prov:endedAtTime"] == "2020-01-01T01:00:00+00:00"


def test_input_entity_used_by_activity(context: FairExportContext) -> None:
    """Each input entity id is referenced by the activity's prov:used list."""
    doc = build_prov_document(context)
    action = doc["createAction"]
    nodes = _nodes_by_id(doc["activities"])

    input_ids = [nid for nid in nodes if nid.startswith("#entity/input/")]
    assert len(input_ids) == 1
    eid = input_ids[0]

    used_ids = {ref["@id"] for ref in action["prov:used"]}
    object_ids = {ref["@id"] for ref in action["object"]}
    assert eid in used_ids
    assert eid in object_ids

    entity = nodes[eid]
    assert entity["@type"] == ["prov:Entity", "File"]
    assert entity["hydromodpy:role"] == "dem"
    assert entity["name"] == "dem.tif"


def test_input_was_generated_by_fetch_activity(context: FairExportContext) -> None:
    """An input with loader metadata wasGeneratedBy its own fetch activity."""
    doc = build_prov_document(context)
    nodes = _nodes_by_id(doc["activities"])

    eid = next(nid for nid in nodes if nid.startswith("#entity/input/"))
    fetch_id = nodes[eid]["prov:wasGeneratedBy"]["@id"]

    # The fetch activity referenced by the entity must exist as a node.
    assert fetch_id in nodes
    fetch_node = nodes[fetch_id]
    assert fetch_node["@id"].startswith("#action/fetch/")
    assert "prov:Activity" in fetch_node["@type"]
    assert fetch_node["hydromodpy:loaderName"] == "rasterio"
    assert fetch_node["agent"]["name"] == "IGN"


def test_output_was_generated_by_simulation_activity(context: FairExportContext) -> None:
    """Each output entity wasGeneratedBy the simulation activity id."""
    doc = build_prov_document(context)
    action = doc["createAction"]
    nodes = _nodes_by_id(doc["activities"])

    output_ids = [nid for nid in nodes if nid.startswith("#entity/output/")]
    assert len(output_ids) == 1
    oid = output_ids[0]
    output = nodes[oid]

    # The output points back at the very activity that declares it as a result.
    assert output["prov:wasGeneratedBy"]["@id"] == action["@id"]
    assert oid in {ref["@id"] for ref in action["result"]}
    assert output["encodingFormat"] == "application/x.zarr-store"


def test_output_was_derived_from_every_input(context: FairExportContext) -> None:
    """wasDerivedFrom lists exactly the declared input entity ids."""
    doc = build_prov_document(context)
    nodes = _nodes_by_id(doc["activities"])

    input_ids = {nid for nid in nodes if nid.startswith("#entity/input/")}
    oid = next(nid for nid in nodes if nid.startswith("#entity/output/"))

    derived = {ref["@id"] for ref in nodes[oid]["prov:wasDerivedFrom"]}
    assert derived == input_ids


def test_activity_was_associated_with_all_agents(context: FairExportContext) -> None:
    """wasAssociatedWith references HydroModPy, the solver and the creator agents."""
    doc = build_prov_document(context)
    action = doc["createAction"]
    nodes = _nodes_by_id(doc["activities"])

    assoc_ids = {ref["@id"] for ref in action["prov:wasAssociatedWith"]}
    assert "#agent/hydromodpy" in assoc_ids
    assert "#agent/solver/modflow6" in assoc_ids
    assert "#agent/creator" in assoc_ids

    # Every associated agent id must resolve to an actual agent node.
    for aid in assoc_ids:
        assert aid in nodes
        assert any(t.startswith("prov:") for t in nodes[aid]["@type"])

    hmp = nodes["#agent/hydromodpy"]
    assert hmp["name"] == "HydroModPy"
    assert hmp["softwareVersion"] == "1.2.3"


def test_no_solver_no_creator_omits_their_associations() -> None:
    """When solver/creator metadata is absent only HydroModPy is associated."""
    ctx = _make_context(
        inputs=(_input(),),
        assets=(_asset(),),
        solver_name=None,
        creator_name=None,
    )
    doc = build_prov_document(ctx)
    action = doc["createAction"]
    nodes = _nodes_by_id(doc["activities"])

    assoc_ids = {ref["@id"] for ref in action["prov:wasAssociatedWith"]}
    assert assoc_ids == {"#agent/hydromodpy"}
    assert "#agent/solver/modflow6" not in nodes
    assert "#agent/creator" not in nodes
    # The single solver instrument must not be appended either.
    instrument_ids = {ref["@id"] for ref in action["instrument"]}
    assert instrument_ids == {"#software/hydromodpy"}


def test_output_without_inputs_omits_was_derived_from() -> None:
    """With no inputs the output entity drops wasDerivedFrom entirely."""
    ctx = _make_context(inputs=(), assets=(_asset(),))
    doc = build_prov_document(ctx)
    nodes = _nodes_by_id(doc["activities"])

    assert not [nid for nid in nodes if nid.startswith("#entity/input/")]
    oid = next(nid for nid in nodes if nid.startswith("#entity/output/"))
    assert "prov:wasDerivedFrom" not in nodes[oid]
    # And the activity used nothing.
    assert "prov:used" not in nodes[oid]
    action = doc["createAction"]
    assert action["object"] == []


def test_two_inputs_produce_distinct_entity_and_fetch_ids() -> None:
    """Distinct inputs get distinct entity ids, each with its own fetch id."""
    ctx = _make_context(
        inputs=(_input("dem", "dem.tif"), _input("recharge", "rch.nc")),
        assets=(_asset(),),
    )
    doc = build_prov_document(ctx)
    action = doc["createAction"]
    nodes = _nodes_by_id(doc["activities"])

    input_ids = [nid for nid in nodes if nid.startswith("#entity/input/")]
    assert len(input_ids) == 2
    assert len(set(input_ids)) == 2

    fetch_ids = [nodes[i]["prov:wasGeneratedBy"]["@id"] for i in input_ids]
    assert len(set(fetch_ids)) == 2

    # The output derives from both inputs.
    oid = next(nid for nid in nodes if nid.startswith("#entity/output/"))
    derived = {ref["@id"] for ref in nodes[oid]["prov:wasDerivedFrom"]}
    assert derived == set(input_ids)

    used_ids = {ref["@id"] for ref in action["prov:used"]}
    assert used_ids == set(input_ids)


def test_serialise_prov_graph_head_is_action(context: FairExportContext) -> None:
    """serialise_prov wraps the doc with PROV context and puts the action first."""
    doc = serialise_prov(context)
    assert doc["@context"] == PROV_CONTEXT
    graph = doc["@graph"]
    assert isinstance(graph, list)
    assert graph[0]["@id"] == _ACTION_ID

    # The graph is the action plus every activity node, no loss.
    built = build_prov_document(context)
    assert len(graph) == 1 + len(built["activities"])
    graph_ids = {node["@id"] for node in graph if "@id" in node}
    for node in built["activities"]:
        assert node["@id"] in graph_ids


def test_serialise_prov_is_json_serialisable(context: FairExportContext) -> None:
    """The full document round-trips through json without custom encoders."""
    import json

    doc = serialise_prov(context)
    parsed = json.loads(json.dumps(doc))
    assert parsed["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert parsed["@graph"][0]["@type"] == ["CreateAction", "prov:Activity"]
