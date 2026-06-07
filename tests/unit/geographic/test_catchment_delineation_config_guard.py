"""Guardrail tests for ``CatchmentDelineation`` configuration and input validation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from rasterio.errors import RasterioIOError
from shapely.geometry import box

from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _write_synthetic_catchment(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(
        data={"id": [1]},
        geometry=[box(100.0, 100.0, 700.0, 700.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(path)


def test_geographic_config_rejects_missing_outlet_fields() -> None:
    """Validate per-variant required-field guardrails for outlet catchment definition."""
    with pytest.raises(ValueError, match="from_outlet_coord"):
        GeographicConfig(
            catchment={
                "catch_def": "from_outlet_coord",
                "dem_init_path": Path("dummy_dem.tif"),
                "snap_dist": 50,
                "buff_area": 20.0,
            },
        )


def test_catchment_delineation_missing_dem_file_raises(tmp_path: Path) -> None:
    """CatchmentDelineation should fail early when input DEM does not exist."""
    catchment_path = tmp_path / "inputs" / "catchment.shp"
    _write_synthetic_catchment(catchment_path)
    missing_dem = tmp_path / "inputs" / "missing_dem.tif"

    cfg = GeographicConfig(
        catchment={
            "catch_def": "from_polyg_shp",
            "dem_init_path": missing_dem,
            "polyg_shp_path": catchment_path,
            "buff_area": 20.0,
        },
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )
    initializing = SimpleNamespace(project_root=str(tmp_path / "case_missing_dem"))

    with pytest.raises(RasterioIOError):
        CatchmentDelineation(config=cfg, initializing=initializing)
