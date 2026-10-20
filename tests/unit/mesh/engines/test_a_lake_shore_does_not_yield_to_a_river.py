"""A lake shore does not yield to a river that runs beside it.

A river chain seed close to the shore pairs used to take their place, and the
shore lost its faces there. The shore now holds, as a barrier does: the chain
seed goes and the river passes through the cell of a shore pair seed on its own
side, so the chain stays off the lake and unbroken.
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
LAKE = box(X0 + 300.0, Y0 + 300.0, X0 + 900.0, Y0 + 600.0)
RIVER = LineString([(X0 + 400.0, Y0 + 100.0), (X0 + 420.0, Y0 + 290.0), (X0 + 780.0, Y0 + 290.0)])


def _mesh():
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
    field = SizeField(np.full((grid.nrow, grid.ncol), 40.0), grid)
    families = (
        LineFamilySpec("rivers", "cell", (RIVER,)),
        LineFamilySpec(
            "lakes", "face", (LineString(shapely.normalize(LAKE).exterior.coords),), closed=True
        ),
    )
    request = MeshRequest(
        domain=domain,
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=40.0,
        lines=resample_families(families, domain=domain, size_field=field).families,
        size_field=field,
    )
    return VoronoiMeshEngine().build(request)


def test_the_shore_keeps_its_faces_beside_a_river() -> None:
    mesh = _mesh()

    assert mesh.qa.families["lakes"]["covered_length_rel"] > 1.0 - 1e-6
    assert mesh.qa.families["lakes"]["yielded_segments"] == 0.0


def test_the_river_chain_stays_off_the_lake_and_unbroken() -> None:
    mesh = _mesh()
    cells = np.unique(np.concatenate([chain.cell_ids for chain in mesh.chains("rivers")]))

    assert mesh.qa.families["rivers"]["breaks"] == 0.0
    assert not shapely.contains(LAKE, shapely.points(mesh.centers[cells])).any()
