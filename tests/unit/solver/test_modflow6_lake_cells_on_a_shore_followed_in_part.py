"""A shore the generated mesh follows only in part is resolved by overlap, not refused.

The voronoi engine yields a shore segment where a lake arm is narrower than a
cell, so the ``lakes`` faces no longer enclose the lake. The regions they bound
then stand for nothing, and the lake owns the cells its polygon overlaps.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders.lake import resolve_lake_cells
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.mesh_cases import L93_ORIGIN, square_domain, voronoi_lake_mesh

X0, Y0 = L93_ORIGIN
CELL_M = 40.0
_AREA_RTOL = 1e-6


def _lake(*points: tuple[float, float]) -> Polygon:
    return Polygon([(X0 + x, Y0 + y) for x, y in points])


SQUARE = _lake((300, 300), (700, 300), (700, 700), (300, 700))
WITH_ARM = _lake(
    (300, 300), (700, 300), (700, 500), (950, 500), (950, 512), (700, 512), (700, 700), (300, 700)
)


def _mesh(lake: Polygon) -> PlanarCellMesh:
    domain = square_domain(1000.0, x0=X0, y0=Y0)
    return voronoi_lake_mesh(lake, domain=domain, pixel=20.0, cell_size=CELL_M)


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
