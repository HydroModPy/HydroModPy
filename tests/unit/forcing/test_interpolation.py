"""Nearest, linear and inverse-distance interpolation on ``(nrow, ncol)`` grids of centers.

:mod:`hydromodpy.spatial.forcing.interpolation` reads a raster or scattered stations.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hydromodpy.spatial.forcing.interpolation import (
    interpolate_points_to_grid,
    interpolate_stack_to_grid,
    interpolate_to_grid,
)
from tests._helpers import forcing_cases as fc

pytestmark = pytest.mark.fast


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """A recharge that rises to the east and to the north."""
    return 1.0 + 0.02 * x + 0.01 * y


def _targets(nrow: int = 3, ncol: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Centers of 10 m cells inside the 0-40 m square, as ``(nrow, ncol)`` arrays."""
    cells = fc.centres(nrow, ncol).reshape(nrow, ncol, 2)
    return cells[..., 0], cells[..., 1]


@pytest.mark.parametrize(
    "interpolate",
    [
        lambda: interpolate_to_grid(np.zeros((2, 2)), np.arange(2.0), np.arange(2.0), *_targets(2, 2), 2, 2, "area"),
        lambda: interpolate_points_to_grid(np.zeros(2), np.zeros(2), np.zeros(2), *_targets(2, 2), 2, 2, "area"),
        lambda: interpolate_stack_to_grid(
            np.zeros((1, 2, 2)), np.arange(2.0), np.arange(2.0), *_targets(2, 2), 2, 2, "area"),
    ],
    ids=["raster", "stations", "stack"],
)  # fmt: skip
def test_a_centre_grid_refuses_area(interpolate):
    with pytest.raises(ValueError, match="needs the cell polygons"):
        interpolate()


@pytest.mark.parametrize("method", ["nearest", "linear", "idw"])
def test_a_uniform_raster_stays_uniform_under_every_method(method):
    result = fc.fields_on_cells([fc.static_field(3, 4, 5.0)], 3, 4, method=method)
    assert result[0].shape == (12,)
    np.testing.assert_allclose(result[0], 5.0 * fc.MM_DAY_TO_M_S, rtol=1e-4)


def test_linear_reproduces_a_plane_read_on_a_finer_raster_slice_by_slice():
    x = np.arange(-2.5, 45.0, 5.0)  # 5 m pixels over the cells and a margin
    y = np.arange(-2.5, 35.0, 5.0)[::-1]
    raster = _plane(x[None, :], y[:, None])
    target_x, target_y = _targets()

    result = interpolate_to_grid(raster, x, y, target_x, target_y, 3, 4, "linear")
    stack = interpolate_stack_to_grid(
        np.stack([raster, 3.0 * raster]), x, y, target_x, target_y, 3, 4, "linear"
    )

    np.testing.assert_allclose(result, _plane(target_x, target_y), rtol=1e-10)
    np.testing.assert_allclose(stack[0], _plane(target_x, target_y), rtol=1e-10)
    np.testing.assert_allclose(stack[1], 3.0 * _plane(target_x, target_y), rtol=1e-10)


def test_linear_reproduces_a_plane_between_stations_and_takes_the_nearest_outside():
    # Three stations span a triangle over the west of the cells; the east ones lie outside.
    xs, ys = np.array([0.0, 25.0, 0.0]), np.array([0.0, 0.0, 30.0])
    target_x, target_y = _targets()

    result, nearest = (
        interpolate_points_to_grid(xs, ys, _plane(xs, ys), target_x, target_y, 3, 4, method)
        for method in ("linear", "nearest")
    )

    inside = target_x / 25.0 + target_y / 30.0 < 1.0
    assert inside.any() and (~inside).any()
    np.testing.assert_allclose(result[inside], _plane(target_x, target_y)[inside], rtol=1e-10)
    np.testing.assert_array_equal(result[~inside], nearest[~inside])


def test_idw_rises_between_two_stations_and_takes_the_value_on_a_station_without_a_warning():
    west, far_east, near_east = (fc.station(*args) for args in (("W", 5.0, 5.0, 10.0), ("E", 45.0, 5.0, 20.0), ("E", 25.0, 5.0, 20.0)))  # fmt: skip

    rates = fc.points_on_cells([west, far_east], 1, 5, method="idw")[0]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        on_station = fc.points_on_cells([west, near_east], 1, 3, method="idw")[0]

    assert rates.shape == (5,)
    assert rates[0] < rates[-1]
    assert np.all(rates >= 10.0 * fc.MM_DAY_TO_M_S * 0.99)
    assert np.all(rates <= 20.0 * fc.MM_DAY_TO_M_S * 1.01)
    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []
    assert on_station.shape == (3,)
    assert on_station[0] == pytest.approx(10.0 * fc.MM_DAY_TO_M_S)
    assert on_station[-1] == pytest.approx(20.0 * fc.MM_DAY_TO_M_S)


