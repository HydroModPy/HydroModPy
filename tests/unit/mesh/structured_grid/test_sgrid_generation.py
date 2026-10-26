"""Unit tests for hydromodpy.spatial.mesh.structured_grid.sgrid_generation."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.mesh.structured_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface


def _surface_from_array(
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


def test_build_from_surfaces_uses_absolute_top_and_bottom():
    top = np.array([[120.0, 121.0], [122.0, 123.0]], dtype=float)
    bottom = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=float)
    top_surface = _surface_from_array(top, name="top")
    bottom_surface = _surface_from_array(bottom, name="bottom")

    sgrid = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=VerticalGridConfig(
            genmtd_lay="constant",
            nlay=3,
            nodata=-9999.0,
        ),
    )

    assert sgrid.nlay == 3
    assert np.allclose(np.asarray(sgrid.top, dtype=float), top)
    assert np.allclose(np.asarray(sgrid.botm[-1], dtype=float), bottom)


def test_build_from_surfaces_rejects_domain_mismatch():
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    bot = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float)
    top_surface = _surface_from_array(top, xmin=0.0, ymin=0.0, name="top")
    bottom_surface = _surface_from_array(bot, xmin=1.0, ymin=0.0, name="bottom")

    with pytest.raises(ValueError, match="Domain extent mismatch"):
        _ = StructuredGridBuilder().build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config={"genmtd_lay": "constant", "nlay": 2},
        )
