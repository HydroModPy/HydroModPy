"""The heads rule: where a mapped network starts a stream, and what the criterion draws from it.

The heads rule keeps only where the map starts a stream and lets the model's own
descent draw the rest, on a V valley (``_heads_valley``) and on a valley holding a
lake whose lowest rim is a saddle (``_heads_dam``). Which end of a reach is upstream
is read on the criterion graph, by the drained area; a head with no landing cell
within the snap radius is lost; a forced cell is traced as it is and counted apart.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.network_heads import HeadCandidates
from hydromodpy.results.derive.stream import geometry as stream_geometry
from hydromodpy.results.derive.stream.geometry import build_network_geometry
from hydromodpy.results.derive.stream.heads import concat_candidates
from tests.unit.results.stream import _heads_dam as dam
from tests.unit.results.stream._heads_valley import (
    AXIS,
    N_ROWS,
    candidates,
    cell,
    centre,
    valley_geometry,
)


def test_the_descent_leaves_through_the_saddle_and_misses_the_dam_foot() -> None:
    geometry = dam.dam_geometry()

    foot = dam.cell(dam.DAM_FOOT_ROW, dam.AXIS)
    assert not geometry.observed[foot]
    assert geometry.observed[dam.cell(8, dam.AXIS)]
    assert geometry.observed[dam.cell(12, 8)]
    assert geometry.diagnostics["n_forced_heads"] == 0.0


def test_forcing_the_dam_foot_draws_the_reach_below_the_dam() -> None:
    foot = dam.cell(dam.DAM_FOOT_ROW, dam.AXIS)

    geometry = dam.dam_geometry([foot])

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
    plain = dam.dam_geometry()
    forced = dam.dam_geometry([dam.cell(dam.DAM_FOOT_ROW, dam.AXIS)])

    assert not (plain.observed & ~forced.observed).any()
    assert int(forced.observed.sum()) > int(plain.observed.sum())


HILLSIDE = cell(20, 3)


def _axis_head() -> HeadCandidates:
    return candidates([(centre(2, AXIS), centre(N_ROWS - 1, AXIS))])


def test_a_forced_cell_is_traced_to_the_outlet_and_counted_apart() -> None:
    plain = valley_geometry(_axis_head())
    forced = valley_geometry(replace(_axis_head(), forced_cells=np.asarray([HILLSIDE])))

    assert not plain.observed[HILLSIDE]
    assert forced.observed[HILLSIDE]
    downstream = forced.metric.graph.downstream
    walk = HILLSIDE
    while walk >= 0:
        assert forced.observed[walk]
        walk = int(downstream[walk])
    assert forced.heads is not None
    assert forced.heads.forced_cell.tolist() == [HILLSIDE]
    assert forced.diagnostics["n_forced_heads"] == 1.0
    assert forced.diagnostics["n_heads"] == 1.0
    assert plain.diagnostics["n_forced_heads"] == 0.0


def test_a_forced_cell_does_not_save_a_map_whose_heads_are_all_lost() -> None:
    # No cell drains 1 km2 on this valley: the free end is lost, the map is refused.
    heads = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE]))

    with pytest.raises(ValueError, match="every one of the 1 head"):
        valley_geometry(heads, min_drained_area_m2=1.0e6)


def test_a_forced_cell_does_not_save_a_map_whose_ends_all_drain_more_than_their_reach() -> None:
    # The head sits below the other end of its reach: it drains more, so it is no head.
    inverted = candidates([(centre(N_ROWS - 1, AXIS), centre(2, AXIS))])
    heads = replace(inverted, forced_cells=np.asarray([HILLSIDE]))

    with pytest.raises(ValueError, match="drains more than the other end"):
        valley_geometry(heads)


def test_a_map_with_no_free_end_is_refused_whatever_its_forced_cells() -> None:
    heads = replace(candidates([]), forced_cells=np.asarray([HILLSIDE]))

    with pytest.raises(ValueError, match="holds no free end"):
        valley_geometry(heads)


def test_a_forced_cell_off_the_mesh_is_dropped() -> None:
    heads = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, -1, 10**6]))

    geometry = valley_geometry(heads)

    assert geometry.heads is not None
    assert geometry.heads.forced_cell.tolist() == [HILLSIDE]


def test_a_forced_cell_off_the_graph_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    heads = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, 10**6]))

    with caplog.at_level("INFO", logger="hydromodpy.results.derive.stream.heads"):
        valley_geometry(heads)

    assert "1 of 2 forced head(s) dropped" in caplog.text


def test_no_free_end_and_no_forced_cell_still_refuses() -> None:
    with pytest.raises(ValueError, match="draws no stream from its heads"):
        valley_geometry(candidates([]))


def test_two_maps_keep_each_forced_cell_once() -> None:
    first = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, 5]))
    second = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, 9]))

    merged = concat_candidates(first, second)

    assert merged.forced_cells.tolist() == [5, 9, HILLSIDE]


def test_a_free_downstream_end_is_not_a_head() -> None:
    head, outlet_end = centre(5, AXIS), centre(N_ROWS - 1, AXIS)
    # Listed outlet first, as a line digitized against the flow would be.
    heads = candidates([(outlet_end, head), (head, outlet_end)])

    geometry = valley_geometry(heads)

    assert geometry.heads is not None
    assert geometry.heads.n_candidates == 2
    np.testing.assert_allclose(geometry.heads.head_xy, [head])


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

    with caplog.at_level("WARNING", logger="hydromodpy.results.derive.stream.geometry"):
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


def test_a_source_both_maps_draw_is_one_head() -> None:
    shared, other = centre(5, AXIS), centre(8, AXIS + 4)
    outlet_end = centre(N_ROWS - 1, AXIS)
    maximal = candidates([(shared, outlet_end), (other, outlet_end)])
    minimal = candidates([(shared, outlet_end)])

    union = concat_candidates(maximal, minimal)

    assert union.n_candidates == 2
    np.testing.assert_allclose(union.head_xy, [shared, other])


def test_a_tie_between_both_ends_keeps_the_head() -> None:
    head, reach_end = centre(N_ROWS - 3, AXIS + 2), centre(N_ROWS - 2, AXIS + 1)

    geometry = valley_geometry(candidates([(head, reach_end)]), snap_radius_m=50.0)

    assert geometry.heads is not None
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
    assert geometry.observed[cell(N_ROWS - 1, AXIS)]


def test_every_head_lost_raises_naming_the_radius_and_the_area() -> None:
    heads = candidates([((-200.0, 155.0), centre(15, AXIS))])

    with pytest.raises(ValueError, match=r"snap radius 100 m.*0\.02 km2"):
        valley_geometry(heads, min_drained_area_m2=2.0e4)


def test_a_map_with_only_a_downstream_end_raises() -> None:
    heads = candidates([(centre(N_ROWS - 1, AXIS), centre(5, AXIS))])

    with pytest.raises(ValueError, match="1 free end"):
        valley_geometry(heads)


def test_the_geometry_takes_exactly_one_map() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        build_network_geometry(
            topography=[1.0],
            face_node_connectivity=[[0, 1, 2, 3]],
            vertices=[[0, 0], [1, 0], [1, 1], [0, 1]],
            cell_area_m2=[1.0],
            mean_recharge_m_s=0.0,
            tau_specific_ratio=0.0,
        )


def test_two_heads_draw_one_connected_chain_to_the_outlet() -> None:
    junction = centre(15, AXIS)
    # The axis reach from row 2, and a tributary from the west hillside.
    heads = candidates(
        [
            (centre(2, AXIS), junction),
            (centre(15, 3), junction),
            (centre(N_ROWS - 1, AXIS), junction),
        ]
    )

    geometry = valley_geometry(heads)

    drawn = geometry.observed
    downstream = geometry.metric.graph.downstream
    assert drawn[geometry.outlet]
    assert drawn[cell(2, AXIS)] and drawn[cell(15, 3)]
    # Every drawn cell drains into a drawn cell, or leaves the domain.
    receivers = downstream[drawn]
    assert np.all((receivers < 0) | drawn[np.maximum(receivers, 0)])
    # Exactly two drawn cells have no drawn cell upstream: the two heads.
    fed = np.zeros(drawn.size, dtype=bool)
    fed[receivers[receivers >= 0]] = True
    assert int(np.count_nonzero(drawn & ~fed)) == 2
    assert geometry.heads is not None
    assert geometry.diagnostics["n_heads"] == 2.0
    assert geometry.diagnostics["n_heads_lost"] == 0.0
    assert geometry.diagnostics["head_snap_p90_m"] == 0.0
