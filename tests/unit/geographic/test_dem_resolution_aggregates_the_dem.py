"""``[geographic.catchment].dem_resolution`` aggregates the DEM before any delineation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic.core.dem_aggregation import aggregate_dem
from hydromodpy.spatial.geographic.core.pipeline_steps import prepare_geographic_run
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint

NODATA = -9999.0


def _write_dem(path: Path, values: np.ndarray, *, cell: float = 100.0) -> None:
    """Write a north-up EPSG:2154 GeoTIFF whose upper-left corner is (0, 1000)."""
    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": np.float32,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1000.0, cell, cell),
        "nodata": NODATA,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(values.astype(np.float32), 1)


def _outlet_config(dem_path: Path, **catchment: object) -> GeographicConfig:
    return GeographicConfig.model_validate(
        {
            "catchment": {
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem_path,
                "x_outlet": 450.0,
                "y_outlet": 550.0,
                "snap_dist": "150 m",
                "buff_area": "10%",
                **catchment,
            },
            "crs_project": "EPSG:2154",
        }
    )


def test_each_coarse_cell_is_the_mean_of_the_fine_pixels_it_covers(tmp_path: Path) -> None:
    values = np.arange(100, dtype=float).reshape(10, 10)
    values[1, 1] = NODATA
    dem = tmp_path / "dem.tif"
    _write_dem(dem, values)

    out = aggregate_dem(dem, tmp_path / "dem_300m.tif", resolution_m=300.0)

    with rasterio.open(out) as src:
        assert (src.height, src.width) == (4, 4)
        assert src.transform.a == 300.0 and src.transform.e == -300.0
        assert (src.transform.c, src.transform.f) == (0.0, 1000.0)
        assert src.crs.to_epsg() == 2154
        assert src.nodata == NODATA
        coarse = src.read(1)
    block = values[:3, :3]
    kept = block[block != NODATA]
    assert coarse[0, 0] == pytest.approx(kept.mean(), rel=1e-6)
    assert coarse[1, 1] == pytest.approx(values[3:6, 3:6].mean(), rel=1e-6)
    # The last row and column are partial blocks: one fine row, one fine column.
    assert coarse[3, 3] == pytest.approx(values[9, 9], rel=1e-6)
    assert coarse[3, 0] == pytest.approx(values[9, :3].mean(), rel=1e-6)


def test_a_cell_size_finer_than_the_dem_is_refused(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    _write_dem(dem, np.ones((10, 10)))
    with pytest.raises(ValueError, match="finer than the 100 m pixel"):
        aggregate_dem(dem, tmp_path / "out.tif", resolution_m=50.0)


def test_prepare_geographic_run_reads_the_aggregated_dem_when_asked(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    _write_dem(dem, np.arange(100, dtype=float).reshape(10, 10))

    native = prepare_geographic_run(config=_outlet_config(dem), out_dir_path=tmp_path / "a")
    assert native.dem_res == 100.0
    assert native.dem_init_path == str(dem)

    coarse = prepare_geographic_run(
        config=_outlet_config(dem, dem_resolution="300 m"), out_dir_path=tmp_path / "b"
    )
    assert coarse.dem_res == 300.0
    assert Path(coarse.dem_init_path).name == "dem_init_300m.tif"
    assert Path(coarse.dem_init_path).is_relative_to(tmp_path / "b")
    with rasterio.open(coarse.dem_init_path) as src:
        assert (src.height, src.width) == (4, 4)

    same = prepare_geographic_run(
        config=_outlet_config(dem, dem_resolution=100.0), out_dir_path=tmp_path / "c"
    )
    assert same.dem_init_path == str(dem)


def test_the_geographic_cache_sees_the_cell_size(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    _write_dem(dem, np.ones((10, 10)))
    assert _geographic_cache_fingerprint(_outlet_config(dem)) != _geographic_cache_fingerprint(
        _outlet_config(dem, dem_resolution="300 m")
    )


def test_a_zero_or_negative_cell_size_is_refused_when_the_file_loads(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="positive length"):
        _outlet_config(tmp_path / "dem.tif", dem_resolution=0.0)


def test_txt_keeps_cell_size_as_its_only_grid(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="say the grid twice"):
        GeographicConfig.model_validate(
            {
                "catchment": {
                    "catch_def": "txt",
                    "dem_init_path": tmp_path / "points.txt",
                    "cell_size": "25 m",
                    "dem_resolution": "75 m",
                },
                "crs_project": "EPSG:2154",
            }
        )
