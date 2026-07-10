"""Two lakes clipping the same grid cell are resolved, not rejected.

MF6 LAK allows one vertical lake connection per GWF cell. When two adjacent lakes
each clip the same edge cell across a narrow sill, the cell is reassigned to the
lake it overlaps most (by intersected area) so the footprints stay cell-disjoint.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow6.builders.lake import _resolve_shared_lake_cells


def test_shared_cell_goes_to_the_larger_overlap_lake() -> None:
    cells = {"a": [1, 2, 3], "b": [3, 4, 5]}  # cell 3 claimed by both
    areas = {"a": {1: 10.0, 2: 10.0, 3: 2.0}, "b": {3: 8.0, 4: 10.0, 5: 10.0}}
    _resolve_shared_lake_cells(cells, areas)
    assert cells["a"] == [1, 2]  # dropped from the smaller-overlap lake
    assert cells["b"] == [3, 4, 5]  # kept in the larger-overlap lake


def test_no_shared_cell_is_a_noop() -> None:
    cells = {"a": [1, 2], "b": [3, 4]}
    _resolve_shared_lake_cells(cells, {"a": {}, "b": {}})
    assert cells == {"a": [1, 2], "b": [3, 4]}


def test_raises_when_a_lake_loses_every_cell() -> None:
    cells = {"a": [1], "b": [1, 2]}  # a's only cell is swallowed by b
    areas = {"a": {1: 1.0}, "b": {1: 5.0, 2: 10.0}}
    with pytest.raises(ValueError, match="lost every grid cell"):
        _resolve_shared_lake_cells(cells, areas)
