"""Water table and budget flux helpers: elevation and depth in m, flux per area in m/s."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from hydromodpy.core.budget.flux import seepage_mask
from hydromodpy.results.derive.derived import (
    budget_flux_per_area,
    watertable_depth,
    watertable_elevation,
)

TOP = np.array([10.0, 10.0, 10.0])  # m
HEAD = np.array([8.0, 11.0, 9.5])  # m, the second cell is above the ground

ELEVATIONS = [
    pytest.param(HEAD, TOP, [8.0, 11.0, 9.5], id="head is not clipped"),
    pytest.param(
        np.array([[np.nan, 5.0], [3.0, 4.0]]),
        np.array([10.0, 10.0]),
        [3.0, 5.0],
        id="uppermost saturated layer",
    ),
]


@pytest.mark.parametrize(("head", "top", "expected"), ELEVATIONS)
def test_watertable_elevation(head, top, expected):
    np.testing.assert_array_equal(watertable_elevation(head, top), expected)


def test_watertable_elevation_xarray():
    top = xr.DataArray(TOP, dims="face")
    head = xr.DataArray(HEAD, dims="face")

    out = watertable_elevation(head, top)

    assert isinstance(out, xr.DataArray)
    np.testing.assert_array_equal(out.values, HEAD)
    assert out.attrs["units"] == "m"


def test_watertable_depth_is_not_negative():
    np.testing.assert_array_equal(watertable_depth(HEAD, TOP), [2.0, 0.0, 0.5])


def test_budget_flux_per_area():
    # A zero area gives NaN, and the sign of the flux is kept.
    flux = np.array([100.0, 0.0, -50.0, 5.0])
    area = np.array([10.0, 10.0, 10.0, 0.0])

    out = budget_flux_per_area(flux, area)

    np.testing.assert_allclose(out[:3], [10.0, 0.0, -5.0])
    assert np.isnan(out[3])


def test_seepage_mask_needs_an_input():
    with pytest.raises(ValueError):
        seepage_mask()
