"""The height above the stream is computed on the DEM and the traced network alone.

On a V-shaped valley whose thalweg is the stream, a pixel lies its side slope
times its distance to the thalweg above it. A pit below its stream gets 0,
a pixel that drains off the grid without a stream has no height, and a grid
without a stream is refused.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.planning.height_above_stream import height_above_stream, stream_pixels
from tests._helpers.mesh_cases import grid_spec

STEP = 10.0
NROW, NCOL = 30, 41
THALWEG = 20
SIDE_SLOPE = 0.1
VALLEY_SLOPE = 0.01


def _valley() -> tuple[np.ndarray, np.ndarray]:
    """A V valley along column THALWEG, its floor falling to the south, and its stream."""
    rows, cols = np.mgrid[0:NROW, 0:NCOL]
    elevation = (
        100.0 + SIDE_SLOPE * STEP * np.abs(cols - THALWEG) + VALLEY_SLOPE * STEP * (NROW - 1 - rows)
    )
    streams = np.zeros((NROW, NCOL), dtype=bool)
    streams[:, THALWEG] = True
    return elevation, streams


def test_a_pixel_lies_its_side_slope_times_its_distance_above_the_thalweg() -> None:
    elevation, streams = _valley()

    height = height_above_stream(elevation, streams, dx=STEP, dy=STEP)

    distance = STEP * np.abs(np.arange(NCOL) - THALWEG)
    for row in (3, 15, 27):
        np.testing.assert_allclose(height[row], SIDE_SLOPE * distance, atol=1e-9)
    assert np.all(height[:, THALWEG] == 0.0)
    near = height < 2.0
    assert near[:, THALWEG - 1 : THALWEG + 2].all()
    assert not near[:, : THALWEG - 1].any()
    assert not near[:, THALWEG + 2 :].any()


def test_a_pit_below_its_stream_has_no_negative_height() -> None:
    elevation, streams = _valley()
    elevation[10, 25] = 90.0

    height = height_above_stream(elevation, streams, dx=STEP, dy=STEP)

    assert height[10, 25] == 0.0
    assert np.nanmin(height) >= 0.0


def test_a_pixel_that_drains_off_the_grid_without_a_stream_has_no_height() -> None:
    elevation, streams = _valley()
    streams[:, THALWEG] = False
    streams[:5, THALWEG] = True

    height = height_above_stream(elevation, streams, dx=STEP, dy=STEP)

    assert np.isnan(height[-1, THALWEG])
    assert height[0, THALWEG] == 0.0


def test_a_pixel_without_elevation_has_no_height() -> None:
    elevation, streams = _valley()
    elevation[5, 5] = np.nan
    elevation[6, 6] = -99999.0

    height = height_above_stream(elevation, streams, dx=STEP, dy=STEP)

    assert np.isnan(height[5, 5]) and np.isnan(height[6, 6])
    assert np.isfinite(height[5, 6])


def test_a_grid_without_a_stream_is_refused() -> None:
    elevation, streams = _valley()

    with pytest.raises(MeshRequestError, match="no stream pixel"):
        height_above_stream(elevation, np.zeros_like(streams), dx=STEP, dy=STEP)


def test_stream_pixels_of_another_shape_than_the_dem_are_refused() -> None:
    elevation, streams = _valley()

    with pytest.raises(MeshRequestError, match="differ in shape"):
        height_above_stream(elevation, streams[:, :-1], dx=STEP, dy=STEP)


def test_the_stream_lines_mark_the_pixels_they_run_through() -> None:
    grid = grid_spec(NROW, NCOL, STEP)
    x = (THALWEG + 0.5) * STEP
    line = LineString([(x, NROW * STEP - 1.0), (x, 1.0)])

    pixels = stream_pixels([line], grid)

    assert pixels[:, THALWEG].all()
    assert pixels.sum() == NROW


def test_no_stream_line_marks_no_pixel() -> None:
    grid = grid_spec(NROW, NCOL, STEP)

    assert not stream_pixels([LineString()], grid).any()
