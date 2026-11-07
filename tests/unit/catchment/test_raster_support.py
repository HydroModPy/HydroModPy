"""A raster support places a grid: CRS, extent, cell size, shape and nodata."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from hydromodpy.catchment.raster_support import RasterSupport

GRID = RasterSupport(crs="EPSG:2154", dx=25.0, dy=25.0, xmin=0.0, xmax=50.0, ymin=0.0, ymax=25.0, nrows=1, ncols=2)  # fmt: skip


def test_the_georeferencing_round_trips_and_an_unknown_extent_has_no_cell_area() -> None:
    support = RasterSupport.from_georeferencing({"crs": "EPSG:2154", "dx": 25.0, "xmin": 0.0})

    assert (support.nrows, support.ncols, support.nodata) == (None, None, None)
    assert support.as_georeferencing_dict() == {"crs": "EPSG:2154", "dx": 25.0, "xmin": 0.0}
    assert RasterSupport.from_georeferencing(None) == RasterSupport()
    assert math.isnan(support.cell_area)
    assert GRID.cell_area == 625.0


@pytest.mark.parametrize(
    ("other", "error", "match"),
    [
        (GRID.as_georeferencing_dict(), TypeError, "Expected RasterSupport"),
        (replace(GRID, nrows=None, crs=None), ValueError, "missing required domain metadata: crs, nrows"),
        (replace(GRID, crs="EPSG:3857"), ValueError, "CRS mismatch"),
        (replace(GRID, xmax=75.0), ValueError, "extent mismatch for 'xmax'"),
    ],
    ids=["not_a_support", "incomplete", "other_crs", "other_extent"],
)  # fmt: skip
def test_two_supports_of_different_domains_are_refused_and_a_crs_differing_by_case_is_not(other, error, match) -> None:  # fmt: skip
    assert GRID.assert_same_geographic_domain(replace(GRID, crs=" epsg:2154 ")) is None
    with pytest.raises(error, match=match):
        GRID.assert_same_geographic_domain(other)
