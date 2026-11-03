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
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec, SizeField
from hydromodpy.spatial.mesh.resample import (
    MIN_SEGMENT_SHARE,
    positions_at_local_size,
    resample_families,
)
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


def test_a_line_on_a_known_ramp_gets_round_integral_segments() -> None:
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


def test_no_segment_is_shorter_than_0_8_cell_off_short_fixed_edges() -> None:
    field = _ramp_in_x(12.0, 0.08)
    lines = (
        LineString([(20.0, 30.0), (400.0, 610.0), (980.0, 700.0)]),
        LineString([(100.0, 900.0), (500.0, 100.0)]),
    )
    out = resample_families(
        [LineFamilySpec("rivers", "cell", lines)], domain=_DOMAIN, size_field=field
    )
    for line in out.families[0].lines:
        assert _segment_integrals(line, field).min() >= MIN_SEGMENT_SHARE * (1.0 - 1e-2)


def test_a_short_edge_between_two_fixed_nodes_is_kept_whole_and_counted() -> None:
    field = _uniform(40.0)
    river = LineString([(100.0, 500.0), (900.0, 500.0)])
    # The contact crosses the river 10 m before the river end: a 10 m fixed edge.
    contact = LineString([(890.0, 100.0), (890.0, 900.0)])
    out = resample_families(
        [
            LineFamilySpec("rivers", "cell", (river,)),
            LineFamilySpec("geology", "face", (contact,), zone_left=("a",), zone_right=("b",)),
        ],
        domain=_DOMAIN,
        size_field=field,
    )
    river_out = out.families[0].lines[0]
    assert river_out.coords[-2] == (890.0, 500.0)
    assert river_out.coords[-1] == (900.0, 500.0)
    assert out.short_fixed_edges == 1


def test_a_closed_ring_keeps_at_least_three_segments_and_closes() -> None:
    field = _uniform(50.0)
    ring = LineString(Point(500.0, 500.0).buffer(5.0, 16).exterior.coords)
    out = resample_families(
        [LineFamilySpec("lakes", "face", (ring,), closed=True)], domain=_DOMAIN, size_field=field
    )
    line = out.families[0].lines[0]
    assert line.is_closed
    assert len(line.coords) - 1 == 3
    assert out.short_fixed_edges == 1


def test_a_confluence_is_a_shared_vertex_of_every_line() -> None:
    field = _uniform(30.0)
    confluence = (517.3, 488.1)
    lines = (
        LineString([(100.0, 900.0), confluence]),
        LineString([(900.0, 870.0), confluence]),
        LineString([confluence, (500.0, 20.0)]),
    )
    out = resample_families(
        [LineFamilySpec("rivers", "cell", lines)], domain=_DOMAIN, size_field=field
    )
    resampled = out.families[0].lines
    assert resampled[0].coords[-1] == confluence
    assert resampled[1].coords[-1] == confluence
    assert resampled[2].coords[0] == confluence


def test_a_river_crossing_a_contact_shares_the_crossing_vertex() -> None:
    field = _ramp_in_x(15.0, 0.02)
    river = LineString([(50.0, 123.4), (950.0, 871.2)])
    contact = LineString([(80.0, 900.0), (930.0, 60.0)])
    out = resample_families(
        [
            LineFamilySpec("rivers", "cell", (river,)),
            LineFamilySpec("geology", "face", (contact,), zone_left=("a",), zone_right=("b",)),
        ],
        domain=_DOMAIN,
        size_field=field,
    )
    crossing = river.intersection(contact)
    river_out, contact_out = out.families[0].lines[0], out.families[1].lines[0]
    shared = set(map(tuple, np.asarray(river_out.coords))) & set(
        map(tuple, np.asarray(contact_out.coords))
    )
    assert len(shared) == 1
    assert Point(next(iter(shared))).distance(crossing) < 1e-9
    assert out.families[1].zone_left == ("a",) and out.families[1].zone_right == ("b",)


def test_a_line_touching_the_boundary_keeps_the_contact_point() -> None:
    field = _uniform(40.0)
    # Dips to the south side at x = 437.5 and comes back.
    line = LineString([(100.0, 300.0), (437.5, 0.0), (800.0, 300.0)])
    out = resample_families(
        [LineFamilySpec("rivers", "cell", (line,))], domain=_DOMAIN, size_field=field
    )
    assert _has_vertex(out.families[0].lines[0], (437.5, 0.0))


def test_orientation_and_line_count_are_kept() -> None:
    field = _uniform(25.0)
    lines = (
        LineString([(900.0, 100.0), (100.0, 150.0)]),
        LineString([(300.0, 900.0), (310.0, 200.0)]),
    )
    out = resample_families(
        [LineFamilySpec("rivers", "cell", lines)], domain=_DOMAIN, size_field=field
    )
    for before, after in zip(lines, out.families[0].lines, strict=True):
        assert after.coords[0] == before.coords[0]
        assert after.coords[-1] == before.coords[-1]


