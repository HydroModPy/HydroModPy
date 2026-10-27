"""The gap terms size the room between two face lines, and nothing else.

A narrow lake arm, two parallel barriers or an acute junction refine their
room to the cells it must hold across. A right angle, a line on the domain
outline, a notch outside the domain or lines farther apart than two background
cells are no gap.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.mesh.sizing.gap import GAP_LEVEL_RATIO, gap_terms
from hydromodpy.spatial.mesh.sizing.size_field import build_size_field, sample_size_field
from tests._helpers.mesh_cases import grid_spec, square_domain

_GRID = grid_spec(200, 200, 5.0)
_DOMAIN = square_domain(1000.0)
_ARM_LAKE = Polygon(
    [(100, 100), (900, 100), (900, 500), (500, 500), (500, 140), (460, 140), (460, 500), (100, 500)]
)


def _terms(*lines: LineString, domain: Polygon = _DOMAIN, h0: float = 100.0):
    return gap_terms(lines, domain=domain, h0=h0, pixel=5.0, cells_across=2.0, touch=0.5)


def _size_at(terms, *points: tuple[float, float]) -> np.ndarray:
    field = build_size_field(_GRID, h0=100.0, h_floor=5.0, terms=terms, outside=None, max_slope=0.5)
    return sample_size_field(field, np.array(points))


def _notch(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    """The ring of a rectangle with a notch 30 m wide down to its middle from the north side."""
    middle = 0.5 * (y0 + y1)
    return [
        (x0, y0),
        (x1, y0),
        (x1, y1),
        (515, y1),
        (515, middle),
        (485, middle),
        (485, y1),
        (x0, y1),
    ]


def test_a_narrow_lake_arm_holds_two_cells_across() -> None:
    terms = _terms(LineString(_ARM_LAKE.exterior.coords))
    size = _size_at(terms, (480.0, 300.0))[0]
    assert 20.0 / GAP_LEVEL_RATIO <= size <= 20.0


def test_two_parallel_barriers_two_cells_apart_size_the_room_between() -> None:
    terms = _terms(LineString([(200, 470), (800, 470)]), LineString([(200, 530), (800, 530)]))
    size = _size_at(terms, (500.0, 500.0))[0]
    assert 30.0 / GAP_LEVEL_RATIO <= size <= 30.0


def test_an_acute_junction_refines_its_sector_down_to_the_pixel() -> None:
    tip = (500.0, 500.0)
    one = LineString([tip, (800.0, 500.0)])
    two = LineString([tip, (500.0 + 300.0 * np.cos(0.35), 500.0 + 300.0 * np.sin(0.35))])
    terms = _terms(one, two)
    assert min(term.size_m for term in terms) == pytest.approx(5.0)


def test_the_same_notch_inside_a_lake_is_a_gap() -> None:
    notched = Polygon(_notch(100, 100, 900, 900))
    terms = _terms(LineString(notched.exterior.coords))
    assert min(term.size_m for term in terms) <= 15.0


@pytest.mark.parametrize(
    ("lines", "domain"),
    [
        ((LineString(box(300, 300, 700, 700).exterior.coords),), _DOMAIN),
        ((LineString([(500, 0), (500, 600)]),), _DOMAIN),
        ((LineString([(0, 200), (0, 800)]),), _DOMAIN),
        ((), Polygon(_notch(0, 0, 1000, 1000))),
        ((LineString(_DOMAIN.exterior.coords),), _DOMAIN),
    ],
    ids=[
        "lines farther apart than two background cells",
        "right angle junction",
        "line on the domain outline",
        "notch outside the domain",
        "catchment boundary that is the domain outline",
    ],
)
def test_room_that_holds_two_background_cells_is_no_gap(lines, domain: Polygon) -> None:
    assert _terms(*lines, domain=domain) == []
