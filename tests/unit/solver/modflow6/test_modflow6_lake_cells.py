"""The cells a lake owns on a mesh, and the cells it switches off (idomain).

A lake owns the cells its polygon overlaps by a positive area (m2), or, where the
mesh faces follow its shore, whole cells that tile it. LAK lays the lake on the grid
by setting idomain to 0 on the occupied top layers of those cells and keeping an
active cell below for the VERTICAL connection.
"""

from __future__ import annotations

from importlib.util import find_spec
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from flopy.discretization import VertexGrid
from flopy.utils import GridIntersect
from shapely import affinity
from shapely.geometry import LineString, Polygon

from hydromodpy.mesh import registry
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.mesh.request import LineFamilySpec
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders._lake_geometry import _drop_interior_rings
from hydromodpy.solver.modflow6.builders.lake_cells import (
    apply_lake_idomain_mask,
    resolve_lake_cells,
    resolve_lake_cells_for_active_lakes,
    resolve_lake_occupied_layers,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_spec,
    mesh_request,
    square_domain,
    voronoi_lake_mesh,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

X0, Y0 = L93_ORIGIN
needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")

BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"

# Two lakes in the unit square, the second with an island. They are scaled to the mesh bounds.
UNIT_LAKES = (
    Polygon([(0.2, 0.25), (0.55, 0.18), (0.71, 0.47), (0.48, 0.69), (0.23, 0.58)]),
    Polygon(
        [(0.6, 0.6), (0.92, 0.62), (0.88, 0.9), (0.62, 0.86)],
        holes=[[(0.7, 0.7), (0.8, 0.71), (0.78, 0.8), (0.71, 0.79)]],
    ),
)


def regular_cell_mesh() -> PlanarCellMesh:
    """30 x 40 cells of 37.3 x 41.7 m at a non-integer origin."""
    mesh = solver_mesh_from_structured_arrays(
        nrow=30,
        ncol=40,
        top=np.zeros((30, 40)),
        botm=np.full((1, 30, 40), -10.0),
        dx=37.3,
        dy=41.7,
        xoff=350_000.37,
        yoff=6_780_000.11,
    )
    return mesh.cell_mesh


def unit_lakes_on(cell_mesh: PlanarCellMesh) -> list[Polygon]:
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    return [
        affinity.affine_transform(lake, [xmax - xmin, 0.0, 0.0, ymax - ymin, xmin, ymin])
        for lake in UNIT_LAKES
    ]


def gridintersect_areas(cell_mesh: PlanarCellMesh, polygon: Polygon) -> dict[int, float]:
    """The rule of the former builder: GridIntersect cells, overlap recomputed by shapely."""
    n_cells = cell_mesh.n_cells
    disv = to_flopy_disv_args(cell_mesh.mesh, top=np.zeros(n_cells), botm=np.full((1, n_cells), -1))
    grid = VertexGrid(
        vertices=disv["vertices"],
        cell2d=disv["cell2d"],
        top=np.zeros(n_cells),
        botm=np.full((1, n_cells), -1.0),
        nlay=1,
        ncpl=n_cells,
        xoff=0.0,
        yoff=0.0,
    )
    result = GridIntersect(grid).intersect(polygon, geo_dataframe=False)
    verts = np.asarray(grid.verts)
    areas = {}
    for cell in sorted({int(c) for c in np.asarray(result["cellids"]).ravel()}):
        ring = verts[[int(i) for i in grid.cell2d[cell][4:] if int(i) >= 0]][:, :2]
        areas[cell] = float(Polygon(ring).intersection(polygon).area)
    return areas


MESHES = [
    pytest.param(regular_cell_mesh, id="regular"),
    pytest.param(lambda: bundle_triangles(BUNDLE), id="triangles"),
    pytest.param(lambda: bundle_dual(BUNDLE), id="dual"),
]


@pytest.mark.parametrize("make_mesh", MESHES)
def test_cells_and_areas_match_gridintersect(make_mesh) -> None:
    cell_mesh = make_mesh()

    for index, lake in enumerate(unit_lakes_on(cell_mesh)):
        expected = gridintersect_areas(cell_mesh, lake)
        cells, areas = resolve_lake_cells(
            None, lake_id=f"lake{index}", polygon=lake, cell_mesh=cell_mesh, with_areas=True
        )
        assert cells == sorted(expected)
        np.testing.assert_allclose(
            [areas[c] for c in cells],
            [expected[c] for c in cells],
            rtol=1e-9,
            atol=1e-9 * lake.area,
        )
        assert sum(areas.values()) == pytest.approx(lake.area, rel=1e-9)


# A shore the generated Voronoi mesh follows in part. Where a lake arm is narrower than
# a cell the mesh has no shore segment, so the lake owns the cells its polygon overlaps.


def lake_on_voronoi_mesh(*points: tuple[float, float]) -> tuple[Polygon, PlanarCellMesh]:
    lake = Polygon([(X0 + x, Y0 + y) for x, y in points])
    domain = square_domain(1000.0, x0=X0, y0=Y0)
    return lake, voronoi_lake_mesh(lake, domain=domain, pixel=20.0, cell_size=40.0)


SQUARE = ((300, 300), (700, 300), (700, 700), (300, 700))
WITH_ARM = (
    (300, 300), (700, 300), (700, 500), (950, 500), (950, 512), (700, 512), (700, 700), (300, 700)
)  # fmt: skip


def test_a_shore_followed_whole_gives_whole_cells() -> None:
    lake, mesh = lake_on_voronoi_mesh(*SQUARE)

    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=lake, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] == pytest.approx(1.0)
    np.testing.assert_array_equal([areas[c] for c in cells], mesh.geometry.areas[cells])
    assert sum(areas.values()) == pytest.approx(lake.area, rel=1e-6)


