"""A head with no landing cell within the snap radius is lost and draws nothing."""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.core._heads_valley import AXIS, candidates, cell, centre, valley_geometry


def test_a_head_farther_than_the_radius_is_lost() -> None:
    junction = centre(15, AXIS)
    # The second head lies 200 m west of the domain, past any 100 m landing.
    heads = candidates([(centre(5, AXIS), junction), ((-200.0, 155.0), junction)])

    geometry = valley_geometry(heads, snap_radius_m=100.0)

    trace = geometry.heads
    assert trace is not None
    assert trace.head_cell.tolist() == [cell(5, AXIS), -1]
    assert np.isnan(trace.snap_distance_m[1])
    assert geometry.diagnostics["n_heads"] == 2.0
    assert geometry.diagnostics["n_heads_lost"] == 1.0
    assert not geometry.observed[cell(15, 0)]


def test_a_head_lands_on_the_nearest_cell_draining_enough() -> None:
    # Row 5 of the axis drains 36 cells; 0.0049 km2 is 49 cells, row 6.
    heads = candidates([(centre(5, AXIS), centre(15, AXIS))])

    geometry = valley_geometry(heads, min_drained_area_m2=4900.0)

    assert geometry.heads is not None
    assert geometry.heads.head_cell.tolist() == [cell(6, AXIS)]
    assert geometry.heads.snap_distance_m[0] == pytest.approx(10.0)
    assert not geometry.observed[cell(5, AXIS)]
