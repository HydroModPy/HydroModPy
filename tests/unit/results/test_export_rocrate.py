"""Unit tests for the RO-Crate v1.1 JSON-LD builder.

These build a real :class:`FairExportContext` from synthetic asset / input
data (no catalog, no DuckDB) and call the real ``build_ro_crate``. They
assert the structural contract of the emitted JSON-LD graph.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    InputEntry,
)
from hydromodpy.results.export.prov import HYDROMODPY_NAMESPACE
from hydromodpy.results.export.rocrate import (
    RO_CRATE_CONFORMS,
    RO_CRATE_CONTEXT,
    RO_CRATE_METADATA_FILENAME,
    build_ro_crate,
    loads,
)
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME

_ZARR_HREF = f"projects/demo/{RUNS_DIRNAME}/demo_run/{FIELDS_STORE_NAME}"


def _make_context() -> FairExportContext:
    """A self-contained context with two assets, one input and a bbox row."""
    sim_row = {
        "sim_id": "sim-123",
        "name": "demo-sim",
        "description": "A demo simulation.",
        "project": "demo",
        "solver_id": 7,
        "doi": "https://doi.org/10.5281/zenodo.1234",
        "bbox_xmin": 0.0,
        "bbox_ymin": 0.0,
        "bbox_xmax": 1000.0,
        "bbox_ymax": 2000.0,
        "period_start": "2020-01-01",
        "period_end": "2020-01-06",
        "started_at": "2020-02-01T00:00:00",
        "ended_at": "2020-02-01T01:00:00",
    }
    assets = (
        AssetEntry(
            key="zarr",
            relative_path=_ZARR_HREF,
            media_type="application/x.zarr-store",
            roles=("data", "fields"),
            sha256="a" * 64,
            size_bytes=4096,
            description="Zarr store.",
        ),
        AssetEntry(
            key="lockfile",
            relative_path="projects/demo/hydromodpy.lock",
            media_type="application/toml",
            roles=("metadata", "provenance"),
            sha256="b" * 64,
            size_bytes=128,
            description="Reproducibility lockfile.",
        ),
    )
    inputs = (
        InputEntry(
            role="dem",
            category="raster",
            original_path="/data/dem/srtm_dem.tif",
            sha256="c" * 64,
            size_bytes=2048,
            source_type="http",
            source_ref="https://example.org/dem.tif",
            loader_name="rasterio",
            license="CC-BY-4.0",
            data_provider="USGS",
            fetched_at="2020-01-01T00:00:00+00:00",
        ),
    )
    return FairExportContext(
        sim_id="sim-123",
        sim_row=sim_row,
        runs_env={"git_commit": "deadbeef", "hostname": "node1"},
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name="Ada Lovelace",
        creator_email="ada@example.org",
        assets=assets,
        inputs=inputs,
        lockfile_path=Path("/tmp/ws/projects/demo/hydromodpy.lock"),
        solver_binary_sha256="d" * 64,
        solver_name="modflow6",
        solver_version="6.4.1",
        hydromodpy_version="1.2.3",
        generated_at="2020-02-02T00:00:00+00:00",
    )


@pytest.fixture
def crate() -> dict:
    return build_ro_crate(_make_context())


@pytest.mark.fast
def test_context_block_present_and_well_formed(crate):
    ctx = crate["@context"]
    assert isinstance(ctx, list)
    # First element is the canonical RO-Crate 1.1 context URL.
    assert ctx[0] == RO_CRATE_CONTEXT
    # The inline term map declares the hydromodpy/prov/sha256 prefixes.
    term_map = ctx[1]
    assert term_map["prov"] == "http://www.w3.org/ns/prov#"
    # The crate and the PROV-O document must declare the same vocabulary IRI.
    assert term_map["hydromodpy"] == HYDROMODPY_NAMESPACE
    assert "sha256" in term_map


@pytest.mark.fast
def test_metadata_descriptor_node(crate):
    graph = crate["@graph"]
    descriptors = [n for n in graph if n.get("@id") == RO_CRATE_METADATA_FILENAME]
    assert len(descriptors) == 1
    desc = descriptors[0]
    assert desc["@type"] == "CreativeWork"
    assert desc["conformsTo"] == {"@id": RO_CRATE_CONFORMS}
    assert desc["about"] == {"@id": "./"}


@pytest.mark.fast
def test_root_dataset_node(crate):
    graph = crate["@graph"]
    datasets = [n for n in graph if n.get("@id") == "./"]
    assert len(datasets) == 1
    ds = datasets[0]
    assert ds["@type"] == "Dataset"
    assert ds["name"] == "demo-sim"
    assert ds["description"] == "A demo simulation."
    assert ds["identifier"] == "sim-123"
    assert ds["hydromodpy:simId"] == "sim-123"
    assert ds["hydromodpy:project"] == "demo"
    assert ds["hydromodpy:solverId"] == 7
    assert ds["license"] == {"@id": "https://creativecommons.org/licenses/by/4.0/"}
    assert ds["datePublished"] == "2020-02-02T00:00:00+00:00"
    # DOI maps to sameAs.
    assert ds["sameAs"] == "https://doi.org/10.5281/zenodo.1234"
    # temporalCoverage built from period_start/period_end.
    assert ds["temporalCoverage"] == "2020-01-01/2020-01-06"
    # spatialCoverage points to the Place node derived from the bbox.
    assert ds["spatialCoverage"] == {"@id": "#place/bbox"}
    assert ds["wasGeneratedBy"] == {"@id": "#action/simulation"}
    assert ds["creator"] == [{"@id": "#person/Ada_Lovelace"}]


@pytest.mark.fast
def test_root_dataset_haspart_resolves_to_every_asset(crate):
    graph = crate["@graph"]
    ds = next(n for n in graph if n.get("@id") == "./")
    haspart_ids = {ref["@id"] for ref in ds["hasPart"]}
    asset_ids = {
        _ZARR_HREF,
        "projects/demo/hydromodpy.lock",
    }
    assert haspart_ids == asset_ids
    # Every referenced part must resolve to a sibling node in the same graph.
    graph_ids = {n.get("@id") for n in graph}
    assert asset_ids <= graph_ids


@pytest.mark.fast
def test_asset_nodes_have_file_type_and_metadata(crate):
    graph = crate["@graph"]
    zarr = next(n for n in graph if n.get("@id") == _ZARR_HREF)
    assert zarr["@type"] == "File"
    assert zarr["name"] == FIELDS_STORE_NAME
    assert zarr["encodingFormat"] == "application/x.zarr-store"
    assert zarr["hydromodpy:assetKey"] == "zarr"
    assert zarr["hydromodpy:simId"] == "sim-123"
    assert zarr["sha256"] == "a" * 64
    assert zarr["contentSize"] == 4096
    assert zarr["hydromodpy:roles"] == ["data", "fields"]


@pytest.mark.fast
def test_input_node_built_from_input_entry(crate):
    graph = crate["@graph"]
    input_nodes = [n for n in graph if str(n.get("@id", "")).startswith("inputs/")]
    assert len(input_nodes) == 1
    node = input_nodes[0]
    assert node["@id"] == "inputs/dem/0/srtm_dem.tif"
    assert node["@type"] == "File"
    assert node["name"] == "srtm_dem.tif"
    assert node["hydromodpy:role"] == "dem"
    assert node["hydromodpy:category"] == "raster"
    assert node["sha256"] == "c" * 64
    assert node["contentSize"] == 2048
    assert node["url"] == "https://example.org/dem.tif"
    assert node["hydromodpy:sourceType"] == "http"
    assert node["hydromodpy:loader"] == "rasterio"
    assert node["license"] == "CC-BY-4.0"
    assert node["publisher"] == {"@type": "Organization", "name": "USGS"}
    assert node["dateCreated"] == "2020-01-01T00:00:00+00:00"


@pytest.mark.fast
def test_software_and_creator_nodes(crate):
    graph = crate["@graph"]
    hmp = next(n for n in graph if n.get("@id") == "#software/hydromodpy")
    assert hmp["@type"] == "SoftwareApplication"
    assert hmp["softwareVersion"] == "1.2.3"
    assert hmp["url"] == "https://docs.hydromodpy.fr/"
    # git_commit from runs_env attaches as softwareSourceCode.
    assert hmp["softwareSourceCode"] == "deadbeef"

    solver = next(n for n in graph if n.get("@id") == "#software/modflow6")
    assert solver["name"] == "modflow6"
    assert solver["softwareVersion"] == "6.4.1"
    assert solver["sha256"] == "d" * 64

    person = next(n for n in graph if n.get("@id") == "#person/Ada_Lovelace")
    assert person["@type"] == "Person"
    assert person["name"] == "Ada Lovelace"
    assert person["email"] == "ada@example.org"


@pytest.mark.fast
def test_geo_and_place_nodes_from_bbox(crate):
    graph = crate["@graph"]
    geo = next(n for n in graph if n.get("@id") == "#geo/bbox")
    assert geo["@type"] == "GeoShape"
    # box uses "ymin xmin ymax xmax" ordering.
    assert geo["box"] == "0.0 0.0 2000.0 1000.0"
    place = next(n for n in graph if n.get("@id") == "#place/bbox")
    assert place["@type"] == "Place"
    assert place["geo"] == {"@id": "#geo/bbox"}


@pytest.mark.fast
def test_prov_create_action_embedded_with_agent(crate):
    graph = crate["@graph"]
    action = next(n for n in graph if n.get("@id") == "#action/simulation")
    assert "CreateAction" in action["@type"]
    assert "prov:Activity" in action["@type"]
    # The creator ref overrides the action agent in the RO-Crate builder.
    assert action["agent"] == {"@id": "#person/Ada_Lovelace"}
    # Outputs reference both assets by their PROV entity ids.
    result_ids = {ref["@id"] for ref in action["result"]}
    assert result_ids == {"#entity/output/zarr", "#entity/output/lockfile"}
    # The single input is recorded as an object.
    object_ids = {ref["@id"] for ref in action["object"]}
    assert object_ids == {"#entity/input/dem/0/srtm_dem.tif"}


@pytest.mark.fast
def test_one_node_per_asset_and_input(crate):
    graph = crate["@graph"]
    asset_file_ids = {
        n["@id"] for n in graph if n.get("@type") == "File" and "hydromodpy:assetKey" in n
    }
    assert asset_file_ids == {
        _ZARR_HREF,
        "projects/demo/hydromodpy.lock",
    }
    input_file_ids = {
        n["@id"] for n in graph if n.get("@type") == "File" and "hydromodpy:role" in n
    }
    assert input_file_ids == {"inputs/dem/0/srtm_dem.tif"}


@pytest.mark.fast
def test_loads_round_trip_equals_built_crate():
    built = build_ro_crate(_make_context())
    serialised = json.dumps(built)
    restored = loads(serialised)
    assert restored == built
    # Sanity: the round-trip preserves the structural anchors, not just bytes.
    assert restored["@graph"][0]["@id"] == RO_CRATE_METADATA_FILENAME
    assert any(n.get("@id") == "./" for n in restored["@graph"])


@pytest.mark.fast
def test_missing_optional_fields_are_omitted():
    """A minimal context with no creator / bbox / doi omits those nodes."""
    ctx = FairExportContext(
        sim_id="bare",
        sim_row={"sim_id": "bare"},
        runs_env={},
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name=None,
        creator_email=None,
        assets=(),
        inputs=(),
        lockfile_path=None,
        solver_binary_sha256=None,
        solver_name=None,
        solver_version=None,
        hydromodpy_version="1.0.0",
        generated_at="2020-02-02T00:00:00+00:00",
    )
    crate = build_ro_crate(ctx)
    graph = crate["@graph"]
    ds = next(n for n in graph if n.get("@id") == "./")
    # Falls back to sim_id for the name when no name/description is present.
    assert ds["name"] == "bare"
    assert ds["description"] == ""
    assert "sameAs" not in ds
    assert "spatialCoverage" not in ds
    assert "creator" not in ds
    assert ds["hasPart"] == []
    # No bbox -> no geo/place nodes; no solver -> only the hydromodpy software.
    ids = {n.get("@id") for n in graph}
    assert "#geo/bbox" not in ids
    assert "#place/bbox" not in ids
    assert "#software/hydromodpy" in ids
    assert not any(str(i).startswith("#software/") and i != "#software/hydromodpy" for i in ids)
