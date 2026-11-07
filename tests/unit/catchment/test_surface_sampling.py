"""A prepared sampler reads a surface bilinearly at XY, with nodata as NaN."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.catchment.surface import Surface
from hydromodpy.catchment.surface_sampling import PreparedSurfaceSampler
from tests._helpers.domain_cases import raster_support

SUPPORT = raster_support(2, 2, cell=1.0, x0=0.0, y0=0.0)
VALUES = np.array([[10.0, 20.0], [30.0, -9999.0]])


def test_the_sampler_reads_bilinear_values_and_masks_nodata() -> None:
    sampler = PreparedSurfaceSampler.from_surface(Surface("topo", VALUES, SUPPORT))
    x, y = np.array([0.5, 1.0, 1.5]), np.array([1.5, 1.0, 0.5])

    sampled = sampler.sample(x, y)

    np.testing.assert_allclose(sampled, [10.0, 20.0, np.nan])
    np.testing.assert_array_equal(sampler.sample_points_xy(np.column_stack([x, y])), sampled)


@pytest.mark.parametrize(
    "support",
    [None, replace(SUPPORT, dx=None), replace(SUPPORT, nrows=None), replace(SUPPORT, dx=0.0)],
    ids=["no_support", "no_cell_size", "no_shape", "zero_cell_size"],
)
def test_a_support_that_places_no_cell_samples_nan(support) -> None:
    sampler = PreparedSurfaceSampler.from_surface(Surface("topo", VALUES, support))

    assert np.all(np.isnan(sampler.sample(np.array([0.5, 1.0]), np.array([0.5, 1.0]))))


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda s: PreparedSurfaceSampler.from_surface(None), "surface is required"),
        (lambda s: s.sample(np.zeros(2), np.zeros(3)), "same shape"),
        (lambda s: s.sample_points_xy(np.zeros((2, 3))), r"shape \(n_points, 2\)"),
    ],
    ids=["no_surface", "x_and_y_differ", "points_not_xy"],
)
def test_a_request_with_no_coordinates_to_read_is_refused(call, match) -> None:
    sampler = PreparedSurfaceSampler.from_surface(Surface("topo", VALUES, SUPPORT))

    with pytest.raises(ValueError, match=match):
        call(sampler)
