"""A lake owns its closed regions, and the cells outside them it covers for most of their area.

The faces of a generated Voronoi mesh follow the lake shore smoothed at the
cell size, so an arm narrower than a cell lies outside the lake regions. The
cells of that arm the lake covers for more than half still belong to it, as a
whole; a cell it only grazes does not.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import box

from hydromodpy.spatial.mesh.ops.family_interior import (
    family_regions,
    interior_cells,
    polygon_overlap,
)
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh, voronoi_lake_mesh

X0, Y0 = L93_ORIGIN
BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)
ARM = box(X0 + 700.0, Y0 + 430.0, X0 + 950.0, Y0 + 470.0)


def _mesh_on_the_body_ring():
    """The Voronoi mesh of a 1.2 x 0.9 km domain whose faces follow the body of the lake."""
    return voronoi_lake_mesh(
        shapely.normalize(BODY),
        domain=box(X0, Y0, X0 + 1200.0, Y0 + 900.0),
        pixel=10.0,
        cell_size=30.0,
    )


def test_the_arm_cells_the_lake_covers_for_most_of_their_area_join_it() -> None:
    mesh = _mesh_on_the_body_ring()
    lake = BODY.union(ARM)
    cells = interior_cells(mesh, "lakes", lake)
    overlap_cells, overlap = polygon_overlap(mesh, lake)
    share = np.zeros(mesh.n_cells)
    share[overlap_cells] = overlap / mesh.geometry.areas[overlap_cells]
    in_arm = shapely.contains(ARM.buffer(1.0), shapely.points(mesh.centers))

    assert mesh.qa.families["lakes"]["covered_length_rel"] > 1.0 - 1e-6
    assert np.any(in_arm & (share > 0.5))
    assert set(np.flatnonzero(in_arm & (share > 0.5)).tolist()) <= set(cells.tolist())
    outside_body = cells[~shapely.contains(BODY, shapely.points(mesh.centers[cells]))]
    assert np.all(share[outside_body] > 0.5)


def test_a_lake_off_every_region_still_owns_nothing() -> None:
    mesh = _mesh_on_the_body_ring()

    assert interior_cells(mesh, "lakes", ARM).size == 0


def test_a_mesh_without_the_family_is_one_region() -> None:
    grid = regular_mesh(3, 4, dx=10.0)

    assert family_regions(grid, "lakes").tolist() == [0] * grid.n_cells
    cells, overlap = polygon_overlap(grid, box(0.0, 0.0, 15.0, 30.0))
    assert cells.tolist() == [0, 1, 4, 5, 8, 9]
    np.testing.assert_allclose(overlap, [100.0, 50.0] * 3)
