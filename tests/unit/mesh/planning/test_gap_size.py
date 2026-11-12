"""The gap terms size the room between two face lines, and nothing else.

A narrow lake arm, two parallel barriers or an acute junction refine their
room to the cells it must hold across. A right angle, a line on the domain
outline, a notch outside the domain or lines farther apart than two background
cells are no gap.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.mesh.planning.gap_size import gap_terms
from hydromodpy.mesh.planning.size_field import build_size_field
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
    return field.sample(np.array(points))


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


def test_an_acute_junction_refines_its_sector_down_to_the_pixel() -> None:
    tip = (500.0, 500.0)
    one = LineString([tip, (800.0, 500.0)])
    two = LineString([tip, (500.0 + 300.0 * np.cos(0.35), 500.0 + 300.0 * np.sin(0.35))])
    terms = _terms(one, two)
    assert min(term.size_m for term in terms) == pytest.approx(5.0)
