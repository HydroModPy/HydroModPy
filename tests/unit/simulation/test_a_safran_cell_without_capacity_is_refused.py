"""Every way a soil capacity raster can fail its contract with the SAFRAN grid.

``capacity_classes`` reads ``[data.soil_capacity]`` on its own (spec section
4.4, guards X16, X17, X20): a raster that misses a cell, holds a negative
value or averages to zero raises the exact class and text of that guard.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.simulation.soil_recharge import capacity_classes

_CRS = "EPSG:2154"
_X = np.array([0.0, 1000.0])  # two SAFRAN cells, one row
_Y = np.array([0.0])
_BBOX = (-500.0, -500.0, 1500.0, 500.0)


def _write_raster(path: Path, data: np.ndarray, *, west: float, north: float) -> LoadResult:
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=_CRS,
        transform=from_origin(west, north, 25.0, 25.0),
    ) as dst:
        dst.write(data.astype("float32"), 1)
    record = FieldRecord(
        variable="soil_capacity",
        source="custom",
        unit="mm",
        data=path,
        bbox=_BBOX,
        crs=_CRS,
    )
    return LoadResult(fields=[record])


def test_a_cell_the_raster_never_covers_is_refused(tmp_path: Path) -> None:
    # 40x40 px at 25 m covers only [-500, 500]: the first cell, never the second.
    data = np.full((40, 40), 150.0)
    soil_capacity = _write_raster(tmp_path / "ru.tif", data, west=-500.0, north=500.0)

    with pytest.raises(DataContractViolation, match="covers no part of the SAFRAN cell"):
        capacity_classes(soil_capacity, x=_X, y=_Y, crs=_CRS, bbox=_BBOX)


def test_a_negative_pixel_is_refused(tmp_path: Path) -> None:
    data = np.full((40, 80), 150.0)
    data[10, 10] = -5.0
    soil_capacity = _write_raster(tmp_path / "ru.tif", data, west=-500.0, north=500.0)

    with pytest.raises(DataContractViolation, match="holds negative values"):
        capacity_classes(soil_capacity, x=_X, y=_Y, crs=_CRS, bbox=_BBOX)


def test_a_raster_that_averages_to_zero_is_refused(tmp_path: Path) -> None:
    data = np.zeros((40, 80))
    soil_capacity = _write_raster(tmp_path / "ru.tif", data, west=-500.0, north=500.0)

    with pytest.raises(DataContractViolation, match="is 0 mm over every SAFRAN cell"):
        capacity_classes(soil_capacity, x=_X, y=_Y, crs=_CRS, bbox=_BBOX)
