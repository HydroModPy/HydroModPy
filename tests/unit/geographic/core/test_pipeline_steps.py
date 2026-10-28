"""The steps the geographic pipeline chains: the run, the catchment and the domain polygons."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.geographic_cases import outlet_config, write_features
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.terrain_doubles import fake_accumulation


def _dem(tmp_path: Path) -> Path:
    values = np.arange(100, dtype="float32").reshape(10, 10)
    return write_geotiff(tmp_path / "dem.tif", values, cell=100.0, nodata=-9999.0)


def _config(dem: Path, **catchment) -> GeographicConfig:
    return outlet_config(dem, x=450.0, y=550.0, catchment={"snap_dist": "150 m", **catchment})


def test_prepare_geographic_run_reads_the_aggregated_dem_when_asked(tmp_path: Path) -> None:
    dem = _dem(tmp_path)

    native = prepare_geographic_run(config=_config(dem), out_dir_path=tmp_path / "a")
    coarse = prepare_geographic_run(
        config=_config(dem, dem_resolution="300 m"), out_dir_path=tmp_path / "b"
    )
    same = prepare_geographic_run(
        config=_config(dem, dem_resolution=100.0), out_dir_path=tmp_path / "c"
    )

    assert (native.dem_res, native.dem_init_path) == (100.0, str(dem))
    assert (native.crs_project, native.epsg) == ("EPSG:2154", 2154)
    assert coarse.dem_res == 300.0
    assert Path(coarse.dem_init_path).name == "dem_init_300m.tif"
    assert Path(coarse.dem_init_path).is_relative_to(tmp_path / "b")
    with rasterio.open(coarse.dem_init_path) as src:
        assert (src.height, src.width) == (4, 4)
    assert same.dem_init_path == str(dem)


def test_a_given_polygon_is_the_catchment_and_its_domain_is_buffered_around_it(tmp_path) -> None:
    dem = _dem(tmp_path)
    polygon = write_features(tmp_path / "given.shp", [box(200.0, 200.0, 800.0, 800.0)])
    config = GeographicConfig.from_polygon(polygon, dem=dem, buff_area="100 m")
    run = prepare_geographic_run(config=config, out_dir_path=tmp_path / "run")

    watershed = build_standard_catchment(
        config=config,
        paths=run.paths,
        accumulation=fake_accumulation(),
        crs_project=run.crs_project,
        backend=object(),
    )
    domain = build_standard_domain_polygons(
        config=config, paths=run.paths, dem_init_path=dem, crs_project=run.crs_project
    )

    assert watershed == run.paths.watershed_shp
    assert gpd.read_file(watershed).total_bounds.tolist() == [200.0, 200.0, 800.0, 800.0]
    assert domain.buffer_distance_m == 100.0
    assert gpd.read_file(run.paths.box_buff).total_bounds.tolist() == [100.0, 100.0, 900.0, 900.0]
    assert domain.catchment_area_km2 == pytest.approx(0.36)


def test_a_dem_driven_domain_has_no_catchment_to_build(tmp_path) -> None:
    dem = _dem(tmp_path)
    config = GeographicConfig.from_dem(dem)
    run = prepare_geographic_run(config=config, out_dir_path=tmp_path / "run")
    options = dict(config=config, paths=run.paths, accumulation=None, crs_project=None)

    assert build_standard_catchment(**options, backend=object(), unsupported_mode="ignore") is None
    with pytest.raises(ValueError, match="Unsupported catch_def"):
        build_standard_catchment(**options, backend=object())
