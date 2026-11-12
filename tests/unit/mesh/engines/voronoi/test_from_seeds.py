"""The generated voronoi mesh: the note of an open lake shore and the centers inside their cells.

The lake builder falls back on the overlap rule where the ``lakes`` faces leave
part of a shore open, and the note puts the reason in the mesh QA, where the mesh is
built (fix of 2026-10-20).
"""

from __future__ import annotations

import functools

import numpy as np
import shapely
from shapely.geometry import Polygon, box

from hydromodpy.mesh.engines.voronoi.from_seeds import (
    CLOSED_SHORE_SHARE,
    INWARD_M,
    _inside_their_cells,
)
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from tests._helpers.mesh_cases import L93_ORIGIN, voronoi_lake_mesh

X0, Y0 = L93_ORIGIN
DOMAIN = box(X0, Y0, X0 + 1200.0, Y0 + 900.0)
BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)
ARM = box(X0 + 700.0, Y0 + 445.0, X0 + 950.0, Y0 + 455.0)
"""An arm 10 m wide, narrower than the 30 m cells of the shore."""


@functools.cache
def lake_mesh(lake: Polygon) -> PlanarCellMesh:
    return voronoi_lake_mesh(shapely.normalize(lake), domain=DOMAIN, pixel=10.0, cell_size=30.0)


def lake_notes(cell_mesh: PlanarCellMesh) -> list[str]:
    """The notes the ``lakes`` family adds to the QA."""
    return [note for note in cell_mesh.qa.notes if note.startswith("lakes:")]


def test_arm_narrower_than_a_cell() -> None:
    cell_mesh = lake_mesh(BODY.union(ARM))
    covered = cell_mesh.qa.families["lakes"]["covered_length_rel"]
    (note,) = lake_notes(cell_mesh)

    assert covered < CLOSED_SHORE_SHARE
    assert f"{100.0 * covered:.1f} %" in note


def test_seed_on_the_ring_of_its_cell_is_moved_inside() -> None:
    # A seed added on the domain boundary sits on the ring of its cell. It moves 0.1 um
    # towards the centroid of the cell, here along the diagonal of a 10 m square.
    cells = np.array([box(0.0, 0.0, 10.0, 10.0), box(10.0, 0.0, 20.0, 10.0)], dtype=object)
    seeds = np.array([[0.0, 0.0], [15.0, 5.0]])

    moved = _inside_their_cells(seeds, cells)

    np.testing.assert_allclose(moved[0], [INWARD_M / np.sqrt(2.0)] * 2, rtol=1e-6)
    np.testing.assert_array_equal(moved[1], seeds[1])


def test_seeds_inside_their_cells_stay() -> None:
    cells = np.array([box(0.0, 0.0, 10.0, 10.0)], dtype=object)
    seeds = np.array([[5.0, 5.0]])

    assert _inside_their_cells(seeds, cells) is seeds
