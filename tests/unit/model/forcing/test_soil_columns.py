"""Soil columns of the SAFRAN grid: catchment weight per cell and capacity classes from a raster.

Cells are 1000 m apart. The basin mean of the soil budget weighs each cell by the share of the
catchment polygon it holds. A capacity raster (mm) must cover every cell and be positive. A
sealed share or a curve number raster gives each cell its mean inside the catchment.
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
from hydromodpy.model.forcing.soil_columns import (
    SoilColumns,
    capacity_classes,
    catchment_cell_means,
    catchment_cell_weights,
    with_surface_maps,
)

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


def sealed_share() -> np.ndarray:
    # Two cells: the left half of the first cell is a town, sealed at 1.
    data = np.full((40, 80), 0.02)
    data[:, :20] = 1.0
    return data


def cell_means(tmp_path, data, polygon, name="impervious") -> np.ndarray:
    bbox = (-500.0, -500.0, 1500.0, 500.0)
    raster = capacity_raster(tmp_path / f"{name}.tif", data, bbox)
    return catchment_cell_means(
        raster.fields[0],
        name=name,
        x=np.array([0.0, 1000.0]),
        y=np.array([0.0]),
        crs=CRS,
        bbox=bbox,
        catchment=polygon,
    )


MEANS = [
    pytest.param(None, [0.51, 0.02], id="no polygon, the whole cell"),
    pytest.param(catchment(0, -500, 1500, 500), [0.02, 0.02], id="town outside the catchment"),
    pytest.param(catchment(500, -500, 1500, 500), [0.02, 0.02], id="cell off the catchment"),
]


@pytest.mark.parametrize(("polygon", "expected"), MEANS)
def test_catchment_cell_means(tmp_path, polygon, expected):
    assert cell_means(tmp_path, sealed_share(), polygon).tolist() == pytest.approx(expected)


def test_a_cell_the_catchment_misses_takes_the_catchment_mean(tmp_path):
    data = np.full((40, 80), 0.02)
    data[:, 40:] = 0.10

    means = cell_means(tmp_path, data, catchment(-500, -500, 400, 500))

    assert means.tolist() == pytest.approx([0.02, 0.02])


MEAN_REFUSALS = [
    pytest.param("impervious", 100.0 * sealed_share(), "outside 0 to 0.95", id="percent"),
    pytest.param(
        "curve_number", np.full((40, 80), 10.0), "outside 30 to 98", id="low curve number"
    ),
]


@pytest.mark.parametrize(("name", "data", "match"), MEAN_REFUSALS)
def test_cell_mean_refusals(tmp_path, name, data, match):
    with pytest.raises(DataContractViolation, match=match):
        cell_means(tmp_path, data, None, name=name)


def test_a_raster_off_the_catchment_is_refused(tmp_path):
    with pytest.raises(DataContractViolation, match="no pixel inside the catchment"):
        cell_means(tmp_path, sealed_share(), catchment(5000, 5000, 6000, 6000))


def test_with_surface_maps_hands_each_column_its_cell_value():
    columns = SoilColumns(
        cell_index=np.array([0, 0, 1]),
        class_index=np.array([0, 1, 0]),
        x=np.zeros(3),
        y=np.zeros(3),
        ru_shape=np.ones(3),
        cell_fraction=np.array([0.5, 0.5, 1.0]),
        basin_weight=np.array([0.25, 0.25, 0.5]),
    )

    mapped = with_surface_maps(columns, impervious=np.array([0.1, 0.3]), curve_number=None)

    assert mapped.impervious.tolist() == [0.1, 0.1, 0.3]
    assert mapped.curve_number is None