@pytest.mark.parametrize(
    ("stations", "targets", "expected"),
    [([[0.0, 7.0, 10.0], [20.0, 7.0, 20.0]], ([[10.0]], [[3.0]]), 15.0), ([[12.0, 3.0, 7.0]], _targets(), 7.0)],
    ids=["halfway-between-two-gives-their-mean", "one-station-gives-its-value-everywhere"],
)  # fmt: skip
def test_idw_of_equidistant_or_single_stations(stations, targets, expected):
    xyv = np.asarray(stations)
    target_x, target_y = (np.asarray(axis) for axis in targets)
    result = interpolate_points_to_grid(*xyv.T, target_x, target_y, *target_x.shape, "idw")
    np.testing.assert_allclose(result, expected, rtol=1e-12)


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
    result = interpolate_points_to_grid(*xyv.T, *_targets(), 3, 4, "idw", idw_power=power)
    tolerance = 1e-9 * max(1.0, float(np.abs(xyv[:, 2]).max()))
    assert np.all(result >= xyv[:, 2].min() - tolerance)
    assert np.all(result <= xyv[:, 2].max() + tolerance)


def test_two_dimensional_source_coordinates_are_read_as_pixel_centres():
    x, y = np.array([5.0, 15.0, 25.0, 35.0]), np.array([25.0, 15.0, 5.0])
    raster = _plane(x[None, :], y[:, None])
    xx, yy = np.meshgrid(x, y, indexing="xy")
    target_x, target_y = _targets()
    shifted = (target_x + 1.0, target_y - 1.0)

    from_axes = interpolate_to_grid(raster, x, y, *shifted, 3, 4, "nearest")
    from_grids = interpolate_to_grid(raster, xx, yy, *shifted, 3, 4, "nearest")

    np.testing.assert_array_equal(from_grids, from_axes)
    np.testing.assert_array_equal(from_axes, raster)


def test_a_stack_on_the_target_grid_comes_back_unchanged_and_an_empty_one_empty():
    target_x, target_y = _targets()
    stack = np.stack([_plane(target_x, target_y), 2.0 * _plane(target_x, target_y)])

    result = interpolate_stack_to_grid(
        stack, target_x[0, :], target_y[:, 0], target_x, target_y, 3, 4, "nearest"
    )
    empty = interpolate_stack_to_grid(np.zeros((0, 2, 3)), np.arange(3.0), np.arange(2.0), *_targets(), 3, 4)  # fmt: skip

    np.testing.assert_array_equal(result, stack)
    assert empty.shape == (0, 3, 4)


def test_a_stack_whose_nodata_moves_is_read_slice_by_slice():
    x, y = np.array([0.0, 20.0, 40.0]), np.array([30.0, 0.0])
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


# Values laid out like the targets on an x axis and a y grid: no pixel can be placed.
_X4 = np.array([5.0, 15.0, 25.0, 35.0])
_YGRID = np.meshgrid(_X4, np.array([25.0, 15.0, 5.0]))[1]
_VALUES = np.arange(12.0).reshape(3, 4)


@pytest.mark.parametrize(
    ("interpolate", "expected"),
    [
        (lambda: interpolate_to_grid(_VALUES, _X4, _YGRID, *_targets(), 3, 4), 5.5),
        (lambda: interpolate_stack_to_grid(_VALUES[None], _X4, _YGRID, *_targets(), 3, 4)[0], 5.5),
        (lambda: interpolate_to_grid(np.full((2, 2), np.nan), np.arange(2.0), np.arange(2.0), *_targets(), 3, 4), 0.0),
        (lambda: interpolate_points_to_grid(np.zeros(2), np.zeros(2), np.full(2, np.nan), *_targets(), 3, 4), 0.0),
    ],
    ids=["mixed-axes-raster", "mixed-axes-stack", "no-finite-raster", "no-finite-station"],
)  # fmt: skip
def test_a_source_that_places_no_pixel_gives_its_mean_or_zero(interpolate, expected):
    np.testing.assert_array_equal(interpolate(), expected)
