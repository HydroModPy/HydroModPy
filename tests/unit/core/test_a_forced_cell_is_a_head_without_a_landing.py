"""A forced cell is traced as a head, as it is, and counted apart.

The foot of a dam is already a cell: no window reads its drained area, no
landing rule moves it, and nothing can lose it. On the V valley a hillside cell
stands for it, with a drained-area floor no cell of the map's own head meets.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.core.stream_heads import HeadCandidates, concat_candidates
from tests.unit.core._heads_valley import AXIS, N_ROWS, candidates, cell, centre, valley_geometry

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

    with caplog.at_level("INFO", logger="hydromodpy.core.stream_heads"):
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
