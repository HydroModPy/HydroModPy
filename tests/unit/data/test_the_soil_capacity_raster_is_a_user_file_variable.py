"""Soil capacity (RU raster) config and manager.

Mirrors the substratum tests: ``soil_capacity`` is another custom-only raster
variable built on ``RasterFileManager``, in mm instead of m.
"""

from __future__ import annotations

import typing
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.contracts import FieldRecord
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.variables.soil_capacity.config import (
    CustomSoilCapacitySource,
    SoilCapacityConfig,
)
from hydromodpy.data.variables.soil_capacity.manager import SoilCapacityManager


def _write_geotiff(path: Path, *, crs: str | None = "EPSG:2154", value: float = 150.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.full((3, 4), value, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def test_config_refuses_two_sources(tmp_path: Path) -> None:
    a = _write_geotiff(tmp_path / "a.tif")
    b = _write_geotiff(tmp_path / "b.tif")
    with pytest.raises(ValidationError):
        SoilCapacityConfig.model_validate(
            {
                "sources": [
                    {"source": "custom", "path": str(a)},
                    {"source": "custom", "path": str(b)},
                ]
            }
        )


def test_the_path_field_carries_the_soil_capacity_role() -> None:
    role = None
    for meta in CustomSoilCapacitySource.model_fields["path"].metadata:
        if isinstance(meta, InputFile):
            role = meta.role
    assert role == "soil_capacity"


def test_manager_reads_a_tiny_geotiff(tmp_path: Path) -> None:
    src = _write_geotiff(tmp_path / "ru.tif")
    config = SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=src)])
    manager = SoilCapacityManager(config=config, catalog=None, data_dir=tmp_path)

    result = manager.load()

    assert len(result.fields) == 1
    record = result.fields[0]
    assert isinstance(record, FieldRecord)
    assert record.variable == "soil_capacity"


def test_manager_internal_unit_is_millimetres() -> None:
    assert SoilCapacityManager.INTERNAL_UNIT == "mm"


def test_manager_labels_the_record_in_millimetres(tmp_path: Path) -> None:
    src = _write_geotiff(tmp_path / "ru.tif")
    config = SoilCapacityConfig(sources=[CustomSoilCapacitySource(path=src)])
    manager = SoilCapacityManager(config=config, catalog=None, data_dir=tmp_path)

    record = manager.load().fields[0]

    assert record.unit == "mm"


def test_the_variable_spec_never_applies_the_simulation_window() -> None:
    assert VARIABLE_SPECS["soil_capacity"].apply_simulation_window is False


def test_the_source_literal_only_accepts_custom() -> None:
    annotation = CustomSoilCapacitySource.model_fields["source"].annotation
    assert typing.get_args(annotation) == ("custom",)
