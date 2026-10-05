"""A setup reading a corrected ground still looks bare filenames up beside the declared DEM."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.ground_corrections import on_ground
from hydromodpy.spatial.geographic.core.lake_enforcement import lakes_from_config


def _setup(root: Path) -> SimpleNamespace:
    dem = root / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"")
    return SimpleNamespace(dem_init_path=str(dem), crs_project="EPSG:2154")


def test_without_a_correction_the_setup_is_returned_as_it_is(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    assert on_ground(setup, setup.dem_init_path) is setup


def test_with_a_correction_the_dem_is_the_ground_and_the_rest_is_forwarded(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    setup.dem_res = 25.0

    grounded = on_ground(setup, tmp_path / "ground.tif")

    assert grounded.dem_init_path == str(tmp_path / "ground.tif")
    assert grounded.source_dem_path == setup.dem_init_path
    assert grounded.dem_res == 25.0
    assert grounded.crs_project == "EPSG:2154"


def test_a_bare_lake_filename_resolves_beside_the_declared_dem(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    lakes = tmp_path / "data" / "lake_geometry" / "lakes.gpkg"
    lakes.parent.mkdir(parents=True)
    gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs="EPSG:2154").to_file(lakes, driver="GPKG")
    enforce = SimpleNamespace(lake_geometry_path=Path("lakes.gpkg"))

    found = lakes_from_config(enforce, on_ground(setup, tmp_path / "work" / "ground.tif"))

    assert len(found) == 1
