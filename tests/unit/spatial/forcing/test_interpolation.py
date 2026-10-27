"""Nearest, linear and inverse-distance interpolation on cell centres.

:mod:`hydromodpy.spatial.forcing.interpolation` reads a raster or
scattered stations and gives one value per target centre. Its targets are
``(nrow, ncol)`` grids of centres; the forcing passes a column of cells.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.forcing.cells import (
    discretize_fields_on_cells,
    discretize_points_on_cells,
)
from hydromodpy.spatial.forcing.interpolation import (
    interpolate_points_to_grid,
    interpolate_stack_to_grid,
    interpolate_to_grid,
)
from tests.unit.spatial.forcing.forcing_cases import (
    MM_DAY_TO_M_S,
    centres,
    static_field,
    station,
)

pytestmark = pytest.mark.fast


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """A recharge that rises to the east and to the north."""
    return 1.0 + 0.02 * x + 0.01 * y


def _targets(nrow: int = 3, ncol: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Centres of 10 m cells inside the 0-40 m square, as ``(nrow, ncol)`` arrays."""
    cells = centres(nrow, ncol).reshape(nrow, ncol, 2)
    return cells[..., 0], cells[..., 1]


@pytest.mark.parametrize(
    "interpolate",
    [
        lambda: interpolate_to_grid(
            np.zeros((2, 2)), np.arange(2.0), np.arange(2.0), *_targets(2, 2), 2, 2, "area"
        ),
        lambda: interpolate_points_to_grid(
            np.zeros(2), np.zeros(2), np.zeros(2), *_targets(2, 2), 2, 2, "area"
        ),
        lambda: interpolate_stack_to_grid(
            np.zeros((1, 2, 2)), np.arange(2.0), np.arange(2.0), *_targets(2, 2), 2, 2, "area"
        ),
    ],
    ids=["raster", "stations", "stack"],
)
def test_a_centre_grid_refuses_area(interpolate):
    with pytest.raises(ValueError, match="needs the cell polygons"):
        interpolate()


@pytest.mark.parametrize("method", ["nearest", "linear", "idw"])
def test_a_uniform_raster_stays_uniform_under_every_method(method):
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[static_field(3, 4, 5.0)]),
        centers=centres(3, 4),
        nper=1,
        method=method,
    )

    assert result[0].shape == (12,)
    np.testing.assert_allclose(result[0], 5.0 * MM_DAY_TO_M_S, rtol=1e-4)


def _finer_raster() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """5 m pixels of the plane over the cells and a margin."""
    x = np.arange(-2.5, 45.0, 5.0)
    y = np.arange(-2.5, 35.0, 5.0)[::-1]
    return _plane(x[None, :], y[:, None]), x, y


def test_linear_reproduces_a_plane_read_on_a_finer_raster():
    raster, x, y = _finer_raster()
    target_x, target_y = _targets()

    result = interpolate_to_grid(raster, x, y, target_x, target_y, 3, 4, "linear")

    np.testing.assert_allclose(result, _plane(target_x, target_y), rtol=1e-10)


def test_linear_reproduces_the_plane_of_every_slice_of_a_stack():
    raster, x, y = _finer_raster()
    target_x, target_y = _targets()

    result = interpolate_stack_to_grid(
        np.stack([raster, 3.0 * raster]), x, y, target_x, target_y, 3, 4, "linear"
    )

    np.testing.assert_allclose(result[0], _plane(target_x, target_y), rtol=1e-10)
    np.testing.assert_allclose(result[1], 3.0 * _plane(target_x, target_y), rtol=1e-10)


def test_linear_reproduces_a_plane_between_stations_and_takes_the_nearest_outside():
    # Three stations span a triangle over the west of the cells; the east ones lie outside.
    stations = np.array([[0.0, 0.0], [25.0, 0.0], [0.0, 30.0]])
    target_x, target_y = _targets()

    result = interpolate_points_to_grid(
        stations[:, 0], stations[:, 1], _plane(stations[:, 0], stations[:, 1]),
        target_x, target_y, 3, 4, "linear",
    )  # fmt: skip

    inside = target_x / 25.0 + target_y / 30.0 < 1.0
    assert inside.any() and (~inside).any()
    np.testing.assert_allclose(result[inside], _plane(target_x, target_y)[inside], rtol=1e-10)
    nearest = interpolate_points_to_grid(
        stations[:, 0], stations[:, 1], _plane(stations[:, 0], stations[:, 1]),
        target_x, target_y, 3, 4, "nearest",
    )  # fmt: skip
    np.testing.assert_array_equal(result[~inside], nearest[~inside])


def test_between_two_stations_idw_rises_from_the_lower_to_the_higher():
    west = station("W", 5.0, 5.0, 10.0)
    east = station("E", 45.0, 5.0, 20.0)

    result = discretize_points_on_cells(
        load_result=LoadResult(points=[west, east]), centers=centres(1, 5), nper=1, method="idw"
    )

    rates = result[0]
    assert rates.shape == (5,)
    assert rates[0] < rates[-1]
    assert np.all(rates >= 10.0 * MM_DAY_TO_M_S * 0.99)
    assert np.all(rates <= 20.0 * MM_DAY_TO_M_S * 1.01)


