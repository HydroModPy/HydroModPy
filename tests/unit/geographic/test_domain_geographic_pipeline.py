from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.geographic import GeographicConfig
from hydromodpy.geographic.core.domain_geographic_pipeline import (
    build_domain_geographic_context,
)
from hydromodpy.simulation.workspace import Workspace
from hydromodpy.simulation.workspace.config import WorkspaceConfig


def _write_dem(path: Path) -> None:
    transform = from_origin(1000.0, 2100.0, 50.0, 50.0)
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 3,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    values = np.array(
        [
            [10.0, 11.0, 12.0],
            [13.0, -9999.0, 15.0],
        ],
        dtype=np.float32,
    )
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(values, 1)


def test_build_domain_geographic_context_from_dem(tmp_path: Path):
    dem_path = tmp_path / "domain_dem.tif"
    _write_dem(dem_path)

    workspace = Workspace(
        WorkspaceConfig(
            catch_name="dem_case",
            out_dir_path=tmp_path / "results",
            data_path=tmp_path / "data",
        )
    )
    config = GeographicConfig(
        catch_def="dem",
        dem_init_path=dem_path,
        crs_project="EPSG:2154",
    )

    context = build_domain_geographic_context(
        config=config,
        workspace=workspace,
    )

    assert context.catch_def == "dem"
    assert context.zone_kind == "uniform"
    assert context.river_mesh_trace is None
    assert context.x_outlet is None
    assert context.y_outlet is None
    assert Path(context.watershed_box_buff_dem).exists()
    assert Path(context.watershed_shp).exists()
    assert Path(context.box_buff_shp).exists()

    np.testing.assert_allclose(
        context.surface_topo.as_array(),
        np.array(
            [
                [10.0, 11.0, 12.0],
                [13.0, -9999.0, 15.0],
            ],
            dtype=float,
        ),
    )
    assert context.catchment_area_km2 == pytest.approx((5 * 50.0 * 50.0) / 1_000_000.0)

    watershed_gdf = gpd.read_file(context.watershed_shp)
    assert float(watershed_gdf.geometry.area.sum() / 1_000_000.0) == pytest.approx(
        context.catchment_area_km2
    )


def test_build_domain_geographic_context_from_synthetic_mode(tmp_path: Path):
    workspace = Workspace(
        WorkspaceConfig(
            catch_name="synthetic_case",
            out_dir_path=tmp_path / "results",
            data_path=tmp_path / "data",
        )
    )
    config = GeographicConfig(
        source_mode="synthetic",
        synthetic={
            "case_id": "domain_synth",
            "grid": {
                "length_x": "100 m",
                "length_y": "100 m",
                "nx": 2,
                "ny": 2,
                "xmin": 100.0,
                "ymin": 200.0,
            },
            "topography": {
                "kind": "flat",
                "base_elevation": 20.0,
            },
        },
    )

    context = build_domain_geographic_context(
        config=config,
        workspace=workspace,
    )

    assert context.catch_def == "synthetic"
    assert context.zone_kind == "uniform"
    assert context.river_mesh_trace is None
    assert context.catchment_area_km2 == pytest.approx(0.01)
    assert Path(context.watershed_box_buff_dem).exists()
    assert Path(context.watershed_shp).exists()
    np.testing.assert_allclose(context.surface_topo.as_array(), np.full((2, 2), 20.0))
