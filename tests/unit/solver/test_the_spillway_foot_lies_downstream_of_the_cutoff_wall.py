"""With a cutoff wall, the foot of the spillway lies downstream of the wall.

The foot was the lowest non-lake neighbour of the shore cell nearest the
discharge point, with no look at the wall: it could fall on a bank beside the
wall or behind it, and the release then entered the aquifer on the lake side.
The wall has the lake on its left, so the foot is taken among the cells on its
right (``downstream_of_wall``), as the HFB and the LAK seal read it.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders import lake as lake_builder
from hydromodpy.solver.modflow6.builders.lake import resolve_spillway_seed_cells

# The wall runs north along x = 15: the lake (x < 15) is on its left.
_WALL = LineString([(15.0, -50.0), (15.0, 50.0)])


def _definitions(wall: LineString | None):
    definition = {"outlets": [{"mover": {"to_downstream_reach": True}}]}
    if wall is not None:
        definition["cutoff_wall_line"] = wall
    return lambda model: {"res": definition}


def _seed(monkeypatch, wall, *, centroids, adjacency, top, lake=(0, 1)) -> dict[str, int]:
    monkeypatch.setattr(lake_builder, "_active_lake_definitions", _definitions(wall))
    return resolve_spillway_seed_cells(
        object(),
        lake_cells_by_id={"res": list(lake)},
        cell_adjacency=adjacency,
        cell_centroids=np.asarray(centroids, dtype=float),
        idomain=np.ones((1, len(top)), dtype=int),
        mesh_top=np.asarray(top, dtype=float),
        outlet_xy=(30.0, 0.0),
    )


# Lake {0, 1}. Shore cell 1 touches cell 2 (a bank on the lake side, x = 10, the
# lowest) and cell 3 (downstream of the wall, x = 20).
_CENTROIDS = [[0, 0], [10, 0], [10, 10], [20, 0]]
_ADJACENCY = [{1}, {0, 2, 3}, {1}, {1}]
_TOP = [100.0, 95.0, 70.0, 80.0]


def test_the_foot_without_a_wall_is_the_lowest_neighbour(monkeypatch) -> None:
    seeds = _seed(monkeypatch, None, centroids=_CENTROIDS, adjacency=_ADJACENCY, top=_TOP)
    assert seeds == {"res": 2}


def test_the_foot_with_a_wall_is_downstream_of_it(monkeypatch) -> None:
    seeds = _seed(monkeypatch, _WALL, centroids=_CENTROIDS, adjacency=_ADJACENCY, top=_TOP)
    assert seeds == {"res": 3}


def test_the_dam_is_the_shore_cell_that_faces_the_wall(monkeypatch) -> None:
    # The shore cell nearest the outlet (cell 1, at x = 12) only touches a bank on
    # the lake side (cell 2). Cell 0 is the one that faces the wall: its toe is 3.
    centroids = [[8, -20], [12, 0], [12, 10], [20, -20]]
    adjacency = [{1, 3}, {0, 2}, {1}, {0}]
    top = [100.0, 95.0, 70.0, 80.0]
    seeds = _seed(monkeypatch, _WALL, centroids=centroids, adjacency=adjacency, top=top)
    assert seeds == {"res": 3}


def test_a_wall_with_no_cell_downstream_on_the_shore_is_refused(monkeypatch) -> None:
    # The only non-lake neighbour is on the lake side: there is no foot below the wall.
    centroids = [[0, 0], [10, 0], [10, 10]]
    adjacency = [{1}, {0, 2}, {1}]
    with pytest.raises(ValueError, match="downstream of the cutoff wall"):
        _seed(monkeypatch, _WALL, centroids=centroids, adjacency=adjacency, top=[100, 95, 70])
