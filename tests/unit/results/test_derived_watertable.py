"""Unit tests for the derived field helpers."""

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


def test_watertable_elevation_returns_head_unclipped():
    top = np.array([10.0, 10.0, 10.0])
    head = np.array([8.0, 11.0, 9.5])
    out = watertable_elevation(head, top)
    np.testing.assert_array_equal(out, [8.0, 11.0, 9.5])


def test_watertable_elevation_picks_uppermost_saturated_layer():
    top = np.array([10.0, 10.0])
    head = np.array(
        [
            [np.nan, 5.0],
            [3.0, 4.0],
        ]
    )
    out = watertable_elevation(head, top)
    assert out.shape == (2,)
    np.testing.assert_array_equal(out, [3.0, 5.0])


def test_watertable_depth_non_negative():
    top = np.array([10.0, 10.0, 10.0])
    head = np.array([8.0, 11.0, 9.5])
    out = watertable_depth(head, top)
    assert (out >= 0).all()
    np.testing.assert_array_equal(out, [2.0, 0.0, 0.5])


def test_seepage_mask_requires_an_input():
    with pytest.raises(ValueError):
        seepage_mask()


def test_fluxes_from_budget_per_unit_area():
    flux = np.array([100.0, 0.0, -50.0])
    area = np.array([10.0, 10.0, 10.0])
    out = budget_flux_per_area(flux, area)
    assert out[2] < 0
    np.testing.assert_array_almost_equal(out, [10.0, 0.0, -5.0])


def test_fluxes_from_budget_zero_area_returns_nan():
    flux = np.array([100.0, 0.0])
    area = np.array([10.0, 0.0])
    out = budget_flux_per_area(flux, area)
    assert out[0] == pytest.approx(10.0)
    assert np.isnan(out[1])


def test_watertable_elevation_xarray_path():
    top = xr.DataArray([10.0, 10.0, 10.0], dims="face")
    head = xr.DataArray([8.0, 11.0, 9.5], dims="face")
    out = watertable_elevation(head, top)
    assert isinstance(out, xr.DataArray)
    np.testing.assert_array_equal(out.values, [8.0, 11.0, 9.5])
    assert out.attrs["units"] == "m"
