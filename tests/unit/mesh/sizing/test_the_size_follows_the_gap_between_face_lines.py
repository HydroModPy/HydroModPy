"""The gap terms size the room between two face lines, and nothing else."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.mesh.request import RasterGridSpec
from hydromodpy.spatial.mesh.sizing.gap import GAP_LEVEL_RATIO, gap_terms
from hydromodpy.spatial.mesh.sizing.size_field import build_size_field, sample_size_field

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
_GRID = RasterGridSpec(
    xmin=0.0, xmax=1000.0, ymin=0.0, ymax=1000.0, dx=5.0, dy=5.0, nrow=200, ncol=200, crs_wkt=_WKT
)
_DOMAIN = box(0.0, 0.0, 1000.0, 1000.0)
_ARM_LAKE = Polygon(
    [(100, 100), (900, 100), (900, 500), (500, 500), (500, 140), (460, 140), (460, 500), (100, 500)]
)


def _terms(*lines: LineString, domain: Polygon = _DOMAIN, h0: float = 100.0):
    return gap_terms(lines, domain=domain, h0=h0, pixel=5.0, cells_across=2.0, touch=0.5)


def _size_at(terms, *points: tuple[float, float]) -> np.ndarray:
    field = build_size_field(_GRID, h0=100.0, h_floor=5.0, terms=terms, outside=None, max_slope=0.5)
    return sample_size_field(field, np.array(points))


def test_a_narrow_lake_arm_holds_two_cells_across() -> None:
    terms = _terms(LineString(_ARM_LAKE.exterior.coords))
    size = _size_at(terms, (480.0, 300.0))[0]
    assert 20.0 / GAP_LEVEL_RATIO <= size <= 20.0


def test_two_parallel_barriers_two_cells_apart_size_the_room_between() -> None:
    terms = _terms(LineString([(200, 470), (800, 470)]), LineString([(200, 530), (800, 530)]))
    size = _size_at(terms, (500.0, 500.0))[0]
    assert 30.0 / GAP_LEVEL_RATIO <= size <= 30.0


def test_lines_farther_apart_than_two_background_cells_refine_nothing() -> None:
    assert _terms(LineString(box(300, 300, 700, 700).exterior.coords)) == []


def test_a_right_angle_junction_is_not_a_gap() -> None:
    assert _terms(LineString([(500, 0), (500, 600)])) == []


def test_an_acute_junction_refines_its_sector_down_to_the_pixel() -> None:
    tip = (500.0, 500.0)
    one = LineString([tip, (800.0, 500.0)])
    two = LineString([tip, (500.0 + 300.0 * np.cos(0.35), 500.0 + 300.0 * np.sin(0.35))])
    terms = _terms(one, two)
    assert min(term.size_m for term in terms) == pytest.approx(5.0)


def test_a_line_on_the_domain_outline_touches_it_and_is_not_a_gap() -> None:
    assert _terms(LineString([(0, 200), (0, 800)])) == []


def test_a_notch_outside_the_domain_is_not_a_gap() -> None:
    notched = Polygon(
        [
            (0, 0),
            (1000, 0),
            (1000, 1000),
            (515, 1000),
            (515, 500),
            (485, 500),
            (485, 1000),
            (0, 1000),
        ]
    )
    assert _terms(domain=notched) == []


def test_the_same_notch_inside_a_lake_is_a_gap() -> None:
    notched = Polygon(
        [
            (100, 100),
            (900, 100),
            (900, 900),
            (515, 900),
            (515, 500),
            (485, 500),
            (485, 900),
            (100, 900),
        ]
    )
    terms = _terms(LineString(notched.exterior.coords))
    assert min(term.size_m for term in terms) <= 15.0


def test_a_catchment_boundary_that_is_the_domain_outline_is_one_line() -> None:
    assert _terms(LineString(_DOMAIN.exterior.coords)) == []
