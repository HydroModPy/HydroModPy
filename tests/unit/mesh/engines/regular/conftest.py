"""The DEM grids the regular engine is checked on."""

from __future__ import annotations

import dataclasses

import pytest

from hydromodpy.spatial.mesh.request import RasterGridSpec
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec

DEM_GRIDS = {
    "lambert_25m": grid_spec(119, 135, 25.0, xmin=346512.5, ymin=6789012.25, crs_wkt=LAMBERT93_WKT),
    "odd_pitch_negative_origin": grid_spec(
        37, 41, 24.4, xmin=-123.456, ymin=-987.321, crs_wkt=LAMBERT93_WKT
    ),
    "band_1x40": grid_spec(1, 40, 100.0, crs_wkt=LAMBERT93_WKT),
    "square": grid_spec(40, 40, 25.0, crs_wkt=LAMBERT93_WKT),
    "pixels_not_square": dataclasses.replace(
        grid_spec(37, 41, 25.00000003, xmin=346512.5, ymin=6789012.25, crs_wkt=LAMBERT93_WKT),
        dy=24.994117,
        ymax=6789012.25 + 37 * 24.994117,
    ),
}


@pytest.fixture(params=sorted(DEM_GRIDS))
def dem_grid(request: pytest.FixtureRequest) -> RasterGridSpec:
    """A DEM grid of a real project, or one with an odd pitch, one row or pixels not square."""
    return DEM_GRIDS[request.param]
