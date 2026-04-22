from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.pipeline import (
    _flow_products_from_paths,
    _geographic_cache_fingerprint,
    _load_cached_geographic_products,
    _raster_products_from_paths,
    _required_geographic_cache_artifacts,
    _write_geographic_cache_manifest,
)


def _touch_artifact(path: str | Path) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.suffix.lower() == ".shp":
        for suffix in (".shp", ".shx", ".dbf"):
            path_obj.with_suffix(suffix).write_text("", encoding="utf-8")
        return
    path_obj.write_text("", encoding="utf-8")


def _cached_config(tmp_path: Path) -> GeographicConfig:
    dem_path = tmp_path / "dem.tif"
    dem_path.write_text("dem", encoding="utf-8")
    return GeographicConfig.model_validate(
        {
            "catch_def": "from_outlet_coord",
            "dem_init_path": dem_path,
            "x_outlet": 1.0,
            "y_outlet": 2.0,
            "snap_dist": 10.0,
            "buff_area": 10.0,
            "reuse_existing_outputs": True,
        }
    )


def test_geographic_cache_loads_matching_complete_artifacts(tmp_path: Path) -> None:
    config = _cached_config(tmp_path)
    paths = build_geographic_paths(tmp_path / "project")
    flow_products = _flow_products_from_paths(paths, str(config.dem_correc_type))
    raster_products = _raster_products_from_paths(paths)
    for path in _required_geographic_cache_artifacts(
        config=config,
        paths=paths,
        flow_products=flow_products,
        raster_products=raster_products,
    ):
        _touch_artifact(path)

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
    )

    cached = _load_cached_geographic_products(
        config=config,
        paths=paths,
        crs_project="EPSG:2154",
    )

    assert cached is not None
    assert cached.catchment_area_km2 == 12.0
    assert cached.domain_products.buffer_distance_m == 300.0
    assert cached.flow_products.direc.endswith("dem_direc.tif")


def test_geographic_cache_rejects_changed_fingerprint(tmp_path: Path) -> None:
    config = _cached_config(tmp_path)
    paths = build_geographic_paths(tmp_path / "project")
    flow_products = _flow_products_from_paths(paths, str(config.dem_correc_type))
    raster_products = _raster_products_from_paths(paths)
    for path in _required_geographic_cache_artifacts(
        config=config,
        paths=paths,
        flow_products=flow_products,
        raster_products=raster_products,
    ):
        _touch_artifact(path)
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
    )
    changed_config = config.model_copy(update={"x_outlet": 99.0})

    assert _geographic_cache_fingerprint(config) != _geographic_cache_fingerprint(changed_config)
    assert (
        _load_cached_geographic_products(
            config=changed_config,
            paths=paths,
            crs_project="EPSG:2154",
        )
        is None
    )
