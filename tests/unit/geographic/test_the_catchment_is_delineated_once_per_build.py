"""A build without notch or capture delineates the catchment once, on the one pipeline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic import catchment_delineation as delineation_module
from hydromodpy.spatial.geographic import pipeline as runtime_pipeline
from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.whitebox_double import FakeWhiteboxBackend


class _Locator:
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *args, **kwargs):
        return None


def _write_dem(path: Path) -> None:
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 10,
        "count": 1,
        "dtype": np.float32,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1000.0, 100.0, 100.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.arange(100, dtype=np.float32).reshape(10, 10), 1)


def test_one_build_delineates_the_catchment_once(tmp_path, monkeypatch) -> None:
    fake_backend = FakeWhiteboxBackend()
    monkeypatch.setattr(
        delineation_module, "resolve_delineation_backend", lambda backend=None: fake_backend
    )
    monkeypatch.setattr(delineation_module, "Nominatim", _Locator)
    delineations: list[object] = []
    delineate = runtime_pipeline.build_standard_catchment

    def _counted(**kwargs):
        delineations.append(kwargs["paths"].watershed_shp)
        return delineate(**kwargs)

    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", _counted)
    dem = tmp_path / "dem.tif"
    _write_dem(dem)
    config = GeographicConfig(
        catchment={
            "catch_def": "from_outlet_coord",
            "dem_init_path": dem,
            "x_outlet": 450.0,
            "y_outlet": 450.0,
            "snap_dist": 100,
            "buff_area": 20.0,
        },
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )

    geographic = CatchmentDelineation(config, SimpleNamespace(project_root=str(tmp_path / "run")))
    geographic.get_domain_geographic_context()

    assert len(delineations) == 1
    assert float(geographic.catch_area) > 0.0
