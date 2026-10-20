"""A generated Voronoi mesh follows each lake shore at its cell size, and closes it.

The mesh lays one mirror pair on each shore segment. A river chain in the lake,
an arm narrower than a cell, or a wall wing of a few metres take or shrink those
pairs and open the lake regions. The planner keeps the rivers half a river cell
off the lakes, gives the mesh the shore smoothed at the cell scale, and leaves
out a wall wing no cell resolves. A cell of an arm left out still joins its
lake when the lake covers most of it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.voronoi.generated import CLOSED_SHORE_SHARE
from hydromodpy.spatial.mesh.ops.family_interior import interior_cells, polygon_overlap
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import RIVER_MARGIN_SHARE, plan_mesh_request
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, RasterGridSpec

_WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 330_000.0, 6_780_000.0
_DOMAIN = box(X0, Y0, X0 + 1600.0, Y0 + 1000.0)
_GRID = RasterGridSpec(
    xmin=X0,
    xmax=X0 + 1600.0,
    ymin=Y0,
    ymax=Y0 + 1000.0,
    dx=10.0,
    dy=10.0,
    nrow=100,
    ncol=160,
    crs_wkt=_WKT,
)
_BODY = box(X0 + 400.0, Y0 + 350.0, X0 + 1100.0, Y0 + 650.0)
_ARM = box(X0 + 1100.0, Y0 + 494.0, X0 + 1400.0, Y0 + 506.0)
_RIVER = LineString([(X0, Y0 + 480.0), (X0 + 1600.0, Y0 + 520.0)])
_CONFIG = MeshConfig(
    engine="voronoi", cell_size=60.0, river_cell_size=30.0, lake_refinement={"cell_size": 30.0}
)


def _inputs(lake: Polygon, *, river: bool = False, barriers=()) -> PlanningInputs:
    return PlanningInputs(
        dem_grid=_GRID,
        crs_wkt=_WKT,
        domain=_DOMAIN,
        river_trace=SimpleNamespace(lines=(_RIVER,)) if river else None,
        watershed=None,
        lakes=(lake,),
        lake_structures=(),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=True,
        barriers=tuple(barriers),
    )


def _build(inputs: PlanningInputs, config: MeshConfig = _CONFIG):
    request = plan_mesh_request(config, inputs)
    return request, registry.create(config.engine).build(request)


def _family(request, name: str):
    return next(family for family in request.lines if family.name == name)


def test_a_river_through_the_lake_leaves_the_shore_closed() -> None:
    request, mesh = _build(_inputs(_BODY, river=True))

    rivers = shapely.multilinestrings(list(_family(request, "rivers").lines))
    assert not rivers.intersects(_BODY.buffer(0.5 * RIVER_MARGIN_SHARE * 30.0))
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert mesh.chains("rivers")


def test_an_arm_narrower_than_a_cell_is_left_out_and_the_shore_closes() -> None:
    lake = _BODY.union(_ARM)
    request, mesh = _build(_inputs(lake))

    ring = shapely.multilinestrings(list(_family(request, "lakes").lines))
    assert ring.distance(shapely.Point(X0 + 1350.0, Y0 + 500.0)) > 100.0
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert any("smoothed" in note and "left out" in note for note in request.notes)


def test_the_cells_of_an_arm_left_out_join_the_lake_when_it_covers_most_of_them() -> None:
    lake = _BODY.union(box(X0 + 1100.0, Y0 + 480.0, X0 + 1400.0, Y0 + 520.0))
    _, mesh = _build(_inputs(lake))
    cells = interior_cells(mesh, "lakes", lake)
    overlap_cells, overlap = polygon_overlap(mesh, lake)
    share = np.zeros(mesh.n_cells)
    share[overlap_cells] = overlap / mesh.geometry.areas[overlap_cells]
    centres = shapely.points(mesh.centers[cells])

    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert np.any(shapely.contains(box(X0 + 1150.0, Y0 + 470.0, X0 + 1400.0, Y0 + 530.0), centres))
    majority = np.flatnonzero(share > 0.5)
    assert set(majority.tolist()) <= set(cells.tolist())
    footprint = mesh.geometry.areas[cells].sum() / lake.area
    assert 0.9 <= footprint <= 1.1


def test_a_lake_with_no_narrow_part_keeps_its_own_outline() -> None:
    request, mesh = _build(_inputs(_BODY))

    ring = shapely.multilinestrings(list(_family(request, "lakes").lines))
    vertices = shapely.points(shapely.get_coordinates(ring))
    assert shapely.distance(vertices, _BODY.boundary).max() <= 1e-6
    assert not any("smoothed" in note for note in request.notes)
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE


def test_a_wall_wing_of_a_few_metres_is_left_out_and_the_wall_stays_on_the_shore() -> None:
    top = Y0 + 650.0
    wall = LineString(
        [
            (X0 + 1100.0 + 5.0, top + 3.0),
            (X0 + 1100.0, top),
            (X0 + 700.0, top),
            (X0 + 600.0, top + 100.0),
        ]
    )
    request, mesh = _build(_inputs(_BODY, barriers=(wall,)))

    line = _family(request, BARRIER_FAMILY).lines[0]
    ends = shapely.get_coordinates(line)[[0, -1]]
    assert np.allclose(ends[0], (X0 + 1100.0, top))
    assert np.allclose(ends[-1], (X0 + 600.0, top + 100.0))
    assert mesh.qa.families["lakes"]["covered_length_rel"] >= CLOSED_SHORE_SHARE
    assert mesh.qa.families[BARRIER_FAMILY]["covered_length_rel"] >= CLOSED_SHORE_SHARE


def test_one_seed_gives_one_mesh_with_lakes_and_rivers() -> None:
    inputs = _inputs(_BODY.union(_ARM), river=True)
    _, first = _build(inputs)
    _, second = _build(inputs)

    assert np.array_equal(np.asarray(first.mesh.vertices), np.asarray(second.mesh.vertices))
    assert np.array_equal(first.centers, second.centers)