def test_a_shore_followed_in_part_is_resolved_by_overlap() -> None:
    lake, mesh = lake_on_voronoi_mesh(*WITH_ARM)

    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=lake, cell_mesh=mesh, with_areas=True
    )

    assert mesh.qa.families["lakes"]["covered_length_rel"] < 0.99
    assert cells
    assert sum(areas.values()) == pytest.approx(lake.area, rel=1e-6)


# Triangles whose faces follow the lake shores: a lake owns whole cells that tile it.
# An island ring keeps its cells out of the lake unless the lake fills it. A lake
# whose shore was not meshed is refused.


def p(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


LAKE = Polygon([p(150, 150), p(420, 120), p(480, 380), p(300, 470), p(130, 340)])
ATOLL = Polygon(
    [p(580, 560), p(900, 600), p(860, 900), p(600, 870)],
    holes=[[p(680, 680), p(790, 690), p(780, 790), p(690, 780)]],
)
UNMESHED = Polygon([p(600, 100), p(800, 120), p(760, 300), p(620, 280)])


def rings(polygon: Polygon) -> list[LineString]:
    return [LineString(polygon.exterior.coords)] + [
        LineString(ring.coords) for ring in polygon.interiors
    ]


def triangles(*, with_shores: bool) -> PlanarCellMesh:
    lines = ()
    if with_shores:
        lines = (LineFamilySpec("lakes", "face", (*rings(LAKE), *rings(ATOLL)), closed=True),)
    return registry.mesh_engines.create("triangle").build(
        mesh_request(
            grid_spec(40, 40, 25.0, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
            nominal_size_m=60.0,
            lines=lines,
        )
    )


@pytest.fixture(scope="module")
def shores() -> PlanarCellMesh:
    return triangles(with_shores=True)


def cells_inside(cell_mesh: PlanarCellMesh, cells: list[int], polygon: Polygon) -> bool:
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    return bool(np.all(shapely.covered_by(polygons[cells], polygon.buffer(1e-6))))


@needs_gmsh
def test_a_lake_owns_whole_cells_that_tile_it(shores: PlanarCellMesh) -> None:
    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=LAKE, cell_mesh=shores, with_areas=True
    )

    assert cells_inside(shores, cells, LAKE)
    np.testing.assert_array_equal([areas[c] for c in cells], shores.geometry.areas[cells])
    assert sum(areas.values()) == pytest.approx(LAKE.area, rel=1e-9)


@needs_gmsh
def test_overlap_adds_slivers_where_no_shore_was_meshed() -> None:
    plain = triangles(with_shores=False)

    cells, areas = resolve_lake_cells(
        None, lake_id="lake", polygon=LAKE, cell_mesh=plain, with_areas=True
    )

    assert not cells_inside(plain, cells, LAKE)
    assert sum(areas.values()) == pytest.approx(LAKE.area, rel=1e-9)


@needs_gmsh
def test_an_island_stays_out_unless_the_lake_fills_it(shores: PlanarCellMesh) -> None:
    kept = resolve_lake_cells(None, lake_id="atoll", polygon=ATOLL, cell_mesh=shores)
    filled, areas = resolve_lake_cells(
        None,
        lake_id="atoll",
        polygon=_drop_interior_rings(ATOLL),
        cell_mesh=shores,
        with_areas=True,
    )

    assert cells_inside(shores, kept, ATOLL)
    assert set(kept) < set(filled)
    assert cells_inside(shores, sorted(set(filled) - set(kept)), Polygon(ATOLL.interiors[0]))
    assert sum(areas.values()) == pytest.approx(Polygon(ATOLL.exterior).area, rel=1e-9)


@needs_gmsh
def test_a_lake_whose_shore_was_not_meshed_is_refused(shores: PlanarCellMesh) -> None:
    with pytest.raises(ValueError, match="encloses no region of the lakes faces"):
        resolve_lake_cells(None, lake_id="pond", polygon=UNMESHED, cell_mesh=shores)


def test_two_overlapping_lakes_are_cell_disjoint() -> None:
    # MF6 LAK allows one lake per cell, so each shared cell goes to the lake that
    # overlaps it most. The second polygon is shifted by one cell on the 4x4 grid.
    lakes = {
        "lac0": {
            "polygon": Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            "bedleak": 0.2,
            "outlets": [],
        },
        "lac1": {
            "polygon": Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),
            "bedleak": 0.2,
            "outlets": [],
        },
    }
    model = SimpleNamespace(
        model_output_name="overlap_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)), lakes=lakes
        ),
    )

    unit_grid = solver_mesh_from_structured_arrays(
        nrow=4,
        ncol=4,
        top=np.full((4, 4), 100.0),
        botm=np.full((2, 4, 4), 0.0),
        dx=1.0,
        dy=1.0,
    )

    cells = resolve_lake_cells_for_active_lakes(model, unit_grid)

    assert set(cells["lac0"]).isdisjoint(cells["lac1"])
    assert cells["lac0"] and cells["lac1"]


