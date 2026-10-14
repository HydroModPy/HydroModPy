"""A shore the generated mesh follows only in part is resolved by overlap, not refused.

The voronoi engine yields a shore segment where a lake arm is narrower than a
cell, so the ``lakes`` faces no longer enclose the lake. The regions they bound
then stand for nothing, and the lake owns the cells its polygon overlaps.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.solver.modflow6.builders.lake import resolve_lake_cells
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 350_000.0, 6_780_000.0
CELL_M = 40.0
_AREA_RTOL = 1e-6


def _lake(*points: tuple[float, float]) -> Polygon:
    return Polygon([(X0 + x, Y0 + y) for x, y in points])


SQUARE = _lake((300, 300), (700, 300), (700, 700), (300, 700))
WITH_ARM = _lake(
    (300, 300), (700, 300), (700, 500), (950, 500), (950, 512), (700, 512), (700, 700), (300, 700)
)


def _mesh(lake: Polygon) -> PlanarCellMesh:
    domain = box(X0, Y0, X0 + 1000.0, Y0 + 1000.0)
    grid = RasterGridSpec(
        xmin=X0,
        xmax=X0 + 1000.0,
        ymin=Y0,
        ymax=Y0 + 1000.0,
        dx=20.0,
        dy=20.0,
        nrow=50,
        ncol=50,
        crs_wkt=WKT,
    )
    field = SizeField(np.full((grid.nrow, grid.ncol), CELL_M), grid)
    shore = (LineFamilySpec("lakes", "face", (LineString(lake.exterior.coords),), closed=True),)
    return registry.create("voronoi").build(
        MeshRequest(
            domain=domain,
            crs_wkt=WKT,
            grid=grid,
            nominal_size_m=CELL_M,
            lines=resample_families(shore, domain=domain, size_field=field).families,
            size_field=field,
        )
    )


def test_a_shore_followed_whole_gives_whole_cells() -> None:
    mesh = _mesh(SQUARE)
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=SQUARE, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] == pytest.approx(1.0)
    np.testing.assert_array_equal([areas[c] for c in cells], mesh.geometry.areas[cells])
    assert sum(areas.values()) == pytest.approx(SQUARE.area, rel=_AREA_RTOL)


def test_a_shore_followed_in_part_is_resolved_by_overlap() -> None:
    mesh = _mesh(WITH_ARM)
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=WITH_ARM, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] < 0.99
    assert cells
    assert sum(areas.values()) == pytest.approx(WITH_ARM.area, rel=_AREA_RTOL)
