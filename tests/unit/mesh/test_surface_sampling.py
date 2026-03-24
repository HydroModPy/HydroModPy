from __future__ import annotations

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler


def test_prepared_surface_sampler_samples_bilinear_values_once_surface_is_prepared() -> None:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=1.0,
        dy=1.0,
        xmin=0.0,
        xmax=2.0,
        ymin=0.0,
        ymax=2.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, -9999.0]], dtype=float),
        support=support,
    )

    sampler = PreparedSurfaceSampler.from_surface(surface)

    sampled = sampler.sample(
        np.array([0.5, 1.0, 1.5], dtype=float),
        np.array([1.5, 1.0, 0.5], dtype=float),
    )

    assert np.isclose(sampled[0], 10.0)
    assert np.isclose(sampled[1], 20.0)
    assert np.isnan(sampled[2])


def test_prepared_surface_sampler_returns_nan_without_complete_support() -> None:
    surface = Surface(
        name="surface_topo",
        values=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float),
        support=None,
    )

    sampler = PreparedSurfaceSampler.from_surface(surface)
    sampled = sampler.sample(np.array([0.0, 1.0]), np.array([0.0, 1.0]))

    assert np.all(np.isnan(sampled))

