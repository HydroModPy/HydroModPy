"""The bathymetry raster becomes one bed elevation per mesh cell."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.lake_bed.regrid import cell_bed_from_surface
from hydromodpy.spatial.surface import Surface
from tests._helpers.lake_bed_cases import quad_mesh, ramp_surface


@pytest.mark.parametrize(("offset", "n"), [(0.0, 200), (12.5, 4)], ids=["inside", "on_the_edges"])
def test_a_cell_gets_the_mean_of_the_pixels_whose_centre_it_holds(offset, n) -> None:
    """On z = x, the zonal mean of a cell is the x of its centre; an edge pixel counts for none."""
    mesh = quad_mesh(dx=50.0, dy=50.0, ncol=2, nrow=2, xmin=offset, ymin=offset)
    bed = cell_bed_from_surface(planar_mesh=mesh, surface=ramp_surface(n=n), cell_ids=[0, 1, 2, 3])
    expected = offset + np.array([25.0, 75.0, 25.0, 75.0])
    assert [bed[c] for c in range(4)] == pytest.approx(expected, abs=0.5)


@pytest.mark.parametrize(
    ("mesh", "surface", "min_pixels", "expected"),
    [
        # A raster with no support cannot be read zonally, nor sampled.
        pytest.param(quad_mesh(dx=50.0, dy=50.0, ncol=2, nrow=1), Surface(name="bathy", values=np.ones((4, 4)), support=None),
                     1, [np.nan, np.nan], id="no_support"),
        # A cell holding no pixel centre takes the bilinear sample at its centroid.
        pytest.param(quad_mesh(dx=10.0, dy=10.0, ncol=1, nrow=1, xmin=40.0), ramp_surface(n=2), 1, [45.0], id="finer_than_raster"),
        # Fewer pixels than asked for: the centroid again.
        pytest.param(quad_mesh(dx=50.0, dy=50.0, ncol=1, nrow=1), ramp_surface(n=200), 10_000, [25.0], id="too_few_pixels"),
        # A cell off the raster has neither pixels nor a sample.
        pytest.param(quad_mesh(dx=10.0, dy=10.0, ncol=1, nrow=1, xmin=500.0), ramp_surface(n=20), 1, [np.nan], id="off_the_raster"),
    ],
)  # fmt: skip
def test_a_cell_the_zonal_mean_cannot_serve_falls_back_to_its_centroid(
    mesh, surface, min_pixels, expected
) -> None:
    cells = list(range(len(expected)))
    bed = cell_bed_from_surface(
        planar_mesh=mesh, surface=surface, cell_ids=cells, min_pixels=min_pixels
    )
    np.testing.assert_allclose([bed[c] for c in cells], expected, atol=1e-9)