@pytest.mark.parametrize("size", [7.0, 33.0])
def test_a_uniform_field_gives_segments_close_to_one_cell(size: float) -> None:
    field = _uniform(size)
    line = LineString([(10.0, 10.0), (600.0, 400.0), (990.0, 990.0)])
    out = resample_families(
        [LineFamilySpec("rivers", "cell", (line,))], domain=_DOMAIN, size_field=field
    )
    lengths = np.hypot(*np.diff(np.asarray(out.families[0].lines[0].coords), axis=0).T)
    assert lengths.min() >= MIN_SEGMENT_SHARE * size * (1 - 1e-6)
    assert lengths.max() <= 1.5 * size


def test_a_river_around_a_re_entrant_corner_stays_in_the_domain() -> None:
    domain = Polygon([(0, 0), (1000, 0), (1000, 500), (500, 500), (500, 1000), (0, 1000)])
    bend = LineString([(497.0, 900.0), (497.0, 497.0), (950.0, 497.0)])
    out = resample_families(
        [LineFamilySpec("rivers", "cell", (bend,))], domain=domain, size_field=_uniform(150.0)
    )
    line = out.families[0].lines[0]
    assert domain.buffer(1e-6).covers(line)
    assert _has_vertex(line, (497.0, 497.0))
    assert line.coords[0] == (497.0, 900.0) and line.coords[-1] == (950.0, 497.0)


def test_positions_at_local_size_cut_a_piece_in_equal_integral_segments() -> None:
    piece = LineString([(0.0, 0.0), (100.0, 0.0)])
    points, positions, short = positions_at_local_size(
        piece, 2.5, lambda xy: np.full(len(xy), 10.0), ring=False
    )

    assert positions.tolist() == pytest.approx([10.0 * k for k in range(1, 10)])
    assert np.asarray(points)[:, 0].tolist() == pytest.approx(positions.tolist())
    assert short == 0


def test_positions_at_local_size_read_the_size_in_the_frame_of_the_piece() -> None:
    """The size callable sees the coordinates of the piece, so a local frame works."""
    seen = []

    def size_at(xy: np.ndarray) -> np.ndarray:
        seen.append(np.asarray(xy))
        return np.full(len(xy), 20.0)

    piece = LineString([(-50.0, 0.0), (50.0, 0.0)])
    _, positions, _ = positions_at_local_size(piece, 5.0, size_at, ring=False)

    assert positions.tolist() == pytest.approx([20.0, 40.0, 60.0, 80.0])
    assert all(np.abs(xy).max() <= 50.0 + 1e-9 for xy in seen)


def test_a_closed_ring_gets_at_least_three_segments() -> None:
    ring = LineString([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)])
    _, positions, _ = positions_at_local_size(
        ring, 1.0, lambda xy: np.full(len(xy), 100.0), ring=True
    )

    assert positions.size == 2


def test_a_barrier_corner_stays_a_vertex_where_another_line_is_resampled() -> None:
    field = uniform_size_field(grid_spec(100, 100), 20.0)
    bent = LineString([(10.0, 10.0), (50.0, 12.0), (52.0, 90.0)])
    families = (
        LineFamilySpec(BARRIER_FAMILY, "face", (bent,)),
        LineFamilySpec("geology", "face", (LineString(np.asarray(bent.coords) + [5.0, 0.0]),)),
    )
    barrier, contact = resample_families(
        families, domain=box(0, 0, 100, 100), size_field=field
    ).families

    assert (50.0, 12.0) in set(barrier.lines[0].coords)
    assert (55.0, 12.0) not in set(contact.lines[0].coords)


def test_a_fixed_point_on_a_line_stays_a_vertex() -> None:
    field = uniform_size_field(grid_spec(100, 100), 30.0)
    family = LineFamilySpec("geology", "face", (LineString([(5.0, 50.0), (95.0, 50.0)]),))
    (resampled,) = resample_families(
        (family,),
        domain=box(0, 0, 100, 100),
        size_field=field,
        fixed_points=np.array([[41.0, 50.0]]),
    ).families

    assert (41.0, 50.0) in set(resampled.lines[0].coords)


def test_a_line_shorter_than_the_node_tolerance_keeps_its_two_ends() -> None:
    tiny = LineString([(500.0, 500.0), (500.0 + 1.0e-7, 500.0)])
    (family,) = resample_families(
        [LineFamilySpec("rivers", "cell", (tiny,))], domain=_DOMAIN, size_field=_uniform(30.0)
    ).families

    assert list(family.lines[0].coords) == list(tiny.coords)


def test_a_line_that_leaves_the_domain_is_followed_as_it_is_outside() -> None:
    """A chord off the domain gets the original vertices back, and none is left to add past the edge."""
    line = LineString([(900.0, 500.0), (1100.0, 500.0), (1100.0, 600.0)])
    (family,) = resample_families(
        [LineFamilySpec("rivers", "cell", (line,))], domain=_DOMAIN, size_field=_uniform(30.0)
    ).families

    resampled = family.lines[0]
    assert _has_vertex(resampled, (1100.0, 500.0))
    assert resampled.hausdorff_distance(line) < 1.0e-9


def test_a_piece_of_one_and_a_half_cells_stays_one_segment() -> None:
    """Two segments would be 0.75 cell each, under the shortest share."""
    piece = LineString([(0.0, 0.0), (15.0, 0.0)])
    points, positions, short = positions_at_local_size(
        piece, 1.0, lambda xy: np.full(len(xy), 10.0), ring=False
    )

    assert points == [] and positions.size == 0
    assert short == 0
