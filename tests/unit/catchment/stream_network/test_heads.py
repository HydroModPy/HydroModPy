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
from hydromodpy.catchment.stream_network import geometry as stream_geometry
from hydromodpy.catchment.stream_network.geometry import build_network_geometry
from hydromodpy.catchment.stream_network.heads import concat_candidates
from tests.unit.catchment.stream_network._heads_valley import (
    AXIS,
    N_ROWS,
    candidates,
    cell,
    centre,
    valley_geometry,
)

HILLSIDE = cell(20, 3)


def _axis_head() -> HeadCandidates:
    return candidates([(centre(2, AXIS), centre(N_ROWS - 1, AXIS))])


def test_forced_cell_off_the_mesh_is_dropped() -> None:
    heads = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, -1, 10**6]))

    geometry = valley_geometry(heads)

    assert geometry.heads is not None
    assert geometry.heads.forced_cell.tolist() == [HILLSIDE]


def test_forced_cell_off_the_graph_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    heads = replace(_axis_head(), forced_cells=np.asarray([HILLSIDE, 10**6]))

    with caplog.at_level("INFO", logger="hydromodpy.catchment.stream_network.heads"):
        valley_geometry(heads)

    assert "1 of 2 forced head(s) dropped" in caplog.text


def test_downstream_end_is_not_a_head() -> None:
    head, outlet_end = centre(5, AXIS), centre(N_ROWS - 1, AXIS)
    # Listed outlet first, as a line digitized against the flow would be.
    heads = candidates([(outlet_end, head), (head, outlet_end)])

    geometry = valley_geometry(heads)

    assert geometry.heads is not None
    assert geometry.heads.n_candidates == 2
    np.testing.assert_allclose(geometry.heads.head_xy, [head])


def test_head_beyond_the_radius_is_lost() -> None:
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


def test_lost_head_warns_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream_geometry, "_heads_lost_warned", False)
    junction = centre(15, AXIS)
    heads = candidates([(centre(5, AXIS), junction), ((-200.0, 155.0), junction)])

    with caplog.at_level("WARNING", logger="hydromodpy.catchment.stream_network.geometry"):
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


def test_head_lands_on_draining_cell() -> None:
    # Row 5 of the axis drains 36 cells; 0.0049 km2 is 49 cells, row 6.
    heads = candidates([(centre(5, AXIS), centre(15, AXIS))])

    geometry = valley_geometry(heads, min_drained_area_m2=4900.0)

    assert geometry.heads is not None
    assert geometry.heads.head_cell.tolist() == [cell(6, AXIS)]
    assert geometry.heads.snap_distance_m[0] == pytest.approx(10.0)
    assert not geometry.observed[cell(5, AXIS)]


def test_shared_source_is_one_head() -> None:
    shared, other = centre(5, AXIS), centre(8, AXIS + 4)
    outlet_end = centre(N_ROWS - 1, AXIS)
    maximal = candidates([(shared, outlet_end), (other, outlet_end)])
    minimal = candidates([(shared, outlet_end)])

    union = concat_candidates(maximal, minimal)

    assert union.n_candidates == 2
    np.testing.assert_allclose(union.head_xy, [shared, other])


def test_tie_between_ends_keeps_the_head() -> None:
    head, reach_end = centre(N_ROWS - 3, AXIS + 2), centre(N_ROWS - 2, AXIS + 1)

    geometry = valley_geometry(candidates([(head, reach_end)]), snap_radius_m=50.0)

    assert geometry.heads is not None
    np.testing.assert_allclose(geometry.heads.head_xy, [head])
    assert geometry.observed[cell(N_ROWS - 1, AXIS)]


def test_geometry_takes_one_map() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        build_network_geometry(
            topography=[1.0],
            face_node_connectivity=[[0, 1, 2, 3]],
            vertices=[[0, 0], [1, 0], [1, 1], [0, 1]],
            cell_area_m2=[1.0],
            mean_recharge_m_s=0.0,
            tau_specific_ratio=0.0,
        )


# The head sits below the other end of its reach, so it drains more and is no head.
INVERTED = candidates([(centre(N_ROWS - 1, AXIS), centre(2, AXIS))])

# (heads, valley options, the message). No cell drains 1 km2 on this valley.
REFUSED_MAPS = [
    pytest.param(
        replace(_axis_head(), forced_cells=np.asarray([HILLSIDE])),
        {"min_drained_area_m2": 1.0e6},
        "every one of the 1 head",
        id="forced cell, every head lost",
    ),
    pytest.param(
        replace(INVERTED, forced_cells=np.asarray([HILLSIDE])),
        {},
        "drains more than the other end",
        id="forced cell, ends drain more than their reach",
    ),
    pytest.param(
        replace(candidates([]), forced_cells=np.asarray([HILLSIDE])),
        {},
        "holds no free end",
        id="forced cell, no free end",
    ),
    pytest.param(candidates([]), {}, "draws no stream from its heads", id="nothing at all"),
    pytest.param(INVERTED, {}, "1 free end", id="only a downstream end"),
]


@pytest.mark.parametrize(("heads", "options", "match"), REFUSED_MAPS)
def test_refusals(heads, options, match) -> None:
    with pytest.raises(ValueError, match=match):
        valley_geometry(heads, **options)
