"""The site selection manifest is checked against its schema and the files it lists."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point

from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.schema.site_selection_manifest import (
    MANIFEST_SCHEMA_VERSION,
    SITE_SELECTION_MANIFEST_NAME,
    validate_selection_manifest,
    write_selection_manifest,
)

pytestmark = pytest.mark.fast

CORE = {
    "criteria_components_jsonl": "criteria_components.jsonl",
    "site_selection_decisions_jsonl": "site_selection_decisions.jsonl",
    "site_selection_manifest_json": SITE_SELECTION_MANIFEST_NAME,
}


def _vectors(root):
    frame = gpd.GeoDataFrame(
        {"site_id": ["site_001"]}, geometry=[Point(350000.0, 6810000.0)], crs="EPSG:2154"
    )
    frame.to_file(root / "site_selection.gpkg", layer="selected_outlets", driver="GPKG")
    write_geoparquet_atomic(frame, root / "selected_outlets.parquet")
    return {
        "site_selection_gpkg": "site_selection.gpkg",
        "selected_outlets_geoparquet": "selected_outlets.parquet",
    }


def _geojson(root):
    (root / "selected_outlets.geojson").write_text('{"type":"FeatureCollection"}')
    return {"selected_outlets_geojson": "selected_outlets.geojson"}


def _png(root):
    (root / "site_selection_map.png").write_bytes(b"not-a-png")
    return {"site_selection_map_png": "site_selection_map.png"}


def _no_components(root):
    (root / "criteria_components.jsonl").unlink()
    return {}


@pytest.mark.parametrize(
    ("extra_files", "schema_version", "check_outputs", "error"),
    [
        (lambda root: {}, MANIFEST_SCHEMA_VERSION, True, None),
        (_vectors, MANIFEST_SCHEMA_VERSION, True, None),
        (_no_components, MANIFEST_SCHEMA_VERSION, True, "criteria_components_jsonl"),
        (lambda root: {}, "bad", False, "unsupported schema_version"),
        (_geojson, MANIFEST_SCHEMA_VERSION, True, "features must be a list"),
        (_png, MANIFEST_SCHEMA_VERSION, True, "invalid PNG"),
    ],
    ids=["core", "vectors", "missing-file", "schema-version", "geojson", "png"],
)
def test_a_manifest_is_valid_only_with_its_schema_and_readable_outputs(
    tmp_path, extra_files, schema_version, check_outputs, error
):
    root = tmp_path / "out"
    root.mkdir()
    for name in ("site_selection_decisions.jsonl", "criteria_components.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    path = root / SITE_SELECTION_MANIFEST_NAME
    manifest = {
        "schema_version": schema_version,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "selection_id": "demo",
        "action": "delineated_catchments",
        "output_root": str(root),
        **dict.fromkeys(("strategy", "territory", "input", "criteria", "counts"), {}),
        "outputs": {**CORE, **extra_files(root)},
        "flow_products": {},
    }
    write_selection_manifest(path, manifest)

    errors = validate_selection_manifest(path, check_outputs=check_outputs)

    assert errors == [] if error is None else any(error in item for item in errors)