def test_occupied_layers_default_to_a_surface_lake() -> None:
    model = SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "surface": {"polygon": None, "bedleak": 0.1},
                "deep": {"polygon": None, "bedleak": 0.1, "occupied_layers": 3},
            },
        ),
    )

    assert resolve_lake_occupied_layers(model) == {"surface": 1, "deep": 3}


def grid(nrow: int, ncol: int, nlay: int = 3) -> SolverMesh:
    top = np.full((nrow, ncol), 10.0)
    botm = np.stack([np.full((nrow, ncol), 10.0 - (lay + 1) * 3.0) for lay in range(nlay)])
    return solver_mesh_from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)


# Each row is (nrow, ncol, nlay, lake cells, occupied-layer keywords, inactive layers
# per switched-off cell). Every other cell stays active on every layer.
MASKS = [
    pytest.param(3, 3, 3, {"lac0": [4]}, {}, {4: 1}, id="surface layer of the central cell"),
    pytest.param(2, 2, 3, {"lac0": [0]}, {"occupied_layers": 2}, {0: 2}, id="two occupied layers"),
    pytest.param(2, 4, 2, {"lac0": [0], "lac1": [7]}, {}, {0: 1, 7: 1}, id="two lakes"),
    pytest.param(
        2,
        2,
        3,
        {"surface": [0], "deep": [3]},
        {"occupied_layers_by_lake": {"surface": 1, "deep": 2}},
        {0: 1, 3: 2},
        id="occupied layers per lake",
    ),
]


@pytest.mark.parametrize(("nrow", "ncol", "nlay", "cells", "kwargs", "inactive"), MASKS)
def test_idomain_mask(nrow, ncol, nlay, cells, kwargs, inactive) -> None:
    masked = apply_lake_idomain_mask(grid(nrow, ncol, nlay), lake_cell_ids_by_lake=cells, **kwargs)

    expected = np.ones((nlay, nrow * ncol), dtype=int)
    for cell, n_layers in inactive.items():
        expected[:n_layers, cell] = 0
    np.testing.assert_array_equal(masked.idomain, expected)


def test_idomain_mask_leaves_the_original_mesh_unchanged() -> None:
    mesh = grid(2, 3, nlay=2)

    apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": [0, 1]})

    assert np.all(mesh.idomain == 1)


MASK_REFUSALS = [
    pytest.param({"lac0": [0]}, {"occupied_layers": 2}, id="one occupied depth"),
    pytest.param({"deep": [0]}, {"occupied_layers_by_lake": {"deep": 2}}, id="depth per lake"),
]


@pytest.mark.parametrize(("cells", "kwargs"), MASK_REFUSALS)
def test_idomain_mask_refuses_a_full_column(cells, kwargs) -> None:
    with pytest.raises(ValueError, match="at least one active layer"):
        apply_lake_idomain_mask(grid(2, 2, nlay=2), lake_cell_ids_by_lake=cells, **kwargs)
