"""The reach below a dam is drawn when the foot of the dam is forced.

The water of the criterion leaves the reservoir through its lowest rim cell. On
this bench that is a saddle east of the dam wall, so the descent of the head
above the lake reaches the axis only at row 14 and never touches the cell at the
foot of the dam. The stream below a dam starts at the dam: forcing that cell as a
head draws the reach between the dam and the point where the saddle path joins.
"""

from __future__ import annotations

from tests.unit.core._heads_dam import AXIS, DAM_FOOT_ROW, cell, dam_geometry


def test_the_descent_leaves_through_the_saddle_and_misses_the_dam_foot() -> None:
    geometry = dam_geometry()

    foot = cell(DAM_FOOT_ROW, AXIS)
    assert not geometry.observed[foot]
    assert geometry.observed[cell(8, AXIS)]
    assert geometry.observed[cell(12, 8)]
    assert geometry.diagnostics["n_forced_heads"] == 0.0


def test_forcing_the_dam_foot_draws_the_reach_below_the_dam() -> None:
    foot = cell(DAM_FOOT_ROW, AXIS)

    geometry = dam_geometry([foot])

    assert geometry.observed[foot]
    downstream = geometry.metric.graph.downstream
    walk = foot
    while walk >= 0:
        assert geometry.observed[walk]
        walk = int(downstream[walk])
    assert geometry.observed[geometry.outlet]
    assert geometry.heads is not None
    assert geometry.heads.forced_cell.tolist() == [foot]
    assert geometry.diagnostics["n_forced_heads"] == 1.0
    assert geometry.diagnostics["n_heads"] == 1.0


def test_forcing_the_dam_foot_keeps_the_trace_the_map_drew() -> None:
    plain = dam_geometry()
    forced = dam_geometry([cell(DAM_FOOT_ROW, AXIS)])

    assert not (plain.observed & ~forced.observed).any()
    assert int(forced.observed.sum()) > int(plain.observed.sum())
