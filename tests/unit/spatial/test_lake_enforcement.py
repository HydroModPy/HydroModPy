"""The lake polygons of ``[geographic.enforce_lakes]`` are read from the data folder."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.lake_enforcement import lakes_from_config


def test_a_bare_lake_filename_resolves_beside_the_declared_dem(tmp_path: Path) -> None:
    dem = tmp_path / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"")
    setup = SimpleNamespace(dem_init_path=str(dem), crs_project="EPSG:2154")
    lakes = tmp_path / "data" / "lake_geometry" / "lakes.gpkg"
    lakes.parent.mkdir(parents=True)
    gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs="EPSG:2154").to_file(lakes, driver="GPKG")
    enforce = SimpleNamespace(lake_geometry_path=Path("lakes.gpkg"))

    assert len(lakes_from_config(enforce, setup)) == 1
