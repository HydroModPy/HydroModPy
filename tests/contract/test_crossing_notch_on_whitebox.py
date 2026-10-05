"""The crossing notch, run for real on Whitebox over a road across a valley.

A V valley drains south and a road embankment, three metres high, is laid across
it at row 30. The domain entry point delineates, finds the road on the generated
channel, notches the ground there, delineates again, and clips the model top from
the notched ground. What the unit tests pin on recorders is checked here on the
real rasters: the names of the channel rasters, the pointer encoding, the walk.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("whitebox_workflows")
gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (  # noqa: E402
    build_geographic_derived_features,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig  # noqa: E402

RES = 25.0
ROWS, COLS, AXIS, ROAD_ROW = 60, 41, 20, 30
EMBANKMENT_M = 3.0


@pytest.fixture(autouse=True)
def _single_thread_whitebox(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests._helpers.whitebox import configure_whitebox_single_thread

    configure_whitebox_single_thread(monkeypatch)


def _y(row: int) -> float:
    return ROWS * RES - (row + 0.5) * RES


def _valley_with_a_road(tmp_path: Path) -> tuple[Path, np.ndarray]:
    rows, cols = np.mgrid[0:ROWS, 0:COLS]
    surface = 100.0 - 0.5 * rows + 2.0 * np.abs(cols - AXIS)
    surface[ROAD_ROW, :] += EMBANKMENT_M
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=ROWS,
        width=COLS,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=rasterio.transform.from_origin(0.0, ROWS * RES, RES, RES),
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path, surface


def _the_road(tmp_path: Path) -> Path:
    path = tmp_path / "crossings.gpkg"
    frame = gpd.GeoDataFrame(
        {"kind": ["road"], "source": ["custom"], "name": ["D1"], "drop_m": [float("nan")]},
        geometry=[LineString([(0.0, _y(ROAD_ROW)), (COLS * RES, _y(ROAD_ROW))])],
        crs="EPSG:2154",
    )
    frame.to_file(path, driver="GPKG")
    return path


def _run(tmp_path: Path):
    dem, surface = _valley_with_a_road(tmp_path)
    config = GeographicConfig.from_outlet(
        x=(AXIS + 0.5) * RES,
        y=_y(ROWS - 3),
        dem=dem,
        snap_dist="100 m",
        buff_area="10%",
        crs_project="EPSG:2154",
        river_network={"enabled": True, "threshold_mode": "cells", "threshold_cells": 15},
        crossings={"enabled": True, "path": _the_road(tmp_path), "bed_reach": 75.0},
    )
    workspace = SimpleNamespace(project_root=tmp_path / "results")
    features = build_geographic_derived_features(config=config, workspace=workspace)
    return features, surface, tmp_path / "results"


def _find(root: Path, name: str) -> Path:
    (found,) = root.rglob(name)
    return found


def test_the_road_on_the_generated_channel_is_notched_and_the_report_says_so(tmp_path) -> None:
    _, _, results = _run(tmp_path)

    report = json.loads(_find(results, "dem_ground_crossings.json").read_text())

    assert report["crossing_points"] == {"road": 1}
    assert report["notched"] == {"road": 1}
    assert report["skipped"] == {}
    assert report["pixels_lowered"] == 1
    assert report["max_lowering_m"] == pytest.approx(EMBANKMENT_M)
    assert report["catchment_area_km2_before"] > 0.0
    assert report["catchment_area_km2_after"] > 0.0


def test_the_ground_falls_to_the_bed_line_on_the_channel_and_nowhere_else(tmp_path) -> None:
    _, surface, results = _run(tmp_path)

    with rasterio.open(_find(results, "dem_ground.tif")) as src:
        ground = src.read(1)

    assert np.argwhere(ground != surface.astype("float32")).tolist() == [[ROAD_ROW, AXIS]]
    assert ground[ROAD_ROW, AXIS] == pytest.approx(surface[ROAD_ROW, AXIS] - EMBANKMENT_M)


def test_the_model_top_is_clipped_from_the_notched_ground(tmp_path) -> None:
    features, _, results = _run(tmp_path)

    with rasterio.open(_find(results, "dem_ground.tif")) as ground:
        notched = ground.read(1)[ROAD_ROW, AXIS]
        x, y = ground.xy(ROAD_ROW, AXIS)
    with rasterio.open(features.watershed_box_buff_dem) as top:
        row, col = top.index(x, y)
        clipped = top.read(1)[row, col]

    assert clipped == pytest.approx(notched)
