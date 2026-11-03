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

from hydromodpy.spatial.mesh.engines.voronoi.from_seeds import CLOSED_SHORE_SHARE, INWARD_M
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
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


def test_an_arm_narrower_than_a_cell_leaves_the_shore_open_and_the_mesh_says_so() -> None:
    cell_mesh = lake_mesh(BODY.union(ARM))
    covered = cell_mesh.qa.families["lakes"]["covered_length_rel"]
    (note,) = lake_notes(cell_mesh)

    assert covered < CLOSED_SHORE_SHARE
    assert f"{100.0 * covered:.1f} %" in note


def test_a_closed_shore_adds_no_note() -> None:
    cell_mesh = lake_mesh(BODY)
    assert cell_mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert not lake_notes(cell_mesh)


def test_every_cell_centre_lies_inside_its_cell_even_on_the_boundary() -> None:
    cell_mesh = lake_mesh(BODY)
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    rings = cell_mesh.geometry.padded_connectivity
    cells = np.array(
        [Polygon(vertices[ring[ring >= 0]]) for ring in np.asarray(rings, dtype=np.int64)]
    )
    on_ring = shapely.dwithin(
        shapely.get_exterior_ring(cells), shapely.points(cell_mesh.centers), 2.0 * INWARD_M
    )

    assert shapely.contains_xy(cells, *cell_mesh.centers.T).all()
    assert on_ring.any()
