"""On triangles whose faces follow the lake shores, a lake owns whole cells and no sliver.

The triangle engine embeds each lake ring as a ``lakes`` face family, so the
mesh splits into regions along the shores. A lake then owns the regions its
polygon covers, each cell with its whole area: the cells tile the lake, their
areas add up to its area, and no cell reaches outside it. An island ring keeps
its cells out of the lake unless the lake fills its enclosed cells. A lake
whose shore was not meshed is refused rather than resolved by overlap.
"""

from __future__ import annotations

from importlib.util import find_spec

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Polygon

from hydromodpy.solver.modflow6.builders.lake import _drop_interior_rings, resolve_lake_cells
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.geometry import cell_polygons
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import LineFamilySpec
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, mesh_request

pytestmark = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

X0, Y0 = L93_ORIGIN
_AREA_RTOL = 1e-9


def _p(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


LAKE = Polygon([_p(150, 150), _p(420, 120), _p(480, 380), _p(300, 470), _p(130, 340)])
ATOLL = Polygon(
    [_p(580, 560), _p(900, 600), _p(860, 900), _p(600, 870)],
    holes=[[_p(680, 680), _p(790, 690), _p(780, 790), _p(690, 780)]],
)
UNMESHED = Polygon([_p(600, 100), _p(800, 120), _p(760, 300), _p(620, 280)])


def _rings(polygon: Polygon) -> list[LineString]:
    return [LineString(polygon.exterior.coords)] + [
        LineString(ring.coords) for ring in polygon.interiors
    ]


def _triangles(*, with_shores: bool) -> PlanarCellMesh:
    lines = ()
    if with_shores:
        rings = (*_rings(LAKE), *_rings(ATOLL))
        lines = (LineFamilySpec("lakes", "face", rings, closed=True),)
    return registry.create("triangle").build(
        mesh_request(
            grid_spec(40, 40, 25.0, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
            nominal_size_m=60.0,
            lines=lines,
        )
    )


@pytest.fixture(scope="module")
def shores() -> PlanarCellMesh:
    return _triangles(with_shores=True)


def _cells_inside(cell_mesh: PlanarCellMesh, cells: list[int], polygon: Polygon) -> bool:
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    return bool(np.all(shapely.covered_by(polygons[cells], polygon.buffer(1e-6))))


def test_a_lake_owns_whole_cells_that_tile_it(shores: PlanarCellMesh) -> None:
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=LAKE, cell_mesh=shores, with_areas=True
    )
    assert _cells_inside(shores, cells, LAKE)
    np.testing.assert_array_equal([areas[c] for c in cells], shores.geometry.areas[cells])
    assert sum(areas.values()) == pytest.approx(LAKE.area, rel=_AREA_RTOL)


def test_the_overlap_rule_adds_slivers_where_no_shore_was_meshed() -> None:
    plain = _triangles(with_shores=False)
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=LAKE, cell_mesh=plain, with_areas=True
    )
    assert not _cells_inside(plain, cells, LAKE)
    assert sum(areas.values()) == pytest.approx(LAKE.area, rel=_AREA_RTOL)


def test_an_island_stays_out_unless_the_lake_fills_it(shores: PlanarCellMesh) -> None:
    kept = resolve_lake_cells(None, lake_id="atoll", polygon=ATOLL, cell_mesh=shores)
    filled, areas = resolve_lake_cells(
        None,
        lake_id="atoll",
        polygon=_drop_interior_rings(ATOLL),
        cell_mesh=shores,
        with_areas=True,
    )
    island = Polygon(ATOLL.interiors[0])
    assert _cells_inside(shores, kept, ATOLL)
    assert set(kept) < set(filled)
    assert _cells_inside(shores, sorted(set(filled) - set(kept)), island)
    assert sum(areas.values()) == pytest.approx(Polygon(ATOLL.exterior).area, rel=_AREA_RTOL)


def test_a_lake_whose_shore_was_not_meshed_is_refused(shores: PlanarCellMesh) -> None:
    with pytest.raises(ValueError, match="encloses no region of the lakes faces"):
        resolve_lake_cells(None, lake_id="pond", polygon=UNMESHED, cell_mesh=shores)