def test_idw_on_a_station_takes_its_value_without_a_warning():
    west = station("W", 5.0, 5.0, 10.0)
    east = station("E", 25.0, 5.0, 20.0)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        result = discretize_points_on_cells(
            load_result=LoadResult(points=[west, east]), centers=centres(1, 3), nper=1, method="idw"
        )

    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []
    assert result[0].shape == (3,)
    assert result[0][0] == pytest.approx(10.0 * MM_DAY_TO_M_S)
    assert result[0][-1] == pytest.approx(20.0 * MM_DAY_TO_M_S)


def test_idw_halfway_between_two_stations_gives_their_mean():
    result = interpolate_points_to_grid(
        np.array([0.0, 20.0]), np.array([7.0, 7.0]), np.array([10.0, 20.0]),
        np.array([[10.0]]), np.array([[3.0]]), 1, 1, "idw",
    )  # fmt: skip

    assert result[0, 0] == pytest.approx(15.0)


def test_idw_from_one_station_gives_its_value_everywhere():
    target_x, target_y = _targets()

    result = interpolate_points_to_grid(
        np.array([12.0]), np.array([3.0]), np.array([7.0]), target_x, target_y, 3, 4, "idw"
    )

    np.testing.assert_allclose(result, 7.0, rtol=1e-12)


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    stations=st.lists(
        st.tuples(st.floats(-50.0, 90.0), st.floats(-50.0, 80.0), st.floats(0.0, 30.0)),
        min_size=1,
        max_size=20,
    ),
    power=st.floats(0.5, 4.0),
)
def test_idw_stays_between_the_lowest_and_the_highest_station(stations, power):
    xyv = np.asarray(stations, dtype=float)
    target_x, target_y = _targets()

    result = interpolate_points_to_grid(
        xyv[:, 0], xyv[:, 1], xyv[:, 2], target_x, target_y, 3, 4, "idw", idw_power=power
    )

    tolerance = 1e-9 * max(1.0, float(np.abs(xyv[:, 2]).max()))
    assert np.all(result >= xyv[:, 2].min() - tolerance)
    assert np.all(result <= xyv[:, 2].max() + tolerance)


def test_two_dimensional_source_coordinates_are_read_as_pixel_centres():
    x = np.array([5.0, 15.0, 25.0, 35.0])
    y = np.array([25.0, 15.0, 5.0])
    raster = _plane(x[None, :], y[:, None])
    xx, yy = np.meshgrid(x, y, indexing="xy")
    target_x, target_y = _targets()
    shifted = (target_x + 1.0, target_y - 1.0)

    from_axes = interpolate_to_grid(raster, x, y, *shifted, 3, 4, "nearest")
    from_grids = interpolate_to_grid(raster, xx, yy, *shifted, 3, 4, "nearest")

    np.testing.assert_array_equal(from_grids, from_axes)
    np.testing.assert_array_equal(from_axes, raster)


def test_a_stack_on_the_target_grid_comes_back_unchanged():
    target_x, target_y = _targets()
    stack = np.stack([_plane(target_x, target_y), 2.0 * _plane(target_x, target_y)])

    result = interpolate_stack_to_grid(
        stack, target_x[0, :], target_y[:, 0], target_x, target_y, 3, 4, "nearest"
    )

    np.testing.assert_array_equal(result, stack)


def test_a_stack_whose_nodata_moves_is_read_slice_by_slice():
    x = np.array([0.0, 20.0, 40.0])
    y = np.array([30.0, 0.0])
    first = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    second = 10.0 * first
    second[0, 0] = np.nan
    target_x, target_y = _targets()

    result = interpolate_stack_to_grid(np.stack([first, second]), x, y, target_x, target_y, 3, 4)

    for index, slice_2d in enumerate((first, second)):
        alone = interpolate_to_grid(slice_2d, x, y, target_x, target_y, 3, 4)
        np.testing.assert_array_equal(result[index], alone)
    assert np.all(np.isfinite(result[1]))
    assert not np.any(result[1] == 10.0)


def test_an_empty_stack_gives_an_empty_result():
    result = interpolate_stack_to_grid(
        np.zeros((0, 2, 3)), np.arange(3.0), np.arange(2.0), *_targets(), 3, 4
    )

    assert result.shape == (0, 3, 4)


@pytest.mark.parametrize(
    "interpolate",
    [
        lambda x, y, values: interpolate_to_grid(values, x, y, *_targets(), 3, 4),
        lambda x, y, values: interpolate_stack_to_grid(values[None], x, y, *_targets(), 3, 4)[0],
    ],
    ids=["raster", "stack"],
)
def test_source_axes_of_mixed_dimensions_fall_back_to_the_mean(interpolate):
    # Values laid out like the targets, an x axis and a y grid: no pixel can be placed.
    x = np.array([5.0, 15.0, 25.0, 35.0])
    y = np.meshgrid(x, np.array([25.0, 15.0, 5.0]))[1]
    values = np.arange(12.0).reshape(3, 4)

    np.testing.assert_array_equal(interpolate(x, y, values), 5.5)


@pytest.mark.parametrize(
    "interpolate",
    [
        lambda: interpolate_to_grid(
            np.full((2, 2), np.nan), np.arange(2.0), np.arange(2.0), *_targets(), 3, 4
        ),
        lambda: interpolate_points_to_grid(
            np.zeros(2), np.zeros(2), np.full(2, np.nan), *_targets(), 3, 4
        ),
    ],
    ids=["raster", "stations"],
)
def test_a_source_without_a_finite_value_gives_zero(interpolate):
    np.testing.assert_array_equal(interpolate(), 0.0)
