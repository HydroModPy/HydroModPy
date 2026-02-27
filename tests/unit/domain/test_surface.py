from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface


def _build_surface(
    values: np.ndarray,
    *,
    xmin: float = 0.0,
    ymin: float = 0.0,
    dx: float = 1.0,
    dy: float = 1.0,
    crs: str = "EPSG:2154",
    nodata: float = -9999.0,
    name: str = "surface",
) -> Surface:
    arr = np.asarray(values, dtype=float)
    nrows, ncols = arr.shape
    support = RasterSupport(
        crs=crs,
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmin + (dx * ncols),
        ymin=ymin,
        ymax=ymin + (dy * nrows),
        nrows=nrows,
        ncols=ncols,
        nodata=nodata,
    )
    return Surface(name=name, values=arr, support=support)


def test_surface_assert_same_geographic_domain_ok():
    top = _build_surface(np.array([[1.0, 2.0], [3.0, 4.0]]), name="top")
    bottom = _build_surface(np.array([[0.0, 1.0], [2.0, 3.0]]), name="bottom")
    top.assert_same_geographic_domain(bottom)


def test_surface_assert_same_geographic_domain_raises_on_extent():
    top = _build_surface(np.array([[1.0, 2.0], [3.0, 4.0]]), xmin=0.0, name="top")
    bottom = _build_surface(np.array([[0.0, 1.0], [2.0, 3.0]]), xmin=5.0, name="bottom")
    with pytest.raises(ValueError, match="Domain extent mismatch"):
        top.assert_same_geographic_domain(bottom)


def test_surface_resample_to_shape_keeps_domain_and_updates_shape():
    surface = _build_surface(
        np.array([[100.0, 101.0], [103.0, 104.0]]),
        dx=10.0,
        dy=10.0,
        xmin=5.0,
        ymin=7.0,
        name="surface",
    )
    resampled = surface.resample_to_shape(4, 5, resampling="bilinear")
    surface.assert_same_geographic_domain(resampled)
    assert resampled.as_array().shape == (4, 5)
