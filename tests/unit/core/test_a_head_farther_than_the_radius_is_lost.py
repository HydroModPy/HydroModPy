"""A head with no landing cell within the snap radius is lost and draws nothing."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core import stream_geometry
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


def test_a_lost_head_warns_once_with_what_to_check(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream_geometry, "_heads_lost_warned", False)
    junction = centre(15, AXIS)
    heads = candidates([(centre(5, AXIS), junction), ((-200.0, 155.0), junction)])

    with caplog.at_level("WARNING", logger="hydromodpy.core.stream_geometry"):
        valley_geometry(heads, snap_radius_m=100.0)
        valley_geometry(heads, snap_radius_m=100.0)

    warned = [
        record.getMessage()
        for record in caplog.records
        if "landed on no cell" in record.getMessage()
    ]
    assert len(warned) == 1
    assert "1 of 2 head(s)" in warned[0]
    assert "map.heads.radius" in warned[0]


def test_a_head_lands_on_the_nearest_cell_draining_enough() -> None:
    # Row 5 of the axis drains 36 cells; 0.0049 km2 is 49 cells, row 6.
    heads = candidates([(centre(5, AXIS), centre(15, AXIS))])

    geometry = valley_geometry(heads, min_drained_area_m2=4900.0)

    assert geometry.heads is not None
    assert geometry.heads.head_cell.tolist() == [cell(6, AXIS)]
    assert geometry.heads.snap_distance_m[0] == pytest.approx(10.0)
    assert not geometry.observed[cell(5, AXIS)]
