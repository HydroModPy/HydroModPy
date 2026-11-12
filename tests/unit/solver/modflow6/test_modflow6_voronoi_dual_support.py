"""MODFLOW 6 locates wells and boundaries on the cells it solves.

A Voronoi cell mesh has one cell per node of its triangulation. The triangles are
indexed differently: a triangle index read as a dual cell index puts a well in the
wrong cell, or runs past the end of the dual grid. The solver reads the cell mesh it
solves on, whatever the engine that built it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.mesh.cells.boundary import side_cells
from hydromodpy.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.mesh.io.bundle import cell_mesh_from_bundle
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.mesh.planning.input_triangulation import domain_polygon_from_mesh
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow6.builders.boundary_conditions import build_side_boundary_chd_spd
from hydromodpy.solver.modflow_grid.discretization_spatial import build_spatial_discretization
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.dual_of_triangles import dual_of_the_triangles
from tests._helpers.mesh_cases import grid_over, mesh_request
from tests._helpers.mf6_toy_models import toy_model

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


def _triangles_and_dual(
    mesh: HydroMesh, bundle: SimpleNamespace
) -> tuple[PlanarCellMesh, PlanarCellMesh]:
    """Return the bundle triangles as a cell mesh, and their Voronoi dual with the river faces."""
    triangles = cell_mesh_from_bundle(bundle, crs_wkt=TEST_CRS_WKT)
    domain = domain_polygon_from_mesh(mesh)
    request = mesh_request(grid_over(domain), domain=domain, nominal_size_m=SIZE_M / (N_SIDE - 1))
    return triangles, dual_of_the_triangles(triangles, request)


def _grid_context(engine: str):
    """Extrude the triangles (``engine = "triangle"``) or their dual (``"voronoi"``)."""
    mesh, bundle = _triangulated_square()
    triangles, dual = _triangles_and_dual(mesh, bundle)
    cell_mesh = triangles if engine == "triangle" else dual
    domain = Domain(config=DomainConfig(), surface_topo=_surface(20.0, "surface_topo"))
    domain.substratum = _surface(0.0, "substratum")
    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=-9999.0),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )
    return ctx, triangles, mesh, bundle


def _model_on(ctx) -> object:
    model = toy_model()
    model.grid_ctx = ctx
    model.solver_mesh = ctx.solver_mesh
    model.nlay = 1
    model.ncpl = int(ctx.solver_mesh.n_cells)
    model.dem_mask = np.zeros(model.ncpl, dtype=bool)
    return model


def _dual_polygon(ctx, cell: int) -> Polygon:
    planar = ctx.solver_mesh.planar_mesh
    row = planar.flat_connectivity[cell]
    return Polygon(np.asarray(planar.vertices, dtype=float)[row[row >= 0], :2])


POINTS = [(250.0, 250.0), (61.0, 433.0), (377.0, 120.0), (430.0, 470.0), (190.0, 300.0)]


def test_side_boundaries_on_the_dual_take_the_dual_cells_of_the_side() -> None:
    ctx, _triangles, mesh, _bundle = _grid_context("voronoi")
    model = _model_on(ctx)
    model.inputs = replace(
        model.inputs,
        boundaries=BoundaryConditionBundle(
            conditions={
                "west_side": SimpleNamespace(value=10.0),
                "north_side": SimpleNamespace(value=12.0),
            },
            active_ids=(
                "west_side",
                "north_side",
            ),
        ),
    )

    chd_spd = build_side_boundary_chd_spd(model)

    cells = {int(row[1]) for row in chd_spd[0]}
    vertices = np.asarray(mesh.vertices, dtype=float)
    on_sides = np.flatnonzero(np.isclose(vertices[:, 0], 0.0) | np.isclose(vertices[:, 1], SIZE_M))
    # One dual cell per node, in node order: the side nodes are the side cells.
    assert cells == set(on_sides.tolist())


SIDES = ("west_side", "east_side", "south_side", "north_side")


def _square_dual(seeds: np.ndarray, size_m: float = 400.0) -> PlanarCellMesh:
    """Return the Voronoi dual of the seeds in a square, with the faces on its four sides."""
    mesh = voronoi_planar_mesh(seeds, box(0.0, 0.0, size_m, size_m))
    cell_mesh = build_planar_cell_mesh(
        mesh,
        np.asarray(seeds, dtype=float),
        center_kind="generator",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("voronoi", "0", "", None),
        declarations={
            "graded": True,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
    )
    geometry = cell_mesh.geometry
    vertices = np.asarray(mesh.vertices, dtype=float)
    midpoint = 0.5 * (vertices[geometry.edge_nodes[:, 0]] + vertices[geometry.edge_nodes[:, 1]])
    outer = geometry.edge_cells[:, 1] < 0
    sides = {
        "west": outer & np.isclose(midpoint[:, 0], 0.0),
        "east": outer & np.isclose(midpoint[:, 0], size_m),
        "south": outer & np.isclose(midpoint[:, 1], 0.0),
        "north": outer & np.isclose(midpoint[:, 1], size_m),
    }
    rows = [np.flatnonzero(mask) for mask in sides.values()]
    edges = np.concatenate(rows)
    table = FaceFamilyTable(
        names=tuple(f"boundary:{side}" for side in sides),
        family=np.repeat(np.arange(len(rows)), [row.size for row in rows]),
        cell_a=geometry.edge_cells[edges, 0],
        cell_b=geometry.edge_cells[edges, 1],
        node_a=geometry.edge_nodes[edges, 0],
        node_b=geometry.edge_nodes[edges, 1],
        zone_left=np.full(edges.size, -1),
        zone_right=np.full(edges.size, -1),
    )
    return replace(cell_mesh, face_families=table)


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


def test_a_side_with_no_centred_cell_keeps_the_cells_with_a_face_on_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seeds = np.asarray(
        [(x, y) for x in range(50, 400, 100) for y in range(50, 400, 100)], dtype=float
    )

    dual = _square_dual(seeds)
    with caplog.at_level(logging.WARNING, logger="hydromodpy"):
        west = set(side_cells(dual, "west_side").tolist())

    assert west == set(np.flatnonzero(seeds[:, 0] == 50.0).tolist())
    assert "No cell of the solver mesh is centred on west_side" in caplog.text
