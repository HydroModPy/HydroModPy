"""Soil columns of the SAFRAN grid: catchment weight per cell and capacity classes from a raster.

Cells are 1000 m apart. The basin mean of the soil budget weighs each cell by the share of the
catchment polygon it holds. A capacity raster (mm) must cover every cell and be positive.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.soil_columns import capacity_classes, catchment_cell_weights

CRS = "EPSG:2154"


def catchment(x0, y0, x1, y1) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(x0, y0, x1, y1)], crs=CRS)


def cell_weights(polygon) -> np.ndarray:
    # Six cells in two rows of three, 1000 m apart.
    x, y = np.array([0.0, 1000.0, 2000.0]), np.array([0.0, 1000.0])
    return catchment_cell_weights(
        x, y, bbox=(-500.0, -500.0, 2500.0, 1500.0), catchment=polygon, crs=CRS
    )


WEIGHTS = [
    pytest.param(catchment(900, -100, 1100, 100), [0, 1, 0, 0, 0, 0], id="inside one cell"),
    pytest.param(
        catchment(250, -100, 1000, 100), [1 / 3, 2 / 3, 0, 0, 0, 0], id="two cells by area"
    ),
    pytest.param(None, [1 / 6] * 6, id="no polygon"),
    pytest.param(catchment(90000, 90000, 91000, 91000), [1 / 6] * 6, id="grid misses the polygon"),
]


@pytest.mark.parametrize(("polygon", "expected"), WEIGHTS)
def test_catchment_cell_weights(polygon, expected):
    assert cell_weights(polygon).tolist() == pytest.approx(expected)


def test_polygon_is_read_in_the_model_crs():
    frame = catchment(900, -100, 1100, 100).to_crs("EPSG:4326")

    assert cell_weights(frame)[1] == pytest.approx(1.0, abs=1e-6)


def capacity_raster(path: Path, data, bbox) -> LoadResult:
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=CRS,
        transform=from_origin(-500.0, 500.0, 25.0, 25.0),
    ) as dst:
        dst.write(data.astype("float32"), 1)
    record = FieldRecord(
        variable="soil_capacity", source="file", unit="mm", data=path, bbox=bbox, crs=CRS
    )
    return LoadResult(fields=[record])


def negative_pixel():
    data = np.full((40, 80), 150.0)
    data[10, 10] = -5.0
    return data


# Two cells in one row, 1000 m apart. A pixel is 25 m, so 40 x 80 pixels cover both cells.
REFUSALS = [
    pytest.param(
        np.full((40, 40), 150.0), "covers no part of the SAFRAN cell", id="second cell uncovered"
    ),
    pytest.param(negative_pixel(), "holds negative values", id="negative pixel"),
    pytest.param(np.zeros((40, 80)), "is 0 mm over every SAFRAN cell", id="zero mean"),
]


@pytest.mark.parametrize(("data", "match"), REFUSALS)
def test_refusals(tmp_path, data, match):
    bbox = (-500.0, -500.0, 1500.0, 500.0)
    soil_capacity = capacity_raster(tmp_path / "ru.tif", data, bbox)

    with pytest.raises(DataContractViolation, match=match):
        capacity_classes(
            soil_capacity, x=np.array([0.0, 1000.0]), y=np.array([0.0]), crs=CRS, bbox=bbox
        )
