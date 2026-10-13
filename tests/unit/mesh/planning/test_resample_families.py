"""Family lines are cut at their fixed nodes and resampled at the local cell size."""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.spatial.mesh.planning.resample import MIN_SEGMENT_SHARE, resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, RasterGridSpec, SizeField
from hydromodpy.spatial.mesh.sizing.size_field import sample_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
_DOMAIN = box(0.0, 0.0, 1000.0, 1000.0)


def _grid() -> RasterGridSpec:
    return RasterGridSpec(
        xmin=0.0,
        xmax=1000.0,
        ymin=0.0,
        ymax=1000.0,
        dx=5.0,
        dy=5.0,
        nrow=200,
        ncol=200,
        crs_wkt=_WKT,
    )


def _uniform(size: float) -> SizeField:
    return SizeField(values=np.full((200, 200), size), grid=_grid())


def _ramp_in_x(a: float, b: float) -> SizeField:
    """``h = a + b x`` at the pixel centres: bilinear sampling is exact between them."""
    x = 2.5 + 5.0 * np.arange(200)
    return SizeField(values=np.tile(a + b * x, (200, 1)), grid=_grid())


def _segment_integrals(line: LineString, field: SizeField) -> np.ndarray:
    """``integral ds / h`` of every segment of *line*, by a fine trapezoid."""
    coords = np.asarray(line.coords)
    integrals = []
    for start, end in zip(coords[:-1], coords[1:], strict=True):
        t = np.linspace(0.0, 1.0, 2001)
        points = start + t[:, None] * (end - start)
        inverse = 1.0 / sample_size_field(field, points)
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
