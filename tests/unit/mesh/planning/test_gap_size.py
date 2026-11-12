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
from tests._helpers.mesh_cases import square_domain

_DOMAIN = square_domain(1000.0)


def _terms(*lines: LineString, domain: Polygon = _DOMAIN, h0: float = 100.0):
    return gap_terms(lines, domain=domain, h0=h0, pixel=5.0, cells_across=2.0, touch=0.5)


def test_an_acute_junction_refines_its_sector_down_to_the_pixel() -> None:
    tip = (500.0, 500.0)
    one = LineString([tip, (800.0, 500.0)])
    two = LineString([tip, (500.0 + 300.0 * np.cos(0.35), 500.0 + 300.0 * np.sin(0.35))])
    terms = _terms(one, two)
    assert min(term.size_m for term in terms) == pytest.approx(5.0)
