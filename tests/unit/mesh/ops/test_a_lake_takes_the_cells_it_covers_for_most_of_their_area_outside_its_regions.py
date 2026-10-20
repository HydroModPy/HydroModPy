"""A lake owns its closed regions, and the cells outside them it covers for most of their area.

The faces of a generated Voronoi mesh follow the lake shore smoothed at the
cell size, so an arm narrower than a cell lies outside the lake regions. The
cells of that arm the lake covers for more than half still belong to it, as a
whole; a cell it only grazes does not.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, box

from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.ops.family_interior import interior_cells, polygon_overlap
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 330_000.0, 6_780_000.0
BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)
ARM = box(X0 + 700.0, Y0 + 430.0, X0 + 950.0, Y0 + 470.0)


def _mesh_on_the_body_ring():
    domain = box(X0, Y0, X0 + 1200.0, Y0 + 900.0)
    grid = RasterGridSpec(
        xmin=X0,
        xmax=X0 + 1200.0,
        ymin=Y0,
        ymax=Y0 + 900.0,
        dx=10.0,
        dy=10.0,
        nrow=90,
        ncol=120,
        crs_wkt=WKT,
    )
    field = SizeField(np.full((grid.nrow, grid.ncol), 30.0), grid)
    ring = LineString(shapely.normalize(BODY).exterior.coords)
    families = (LineFamilySpec("lakes", "face", (ring,), closed=True),)
    request = MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=30.0,
        lines=resample_families(families, domain=domain, size_field=field).families,
        size_field=field,
    )
    return VoronoiMeshEngine().build(request)


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
