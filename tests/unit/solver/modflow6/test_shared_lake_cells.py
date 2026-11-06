"""Two lakes clipping the same grid cell are resolved, not rejected.

MF6 LAK allows one vertical lake connection per GWF cell. When two adjacent lakes
each clip the same edge cell across a narrow sill, the cell is reassigned to the
lake it overlaps most (by intersected area) so the footprints stay cell-disjoint.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import lake_outflow as lake_builder
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _fill_lake_enclosed_cells,
    _resolve_shared_lake_cells,
)
from hydromodpy.solver.modflow6.builders.lake_outflow import (
    own_lake_upstream_ifnos,
    resolve_downstream_spillway_reaches,
    resolve_spillway_seed_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


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


def _quad_mesh(nrow: int, ncol: int) -> SolverMesh:
    """An nrow x ncol grid of 10 m cells, all active, ids row-major from the north."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.zeros((nrow, ncol)),
        botm=np.full((1, nrow, ncol), -10.0),
        dx=10.0,
        dy=10.0,
    )


def test_fully_lake_enclosed_cell_is_absorbed() -> None:
    # 3x3 grid: the center cell 4 has edge-neighbors {1, 3, 5, 7}, all lake -> absorbed.
    mesh = _quad_mesh(3, 3)
    cells = {"a": [1, 3, 5, 7]}
    areas = {"a": {c: 100.0 for c in (1, 3, 5, 7)}}
    _fill_lake_enclosed_cells(cells, areas, mesh)
    assert 4 in cells["a"]
    assert areas["a"][4] == 100.0


def test_cell_with_an_open_face_is_left_active() -> None:
    # Neighbor 7 is not lake, so the center keeps an active face and is not absorbed.
    mesh = _quad_mesh(3, 3)
    cells = {"a": [1, 3, 5]}
    areas = {"a": {c: 100.0 for c in (1, 3, 5)}}
    _fill_lake_enclosed_cells(cells, areas, mesh)
    assert cells["a"] == [1, 3, 5]


def test_spillway_seed_is_the_lowest_dam_toe_cell(monkeypatch) -> None:
    # Lake {0, 1}; cell 1 is the shoreline (its non-lake active neighbors are 2 and 3).
    # The dam toe is the lowest of them: cell 3 (top 80 < 90).
    monkeypatch.setattr(
        lake_builder,
        "_active_lake_definitions",
        lambda model: {"res": {"outlets": [{"mover": {"to_downstream_reach": True}}]}},
    )
    centroids = np.array([[0, 0], [10, 0], [20, 0], [20, 10], [0, 0]], dtype=float)
    adjacency = [{1}, {0, 2, 3}, {1}, {1}, set()]
    idomain = np.ones((1, 5), dtype=int)
    top = np.array([100.0, 95.0, 90.0, 80.0, 100.0])
    seeds = resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": [0, 1]},
        cell_adjacency=adjacency,
        cell_centroids=centroids,
        idomain=idomain,
        mesh_top=top,
        outlet_xy=(15.0, 0.0),
    )
    assert seeds == {"res": 3}


def test_spillway_seed_uses_explicit_discharge_xy(monkeypatch) -> None:
    # An explicit discharge_xy at (0, 0) locates the dam there, overriding the domain
    # outlet at (20, 0): the seed is the toe of shoreline cell 0 (cell 3), not cell 4.
    monkeypatch.setattr(
        lake_builder,
        "_active_lake_definitions",
        lambda model: {
            "res": {
                "outlets": [{"mover": {"to_downstream_reach": True, "discharge_xy": [0.0, 0.0]}}]
            }
        },
    )
    centroids = np.array([[0, 0], [10, 0], [20, 0], [0, 10], [20, 10]], dtype=float)
    adjacency = [{1, 3}, {0, 2}, {1, 4}, {0}, {2}]
    idomain = np.ones((1, 5), dtype=int)
    top = np.array([90.0, 95.0, 90.0, 80.0, 80.0])
    seeds = resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": [0, 1, 2]},
        cell_adjacency=adjacency,
        cell_centroids=centroids,
        idomain=idomain,
        mesh_top=top,
        outlet_xy=(20.0, 0.0),
    )
    assert seeds == {"res": 3}


def test_spillway_receiver_is_the_reach_on_the_toe_seed() -> None:
    # The dam-toe seed cell 2 is itself a reach after the rectification -> exact receiver.
    centroids = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], dtype=float)
    resolved = resolve_downstream_spillway_reaches(
        {"res": 2}, reach_cell_to_ifno={2: 10, 3: 20}, cell_centroids=centroids
    )
    assert resolved == {"res": 10}


def test_spillway_without_a_reach_on_the_toe_seed_raises() -> None:
    """No silent fallback on the nearest reach: it can be a tributary of the lake.

    On the Cheze the nearest reach to the toe sat 2.8 km away and fed the reservoir
    again, so 99 % of a configured release came back into it.
    """
    centroids = np.array([[0, 0], [10, 0], [20, 0], [40, 0]], dtype=float)
    with pytest.raises(ValueError, match="rectify_on_mesh"):
        resolve_downstream_spillway_reaches(
            {"res": 1}, reach_cell_to_ifno={2: 10, 3: 20}, cell_centroids=centroids
        )


def test_own_lake_upstream_reaches_cover_the_whole_catchment_of_the_lake() -> None:
    """Terminal labels are 1-based; the forbidden set holds every reach draining to the lake."""
    from types import SimpleNamespace as NS

    reaches = [
        NS(ifno=0, upstream=(), is_terminal_to_lake=False, terminal_lake=None),
        NS(ifno=1, upstream=(0,), is_terminal_to_lake=True, terminal_lake=1),
        NS(ifno=2, upstream=(), is_terminal_to_lake=False, terminal_lake=None),
        NS(ifno=3, upstream=(2,), is_terminal_to_lake=True, terminal_lake=2),
        NS(ifno=4, upstream=(), is_terminal_to_lake=False, terminal_lake=None),
    ]
    network = NS(reaches=reaches)
    forbidden = own_lake_upstream_ifnos({"a": network}, lake_ids=["res", "forebay"])
    assert forbidden == {"res": {0, 1}, "forebay": {2, 3}}


def test_spillway_fallback_allows_a_feeder_of_another_lake() -> None:
    """A cascade stays legal: a forebay may spill into a reach feeding the main lake."""
    centroids = np.array([[0, 0], [10, 0], [20, 0], [40, 0]], dtype=float)
    resolved = resolve_downstream_spillway_reaches(
        {"forebay": 2},
        reach_cell_to_ifno={2: 10, 3: 20},
        cell_centroids=centroids,
        own_lake_terminal_ifnos={"forebay": set(), "main": {10}},
    )
    assert resolved == {"forebay": 10}


def test_spillway_exact_hit_on_own_feeder_raises() -> None:
    """A mid-basin lake whose toe reach feeds it back is refused, not silently wired."""
    centroids = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], dtype=float)
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        resolve_downstream_spillway_reaches(
            {"res": 2},
            reach_cell_to_ifno={2: 10, 3: 20},
            cell_centroids=centroids,
            own_lake_terminal_ifnos={"res": {10}},
        )
