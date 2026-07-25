"""Conformance tests for the STAC Item 1.0 exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export import build_context, build_stac_item, write_stac_item
from hydromodpy.results.export.stac import STAC_VERSION
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests.integration.exports.conftest import populate_simulation


def test_stac_item_has_required_keys(fair_catalog):
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    assert item["type"] == "Feature"
    assert item["stac_version"] == STAC_VERSION
    assert item["id"] == sid
    assert "properties" in item
    assert "assets" in item
    assert "links" in item


def test_stac_bbox_and_geometry_from_catalog(fair_catalog):
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    assert item["bbox"] == [0.0, 0.0, 1000.0, 1000.0]
    geom = item["geometry"]
    assert geom is not None
    assert geom["type"] == "Polygon"
    assert geom["coordinates"][0][0] == [0.0, 0.0]


def test_stac_datetime_and_period_present(fair_catalog):
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    props = item["properties"]
    assert "datetime" in props
    assert "start_datetime" in props
    assert "end_datetime" in props


def test_stac_projection_extension(fair_catalog):
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    assert item["properties"]["proj:epsg"] == 2154
    assert "proj:wkt2" in item["properties"]
    assert any("projection" in ext for ext in item["stac_extensions"])


def test_stac_assets_contain_zarr(fair_catalog):
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    assets = item["assets"]
    assert "zarr" in assets
    zarr_asset = assets["zarr"]
    assert zarr_asset["href"].endswith(FIELDS_STORE_NAME)
    assert "roles" in zarr_asset


def test_stac_pystac_round_trip(fair_catalog):
    pystac = pytest.importorskip("pystac")
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    parsed = pystac.Item.from_dict(item)
    assert parsed.id == sid
    assert parsed.bbox == [0.0, 0.0, 1000.0, 1000.0]


def test_stac_collection_aggregates_items(fair_catalog):
    """``build_stac_collection`` unions the bbox and temporal range of items."""
    from hydromodpy.results.export.stac import build_stac_collection

    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    collection = build_stac_collection([item], collection_id="demo")
    assert collection["type"] == "Collection"
    assert collection["id"] == "demo"
    assert collection["extent"]["spatial"]["bbox"][0] == [0.0, 0.0, 1000.0, 1000.0]
    interval = collection["extent"]["temporal"]["interval"][0]
    assert interval[0] is not None and interval[1] is not None
    assert collection["summaries"]["hydromodpy:simCount"] == [1]


def test_stac_catalog_lists_collections(tmp_path: Path):
    """``build_stac_catalog`` references every collection_id as a child link."""
    from hydromodpy.results.export.stac import build_stac_catalog

    catalog = build_stac_catalog(
        catalog_id="my-workspace",
        title="My Workspace",
        description="HydroModPy workspace",
        collection_ids=["naizin", "lez"],
    )
    assert catalog["type"] == "Catalog"
    assert catalog["id"] == "my-workspace"
    children = [link for link in catalog["links"] if link["rel"] == "child"]
    assert len(children) == 2
    assert {link["title"] for link in children} == {"naizin", "lez"}


def test_stac_write_collection_and_catalog(tmp_path: Path, fair_catalog):
    """Both writers materialise valid JSON on disk."""
    from hydromodpy.results.export.stac import (
        write_stac_catalog,
        write_stac_collection,
    )

    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    coll_path = write_stac_collection([item], tmp_path / "collection", collection_id="demo")
    assert coll_path.is_file()
    json.loads(coll_path.read_text(encoding="utf-8"))
    cat_path = write_stac_catalog(tmp_path, catalog_id="workspace", collection_ids=["demo"])
    assert cat_path.is_file()
    json.loads(cat_path.read_text(encoding="utf-8"))


def test_stac_validator(fair_catalog):
    """When ``stac-validator`` is installed, the JSON Schema check must pass."""
    pytest.importorskip("stac_validator")
    sid = populate_simulation(fair_catalog)
    item = build_stac_item(build_context(fair_catalog, sid))
    from stac_validator import stac_validator as _sv  # type: ignore[import-not-found]

    sv = _sv.StacValidate()
    sv.validate_dict(item)
    results = sv.message
    assert results, "stac-validator returned no messages"
    for entry in results:
        assert entry["valid_stac"], entry


def test_stac_written_file_round_trip(fair_catalog, tmp_path: Path):
    sid = populate_simulation(fair_catalog)
    out = write_stac_item(fair_catalog, sid, tmp_path)
    assert out.is_file()
    assert out.name == f"{sid}.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["id"] == sid
