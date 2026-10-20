"""The voronoi engine says so when its lake faces leave part of a shore open.

The lake builder then falls back on the overlap rule; the note puts the reason
in the mesh QA, where the mesh is built.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, box

from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 330_000.0, 6_780_000.0
BODY = box(X0 + 300.0, Y0 + 300.0, X0 + 700.0, Y0 + 600.0)


def _mesh(lake) -> object:
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
    ring = LineString(shapely.normalize(lake).exterior.coords)
    families = (LineFamilySpec("lakes", "face", (ring,), closed=True),)
    return VoronoiMeshEngine().build(
        MeshRequest(
            domain=domain,
            crs_wkt=WKT,
            grid=grid,
            nominal_size_m=30.0,
            lines=resample_families(families, domain=domain, size_field=field).families,
            size_field=field,
        )
    )


def test_an_arm_narrower_than_a_cell_leaves_the_shore_open_and_the_mesh_says_so() -> None:
    mesh = _mesh(BODY.union(box(X0 + 700.0, Y0 + 445.0, X0 + 950.0, Y0 + 455.0)))

    assert mesh.qa.families["lakes"]["covered_length_rel"] < 1.0 - 1e-6
    assert any("the lake regions stay open" in note for note in mesh.qa.notes)


def test_a_closed_shore_adds_no_note() -> None:
    mesh = _mesh(BODY)

    assert mesh.qa.families["lakes"]["covered_length_rel"] >= 1.0 - 1e-6
    assert not any("stay open" in note for note in mesh.qa.notes)
