"""MODFLOW 6 locates wells and boundaries on the cells it solves.

With ``grid_dual = "voronoi"`` (the default for a gmsh mesh) MODFLOW 6 solves on
the Voronoi dual of the bundle triangles: one cell per node. The bundle support
indexes the triangles. A triangle index read as a dual cell index puts a well in
the wrong cell, or runs past the end of the dual grid.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from hydromodpy.physics.flow.sinks_sources import FlowWellConfig
from hydromodpy.solver.modflow6.builders import (
    build_side_boundary_chd_spd,
    build_stream_boundary_chd_spd,
    build_well_stress_period_data,
)
from hydromodpy.solver.modflow6.builders.boundary_conditions import side_boundary_cell_ids
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    SolverSGridConfig,
    VerticalGridConfig,
)
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
    support_on_planar_mesh,
)
from hydromodpy.spatial.mesh.ops.voronoi import voronoi_planar_mesh

from ._test_modflow6_boundary_conditions_builders import _build_model

SIZE_M = 500.0
N_SIDE = 6
RIVER_ROW = 3


def _triangulated_square() -> tuple[HydroMesh, SimpleNamespace]:
    """Return a jittered square triangulation and its bundle-like payload.

    The nodes of row ``RIVER_ROW`` are joined by river edges.
    """
    rng = np.random.default_rng(7)
    axis = np.linspace(0.0, SIZE_M, N_SIDE)
    node_x, node_y = np.meshgrid(axis, axis)
    node_x = node_x.reshape(-1)
    node_y = node_y.reshape(-1)
    spacing = SIZE_M / (N_SIDE - 1)
    interior = (node_x > 0.0) & (node_x < SIZE_M) & (node_y > 0.0) & (node_y < SIZE_M)
    node_x[interior] += rng.uniform(-0.2, 0.2, int(interior.sum())) * spacing
    node_y[interior] += rng.uniform(-0.2, 0.2, int(interior.sum())) * spacing

    def node(i: int, j: int) -> int:
        return j * N_SIDE + i

    triangles: list[tuple[int, int, int]] = []
    for j in range(N_SIDE - 1):
        for i in range(N_SIDE - 1):
            a, b, c, d = node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)
            triangles.extend([(a, b, c), (a, c, d)])

    owners: dict[tuple[int, int], list[int]] = {}
    for cell_id, tri in enumerate(triangles):
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            owners.setdefault((min(a, b), max(a, b)), []).append(cell_id)
    river = {(node(i, RIVER_ROW), node(i + 1, RIVER_ROW)) for i in range(N_SIDE - 1)}
    edges = tuple(
        SimpleNamespace(
            edge_id=edge_id,
            node_a=key[0],
            node_b=key[1],
            cell_a=cells[0],
            cell_b=cells[1] if len(cells) > 1 else None,
            edge_kind="internal" if len(cells) > 1 else "boundary",
            is_river=key in river,
            geology_a_key="",
            geology_b_key="",
        )
        for edge_id, (key, cells) in enumerate(owners.items())
    )
    bundle = SimpleNamespace(
        bundle_dir=".",
        mesh_path="mesh_2d.msh",
        nodes=tuple(
            SimpleNamespace(node_id=index, x=float(x), y=float(y))
            for index, (x, y) in enumerate(zip(node_x, node_y, strict=True))
        ),
        cells=tuple(
            SimpleNamespace(
                cell_id=cell_id,
                node_indices=tri,
                centroid_x=float(node_x[list(tri)].mean()),
                centroid_y=float(node_y[list(tri)].mean()),
            )
            for cell_id, tri in enumerate(triangles)
        ),
        edges=edges,
    )
    mesh = HydroMesh(
        vertices=np.column_stack([node_x, node_y]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangles, dtype=int)),),
    )
    return mesh, bundle


def _surface(value: float, name: str) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=10.0,
        dy=10.0,
        xmin=-10.0,
        xmax=SIZE_M + 10.0,
        ymin=-10.0,
        ymax=SIZE_M + 10.0,
        nrows=52,
        ncols=52,
        nodata=-9999.0,
    )
    return Surface(name=name, values=np.full((52, 52), value), support=support)


def _grid_context(grid_dual: str):
    mesh, bundle = _triangulated_square()
    triangle_support = build_gmsh_support_metadata(bundle)
    domain = Domain(config=DomainConfig(), surface_topo=_surface(20.0, "surface_topo"))
    domain.substratum = _surface(0.0, "substratum")
    ctx = build_spatial_discretization(
        domain=domain,
        sgrid_config=SolverSGridConfig(
            grid_dual=grid_dual,
            vertical=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=-9999.0),
        ),
        runtime_planar_mesh=mesh,
        runtime_mesh_support=triangle_support,
    )
    return ctx, triangle_support, mesh


def _model_on(ctx) -> object:
    model = _build_model()
    model.grid_ctx = ctx
    model.solver_mesh = ctx.solver_mesh
    model.solver_mesh_support = ctx.mesh_support
    model.nlay = 1
    model.ncpl = int(ctx.solver_mesh.n_cells)
    model.ncol = 0
    model.dem_mask = np.zeros(model.ncpl, dtype=bool)
    return model


def _dual_polygon(ctx, cell: int) -> Polygon:
    planar = ctx.solver_mesh.planar_mesh
    nodes = np.asarray(planar.flat_connectivity[cell], dtype=int)
    return Polygon(np.asarray(planar.vertices, dtype=float)[nodes, :2])


POINTS = [(250.0, 250.0), (61.0, 433.0), (377.0, 120.0), (430.0, 470.0), (190.0, 300.0)]


def test_the_voronoi_support_describes_the_dual_cells() -> None:
    ctx, triangle_support, mesh = _grid_context("voronoi")
    support = ctx.mesh_support

    assert ctx.solver_mesh.n_cells == mesh.n_nodes
    assert triangle_support.n_cells > ctx.solver_mesh.n_cells
    assert support.n_cells == ctx.solver_mesh.n_cells
    assert int(support.edge_cell_a.max()) < support.n_cells
    assert int(support.edge_cell_b.max()) < support.n_cells


def test_the_triangle_dual_keeps_the_bundle_support() -> None:
    ctx, triangle_support, _mesh = _grid_context("triangle")

    assert ctx.mesh_support is triangle_support


@pytest.mark.parametrize(("x_m", "y_m"), POINTS)
def test_a_point_lands_in_the_dual_cell_that_holds_it(x_m: float, y_m: float) -> None:
    ctx, _triangle_support, _mesh = _grid_context("voronoi")

    cell = ctx.mesh_support.locate_cell_index_for_point(x_m, y_m, allow_nearest=False)

    assert _dual_polygon(ctx, cell).covers(Point(x_m, y_m))
    center_x, center_y = ctx.solver_mesh.planar_mesh.cell_centroids()
    nearest = int(np.argmin((center_x - x_m) ** 2 + (center_y - y_m) ** 2))
    assert cell == nearest


def test_the_triangle_index_is_not_the_dual_cell() -> None:
    # Guard on the test itself: on this mesh, the bundle triangle index of some
    # point names another dual cell, so the tests above see the old defect.
    ctx, triangle_support, _mesh = _grid_context("voronoi")

    differs = [
        triangle_support.locate_cell_index_for_point(x_m, y_m, allow_nearest=False)
        != ctx.mesh_support.locate_cell_index_for_point(x_m, y_m, allow_nearest=False)
        for x_m, y_m in POINTS
    ]
    assert any(differs)


def test_a_well_is_written_in_the_dual_cell_that_holds_it() -> None:
    ctx, _triangle_support, _mesh = _grid_context("voronoi")
    model = _model_on(ctx)
    x_m, y_m = POINTS[1]
    model.flow = SimpleNamespace(
        sinks_sources={
            "wells": {
                "P1": FlowWellConfig(
                    location={"kind": "absolute_xy", "x": x_m, "y": y_m},
                    flux=-1.0,
                )
            }
        },
        active_sinks_sources=["wells"],
    )

    wel_spd = build_well_stress_period_data(model, 2)

    cell = int(wel_spd[0][0][1])
    assert _dual_polygon(ctx, cell).covers(Point(x_m, y_m))


def test_side_boundaries_on_the_dual_take_the_dual_cells_of_the_side() -> None:
    ctx, _triangle_support, mesh = _grid_context("voronoi")
    model = _model_on(ctx)
    model.flow = SimpleNamespace(
        boundary_conditions={
            "west_side": SimpleNamespace(value=10.0),
            "north_side": SimpleNamespace(value=12.0),
        },
        active_bc=["west_side", "north_side"],
    )

    chd_spd = build_side_boundary_chd_spd(model)

    cells = {int(row[1]) for row in chd_spd[0]}
    vertices = np.asarray(mesh.vertices, dtype=float)
    on_sides = np.flatnonzero(np.isclose(vertices[:, 0], 0.0) | np.isclose(vertices[:, 1], SIZE_M))
    # One dual cell per node, in node order: the side nodes are the side cells.
    assert cells == set(on_sides.tolist())


def test_a_stream_boundary_on_the_dual_takes_the_cells_the_river_runs_through() -> None:
    ctx, _triangle_support, mesh = _grid_context("voronoi")
    model = _model_on(ctx)
    model.flow = SimpleNamespace(
        boundary_conditions={"stream": SimpleNamespace(value=7.0)},
        active_bc=["stream"],
    )

    _chd_spd, mask = build_stream_boundary_chd_spd(model)

    assert mask.size == ctx.solver_mesh.n_cells
    river_nodes = np.arange(N_SIDE) + RIVER_ROW * N_SIDE
    # Each river node is the generator of its own dual cell.
    assert mask[river_nodes].all()
    line = LineString(np.asarray(mesh.vertices, dtype=float)[river_nodes])
    for cell in np.flatnonzero(mask).tolist():
        assert _dual_polygon(ctx, cell).intersects(line)


SIDES = ("west_side", "east_side", "south_side", "north_side")


def _square_dual(seeds: np.ndarray, size_m: float = 400.0) -> GmshSupportMetadata:
    mesh = voronoi_planar_mesh(seeds, box(0.0, 0.0, size_m, size_m))
    return support_on_planar_mesh(GmshSupportMetadata(), mesh)


def _sparse_side_seeds() -> np.ndarray:
    """Return 8 nodes on the sides of a 400 m square (200 m apart) and a 50 m lattice inside.

    The inner nodes 50 m from a side lie closer to it than the side nodes, so
    their clipped cells reach the side.
    """
    on_sides = [(0, 0), (200, 0), (400, 0), (400, 200), (400, 400), (200, 400), (0, 400), (0, 200)]
    inner = [(x, y) for x in range(50, 400, 50) for y in range(50, 400, 50)]
    return np.asarray(on_sides + inner, dtype=float)


def _expected_side_cells(seeds: np.ndarray, size_m: float = 400.0) -> dict[str, set[int]]:
    x, y = seeds[:, 0], seeds[:, 1]
    return {
        "west_side": set(np.flatnonzero(x == 0.0).tolist()),
        "east_side": set(np.flatnonzero(x == size_m).tolist()),
        "south_side": set(np.flatnonzero(y == 0.0).tolist()),
        "north_side": set(np.flatnonzero(y == size_m).tolist()),
    }


def test_a_side_on_the_dual_takes_exactly_the_cells_centred_on_it() -> None:
    seeds = _sparse_side_seeds()
    support = _square_dual(seeds)

    expected = _expected_side_cells(seeds)
    face_rule = replace(support, side_cell_indices={})
    for side in SIDES:
        assert set(support.boundary_cell_indices_for_side(side).tolist()) == expected[side]
        assert set(support.cell_indices_for_label(side).tolist()) == expected[side]
        # Guard on the test itself: inner cells also touch the side here.
        assert set(face_rule.boundary_cell_indices_for_side(side).tolist()) > expected[side]


def test_a_corner_cell_belongs_to_both_sides_as_on_the_structured_grid() -> None:
    structured = _build_model()  # 2 rows x 3 columns, cell 0 at the north-west corner
    assert 0 in side_boundary_cell_ids(structured, "west_side")
    assert 0 in side_boundary_cell_ids(structured, "north_side")

    seeds = _sparse_side_seeds()
    support = _square_dual(seeds)

    north_west = int(np.flatnonzero((seeds[:, 0] == 0.0) & (seeds[:, 1] == 400.0))[0])
    assert north_west in support.boundary_cell_indices_for_side("west_side").tolist()
    assert north_west in support.boundary_cell_indices_for_side("north_side").tolist()


def test_a_side_with_no_centred_cell_keeps_the_cells_with_a_face_on_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seeds = np.asarray(
        [(x, y) for x in range(50, 400, 100) for y in range(50, 400, 100)], dtype=float
    )

    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        support = _square_dual(seeds)

    west = set(support.boundary_cell_indices_for_side("west_side").tolist())
    assert west == set(np.flatnonzero(seeds[:, 0] == 50.0).tolist())
    assert "No cell of the solver mesh is centred on west_side" in caplog.text
