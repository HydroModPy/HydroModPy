"""Family lines are cut at their fixed nodes and resampled at the local cell size.

The fixed nodes are the line ends, the confluences, the crossings, the contacts
with the domain outline, the corners of a barrier and the points the planner
fixes. Between two of them a line is cut into segments of equal
``integral ds / h``, none shorter than 0.8 local cell unless the whole edge is.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.mesh.request import LineFamilySpec, SizeField
from hydromodpy.mesh.resample import positions_at_local_size, resample_families
from tests._helpers.mesh_cases import grid_spec, square_domain, uniform_size_field

_DOMAIN = square_domain(1000.0)
_GRID = grid_spec(200, 200, 5.0)


def _uniform(size: float) -> SizeField:
    return uniform_size_field(_GRID, size)


def _ramp_in_x(a: float, b: float) -> SizeField:
    """``h = a + b x`` at the pixel centers: bilinear sampling is exact between them."""
    x = 2.5 + 5.0 * np.arange(200)
    return SizeField(values=np.tile(a + b * x, (200, 1)), grid=_GRID)


def _segment_integrals(line: LineString, field: SizeField) -> np.ndarray:
    """``integral ds / h`` of every segment of *line*, by a fine trapezoid."""
    coords = np.asarray(line.coords)
    integrals = []
    for start, end in zip(coords[:-1], coords[1:], strict=True):
        t = np.linspace(0.0, 1.0, 2001)
        points = start + t[:, None] * (end - start)
        inverse = 1.0 / field.sample(points)
        integrals.append(np.trapezoid(inverse, t) * np.hypot(*(end - start)))
    return np.asarray(integrals)


def _has_vertex(line: LineString, xy: tuple[float, float]) -> bool:
    return any(tuple(c) == xy for c in np.asarray(line.coords))


def test_segments_on_a_ramp() -> None:
    a, b = 10.0, 0.05
    field = _ramp_in_x(a, b)
    x0, x1 = 50.0, 900.0
    family = LineFamilySpec("rivers", "cell", (LineString([(x0, 500.0), (x1, 500.0)]),))
    out = resample_families([family], domain=_DOMAIN, size_field=field)
    line = out.families[0].lines[0]
    exact = math.log((a + b * x1) / (a + b * x0)) / b
    assert len(line.coords) - 1 == round(exact)
    np.testing.assert_allclose(_segment_integrals(line, field), exact / round(exact), rtol=1e-3)
    assert line.coords[0] == (x0, 500.0) and line.coords[-1] == (x1, 500.0)
    assert out.short_fixed_edges == 0


def test_river_round_a_corner() -> None:
    domain = Polygon([(0, 0), (1000, 0), (1000, 500), (500, 500), (500, 1000), (0, 1000)])
    bend = LineString([(497.0, 900.0), (497.0, 497.0), (950.0, 497.0)])
    out = resample_families(
        [LineFamilySpec("rivers", "cell", (bend,))], domain=domain, size_field=_uniform(150.0)
    )
    line = out.families[0].lines[0]
    assert domain.buffer(1e-6).covers(line)
    assert _has_vertex(line, (497.0, 497.0))
    assert line.coords[0] == (497.0, 900.0) and line.coords[-1] == (950.0, 497.0)


def test_positions_equal_segments() -> None:
    piece = LineString([(0.0, 0.0), (100.0, 0.0)])
    points, positions, short = positions_at_local_size(
        piece, 2.5, lambda xy: np.full(len(xy), 10.0), ring=False
    )

    assert positions.tolist() == pytest.approx([10.0 * k for k in range(1, 10)])
    assert np.asarray(points)[:, 0].tolist() == pytest.approx(positions.tolist())
    assert short == 0


def test_positions_local_frame() -> None:
    """The size callable sees the coordinates of the piece, so a local frame works."""
    seen = []

    def size_at(xy: np.ndarray) -> np.ndarray:
        seen.append(np.asarray(xy))
        return np.full(len(xy), 20.0)

    piece = LineString([(-50.0, 0.0), (50.0, 0.0)])
    _, positions, _ = positions_at_local_size(piece, 5.0, size_at, ring=False)

    assert positions.tolist() == pytest.approx([20.0, 40.0, 60.0, 80.0])
    assert all(np.abs(xy).max() <= 50.0 + 1e-9 for xy in seen)


def test_tiny_line_keeps_its_ends() -> None:
    tiny = LineString([(500.0, 500.0), (500.0 + 1.0e-7, 500.0)])
    (family,) = resample_families(
        [LineFamilySpec("rivers", "cell", (tiny,))], domain=_DOMAIN, size_field=_uniform(30.0)
    ).families

    assert list(family.lines[0].coords) == list(tiny.coords)


def test_line_leaving_the_domain() -> None:
    """A chord off the domain gets the original vertices back, and none is left to add past the edge."""
    line = LineString([(900.0, 500.0), (1100.0, 500.0), (1100.0, 600.0)])
    (family,) = resample_families(
        [LineFamilySpec("rivers", "cell", (line,))], domain=_DOMAIN, size_field=_uniform(30.0)
    ).families

    resampled = family.lines[0]
    assert _has_vertex(resampled, (1100.0, 500.0))
    assert resampled.hausdorff_distance(line) < 1.0e-9


def test_short_piece_stays_one_segment() -> None:
    """Two segments would be 0.75 cell each, under the shortest share."""
    piece = LineString([(0.0, 0.0), (15.0, 0.0)])
    points, positions, short = positions_at_local_size(
        piece, 1.0, lambda xy: np.full(len(xy), 10.0), ring=False
    )

    assert points == [] and positions.size == 0
    assert short == 0
