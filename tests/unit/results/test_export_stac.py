"""Unit tests for the pure STAC helpers and the ``build_stac_item`` builder.

These cover the deterministic branches the integration conformance test does
not exercise: bbox->polygon ring closure, UTC ISO normalisation, period
midpoint, multi-item bbox union, ``validate_item`` valid/invalid paths and the
top-level shape of ``build_stac_item`` on a synthetic context.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.results.export.context import AssetEntry, FairExportContext
from hydromodpy.results.export.stac import (
    STAC_VERSION,
    _bbox_to_polygon,
    _midpoint,
    _to_utc_iso,
    _union_bbox,
    build_stac_item,
    validate_item,
)
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME


def _make_context(
    *,
    sim_row: dict | None = None,
    assets: tuple[AssetEntry, ...] = (),
) -> FairExportContext:
    """Build a minimal synthetic context mirroring the catalog row shape."""
    row = {
        "sim_id": "sim-001",
        "name": "fair-sim",
        "project": "test",
        "solver_id": "modflow6",
        "n_cells": 8,
        "n_layers": 1,
        "n_timesteps": 6,
        "bbox_xmin": 0.0,
        "bbox_ymin": 0.0,
        "bbox_xmax": 1000.0,
        "bbox_ymax": 1000.0,
        "crs_epsg": 2154,
        "crs_wkt": "EPSG:2154",
        "period_start": "2020-01-01",
        "period_end": "2020-01-06",
    }
    if sim_row is not None:
        row = sim_row
    return FairExportContext(
        sim_id=str(row.get("sim_id", "sim-001")),
        sim_row=row,
        runs_env={},
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name="Jane Doe",
        creator_email="jane@example.org",
        assets=assets,
        inputs=(),
        lockfile_path=None,
        solver_binary_sha256=None,
        solver_name=None,
        solver_version=None,
        hydromodpy_version="0.0.0-test",
    )


@pytest.mark.fast
class TestBboxToPolygon:
    def test_closed_five_point_ring(self):
        poly = _bbox_to_polygon((0.0, 0.0, 1000.0, 1000.0))
        assert poly["type"] == "Polygon"
        ring = poly["coordinates"][0]
        assert len(ring) == 5
        # The ring must be closed: first vertex equals the last.
        assert ring[0] == ring[-1] == [0.0, 0.0]

    def test_corner_ordering(self):
        poly = _bbox_to_polygon((1.0, 2.0, 3.0, 4.0))
        ring = poly["coordinates"][0]
        assert ring == [
            [1.0, 2.0],
            [3.0, 2.0],
            [3.0, 4.0],
            [1.0, 4.0],
            [1.0, 2.0],
        ]


@pytest.mark.fast
class TestToUtcIso:
    def test_naive_date_gets_z_suffix_and_midnight(self):
        assert _to_utc_iso("2020-01-01") == "2020-01-01T00:00:00Z"

    def test_offset_normalised_to_utc(self):
        # +02:00 at 12:00 maps to 10:00 UTC.
        assert _to_utc_iso("2020-06-01T12:00:00+02:00") == "2020-06-01T10:00:00Z"

    def test_trailing_z_is_accepted(self):
        assert _to_utc_iso("2020-06-01T12:00:00Z") == "2020-06-01T12:00:00Z"

    def test_unparseable_value_returned_verbatim(self):
        assert _to_utc_iso("not-a-date") == "not-a-date"


@pytest.mark.fast
class TestMidpoint:
    def test_midpoint_between_start_and_end(self):
        # Midpoint of a 4-day window starting at midnight is day 3, 00:00.
        assert _midpoint("2020-01-01", "2020-01-05") == "2020-01-03T00:00:00Z"

    def test_start_only_returns_start(self):
        assert _midpoint("2020-01-01", None) == "2020-01-01T00:00:00Z"

    def test_end_only_returns_end(self):
        assert _midpoint(None, "2020-01-06") == "2020-01-06T00:00:00Z"

    def test_no_bounds_returns_z_suffixed_now(self):
        out = _midpoint(None, None)
        # Falls back to "now" in UTC; shape must still be valid STAC datetime.
        assert out.endswith("Z")
        assert len(out) == len("2020-01-01T00:00:00Z")

    def test_invalid_bounds_fall_back_to_start(self):
        assert _midpoint("not-a-date", "also-bad") == "not-a-date"


@pytest.mark.fast
class TestUnionBbox:
    def test_multi_item_min_max(self):
        items = [
            {"bbox": [0.0, 0.0, 10.0, 10.0]},
            {"bbox": [-5.0, 2.0, 8.0, 20.0]},
            {"bbox": [3.0, -1.0, 4.0, 4.0]},
        ]
        assert _union_bbox(items) == [-5.0, -1.0, 10.0, 20.0]

    def test_single_item_is_its_own_bbox(self):
        assert _union_bbox([{"bbox": [1.0, 2.0, 3.0, 4.0]}]) == [1.0, 2.0, 3.0, 4.0]

    def test_no_bbox_returns_none(self):
        assert _union_bbox([{"properties": {}}, {"bbox": None}]) is None

    def test_empty_list_returns_none(self):
        assert _union_bbox([]) is None


@pytest.mark.fast
class TestValidateItem:
    def test_valid_item_passes(self):
        pytest.importorskip("pystac")
        item = build_stac_item(_make_context())
        ok, reasons = validate_item(item)
        assert ok is True
        assert reasons == []

    def test_invalid_item_reports_reasons(self):
        pytest.importorskip("pystac")
        # A bare dict missing every required STAC field must fail parsing.
        ok, reasons = validate_item({"type": "Feature"})
        assert ok is False
        assert reasons
        assert all(isinstance(r, str) for r in reasons)


@pytest.mark.fast
class TestBuildStacItem:
    def test_top_level_structure(self):
        zarr_asset = AssetEntry(
            key="zarr",
            relative_path=f"{RUNS_DIRNAME}/demo_run/{FIELDS_STORE_NAME}",
            media_type="application/x.zarr-store",
            roles=("data", "fields"),
            sha256="deadbeef",
            size_bytes=42,
            description="Zarr store.",
        )
        item = build_stac_item(_make_context(assets=(zarr_asset,)))

        assert item["type"] == "Feature"
        assert item["stac_version"] == STAC_VERSION
        assert item["id"] == "sim-001"

        # Geometry mirrors the bbox ring; bbox is the flat 4-tuple list.
        assert item["bbox"] == [0.0, 0.0, 1000.0, 1000.0]
        assert item["geometry"]["type"] == "Polygon"
        assert item["geometry"]["coordinates"][0][0] == [0.0, 0.0]

        props = item["properties"]
        assert props["datetime"] == "2020-01-03T12:00:00Z"
        assert props["start_datetime"] == "2020-01-01T00:00:00Z"
        assert props["end_datetime"] == "2020-01-06T00:00:00Z"
        assert props["proj:epsg"] == 2154
        assert props["license"] == "CC-BY-4.0"
        assert props["hydromodpy:simId"] == "sim-001"
        assert props["created_by"] == "Jane Doe"

        # The Zarr asset is keyed and carries the directory-store media type.
        assert "zarr" in item["assets"]
        zarr = item["assets"]["zarr"]
        assert zarr["href"] == f"{RUNS_DIRNAME}/demo_run/{FIELDS_STORE_NAME}"
        assert zarr["type"] == "application/x.zarr-store"
        assert zarr["roles"] == ["data", "fields"]
        # file:checksum is a sha2-256 multihash (0x12 0x20 + digest), not bare hex.
        assert zarr["file:checksum"] == "1220deadbeef"
        assert "sha256" not in zarr
        assert zarr["file:size"] == 42

    def test_missing_bbox_drops_bbox_and_nulls_geometry(self):
        row = {
            "sim_id": "sim-002",
            "name": "no-bbox",
            "project": "test",
            "period_start": "2020-01-01",
            "period_end": "2020-01-06",
        }
        item = build_stac_item(_make_context(sim_row=row))
        # When the catalog has no bbox columns, the key is removed entirely
        # and geometry is explicitly null (STAC item-spec allowance).
        assert "bbox" not in item
        assert item["geometry"] is None

    def test_collection_link_present_when_project_set(self):
        item = build_stac_item(_make_context())
        rels = {link["rel"] for link in item["links"]}
        assert "self" in rels
        assert "collection" in rels
        coll_link = next(link for link in item["links"] if link["rel"] == "collection")
        assert coll_link["title"] == "test"
