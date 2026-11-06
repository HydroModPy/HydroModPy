"""The basin mean of the soil budget weighs each cell by the catchment it holds.

The printed budget is read against the gauge, so a cell the catchment barely
touches must not count like the one that holds it.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.simulation.soil.columns import catchment_cell_weights

_X = np.array([0.0, 1000.0, 2000.0])
_Y = np.array([0.0, 1000.0])
_BBOX = (-500.0, -500.0, 2500.0, 1500.0)


def _catchment(x0: float, y0: float, x1: float, y1: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[box(x0, y0, x1, y1)], crs="EPSG:2154")


def _weights(catchment: gpd.GeoDataFrame | None) -> np.ndarray:
    return catchment_cell_weights(_X, _Y, bbox=_BBOX, catchment=catchment, crs="EPSG:2154")


def test_a_catchment_inside_one_cell_gives_it_all_the_weight() -> None:
    weights = _weights(_catchment(900.0, -100.0, 1100.0, 100.0))
    assert weights.tolist() == pytest.approx([0.0, 1.0, 0.0, 0.0, 0.0, 0.0])


def test_two_cells_share_the_catchment_by_area() -> None:
    weights = _weights(_catchment(250.0, -100.0, 1000.0, 100.0))
    assert weights.tolist() == pytest.approx([1 / 3, 2 / 3, 0.0, 0.0, 0.0, 0.0])


def test_the_polygon_is_read_in_the_crs_of_the_model() -> None:
    frame = _catchment(900.0, -100.0, 1100.0, 100.0).to_crs("EPSG:4326")
    weights = _weights(frame)
    assert weights[1] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "catchment",
    [None, _catchment(90000.0, 90000.0, 91000.0, 91000.0)],
    ids=["no polygon", "a grid that misses it"],
)
def test_without_a_catchment_to_read_the_cells_count_the_same(
    catchment: gpd.GeoDataFrame | None,
) -> None:
    assert _weights(catchment).tolist() == pytest.approx([1 / 6] * 6)
