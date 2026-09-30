"""A soil capacity raster without a soil reservoir would never be read.

``[data.soil_capacity]`` spreads the ``ru`` of
``[flow.sinks_sources.recharge.soil]`` over classes: without that section the
raster has nothing to spread and would be loaded for no reader.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.variables.soil_capacity.config import (
    CustomSoilCapacitySource,
    SoilCapacityConfig,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _write_geotiff(path: Path) -> Path:
    data = np.full((3, 4), 150.0, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def _base_kwargs(tmp_path: Path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


def test_a_capacity_map_without_a_soil_section_is_rejected(tmp_path: Path) -> None:
    raster = _write_geotiff(tmp_path / "ru.tif")
    data = DataManagersConfig(
        soil_capacity=SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=raster)])
    )

    with pytest.raises(ValidationError, match=r"\[data.soil_capacity\]"):
        HydroModPyConfig(**_base_kwargs(tmp_path), data=data)


def test_a_capacity_map_without_a_soil_section_names_the_fix(tmp_path: Path) -> None:
    raster = _write_geotiff(tmp_path / "ru.tif")
    data = DataManagersConfig(
        soil_capacity=SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=raster)])
    )

    with pytest.raises(ValidationError) as excinfo:
        HydroModPyConfig(**_base_kwargs(tmp_path), data=data)

    assert "declare the soil section, or remove [data.soil_capacity]" in str(excinfo.value)
