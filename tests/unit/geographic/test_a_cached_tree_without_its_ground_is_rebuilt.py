"""The model top of a cache hit is the ground, so a tree that lacks it is a miss."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.core.ground_corrections import GROUND_DAM_FILENAME
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.pipeline import (
    _load_cached_geographic_products,
    _raster_products_from_paths,
    _required_geographic_cache_artifacts,
    _write_geographic_cache_manifest,
)


def _raster(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 1.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.zeros((1, 1), dtype="float32"), 1)


def _touch(path: str | Path) -> None:
    path = Path(path)
    if path.suffix.lower() == ".tif":
        _raster(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".shp":
        for suffix in (".shp", ".shx", ".dbf"):
            path.with_suffix(suffix).write_text("", encoding="utf-8")
        return
    path.write_text("", encoding="utf-8")


def _tree(tmp_path: Path, *, dam: bool):
    dem = tmp_path / "dem.tif"
    _raster(dem)
    sections = {}
    if dam:
        line = tmp_path / "dam.gpkg"
        gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:2154").to_file(
            line, driver="GPKG"
        )
        sections = {"dam_carve": {"enabled": True, "line_path": line}}
    config = GeographicConfig.model_validate(
        {
            "catchment": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem,
                "x_outlet": 1.0,
                "y_outlet": 2.0,
                "snap_dist": 10.0,
                "buff_area": 10.0,
            },
            "reuse_existing_outputs": True,
            **sections,
        }
    )
    paths = build_geographic_paths(tmp_path / "project")
    for artifact in _required_geographic_cache_artifacts(
        config=config, paths=paths, raster_products=_raster_products_from_paths(paths)
    ):
        _touch(artifact)
    _write_geographic_cache_manifest(
        config=config,
        paths=paths,
        domain_products=CatchmentDomainProducts(
            catchment_area_km2=12.0,
            buffer_distance_m=300.0,
            watershed_buff_shp=str(Path(paths.geographic_path) / "watershed_buff.shp"),
            watershed_box_shp=paths.watershed_box_shp,
            watershed_box_buff_shp=paths.box_buff,
        ),
        catchment_area_km2=12.0,
        catchment_products=None,
    )
    return config, paths


def _load(config, paths):
    return _load_cached_geographic_products(config=config, paths=paths, crs_project="EPSG:2154")


def test_a_tree_with_the_dam_carved_ground_is_a_hit(tmp_path: Path) -> None:
    config, paths = _tree(tmp_path, dam=True)
    _raster(Path(paths.correcflow_path) / GROUND_DAM_FILENAME)

    assert _load(config, paths) is not None


def test_a_tree_written_before_the_ground_had_its_own_file_is_a_miss(tmp_path: Path) -> None:
    config, paths = _tree(tmp_path, dam=True)

    assert _load(config, paths) is None


def test_a_tree_without_corrections_needs_no_ground_file(tmp_path: Path) -> None:
    config, paths = _tree(tmp_path, dam=False)

    assert _load(config, paths) is not None
