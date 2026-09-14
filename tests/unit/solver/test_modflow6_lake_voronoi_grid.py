"""The LAK CONNECTIONDATA builder on an irregular (non-rectangular) DISV grid.

``builders/lake.py`` builds CONNECTIONDATA from the mesh geometry, so its math
must hold on non-uniform polygon cells, not only on a unit grid. Two irregular
meshes exercise that:

* an irregular *triangular* mesh (jittered Delaunay) driven through the
  production ``build_lake_connectiondata``. ``SolverMesh`` carries homogeneous
  triangle / quad blocks only, so a mixed-polygon Voronoi tessellation cannot be
  wrapped as a ``SolverMesh`` directly; an irregular triangulation is the
  non-rectangular mesh the production builder consumes. Every HORIZONTAL row is
  checked against the true shared-edge length (``connwidth``) and the exact
  perpendicular distance from the neighbour centroid to that edge (``connlen``);
* a genuinely mixed-polygon *Voronoi* DISV (coarse background plus a refined
  cluster around the lake) built with ``flopy.utils.cvfdutil``. The production
  ``resolve_lake_cells`` intersects the lake polygon with the Voronoi
  ``VertexGrid``, and MF6 runs one period to confirm the package converges on the
  irregular mesh.

The point is the geometry is correct on non-uniform polygon cells. The lake
polygon is intersected with the mesh, CONNECTIONDATA is built, and the
invariants under test mirror the unit-grid case:

* ``connwidth`` equals the true shared-edge length and ``connlen > 0`` (the
  centroid-to-edge perpendicular half-distance);
* HORIZONTAL connections only target active, non-lake neighbours;
* exactly one VERTICAL per lake column to the first active cell below;
* lake cells become ``idomain = 0``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.spatial import Delaunay, Voronoi
from shapely.geometry import Polygon, box

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lake_connectiondata,
    build_vertex_grid_for_intersection,
    resolve_lake_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

_DOMAIN = 100.0
_LAKE_POLYGON = Polygon([(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)])
_TOP = 100.0
_BOTM = (90.0, 50.0)


# --------------------------------------------------------------------------- #
# Irregular triangular SolverMesh (drives the production builder).
# --------------------------------------------------------------------------- #


def _irregular_triangular_mesh() -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, triangles) for a jittered Delaunay mesh on the domain.

    Interior nodes are perturbed off the grid so the triangles are non-congruent:
    a real irregular mesh, not a unit grid. The perimeter nodes stay fixed so the
    footprint is exactly the domain square.
    """
    rng = np.random.default_rng(11)
    xs = np.linspace(0.0, _DOMAIN, 11)
    ys = np.linspace(0.0, _DOMAIN, 11)
    gx, gy = np.meshgrid(xs, ys)
    points = np.column_stack([gx.ravel(), gy.ravel()]).astype(float)
    interior = (
        (points[:, 0] > 0.0)
        & (points[:, 0] < _DOMAIN)
        & (points[:, 1] > 0.0)
        & (points[:, 1] < _DOMAIN)
    )
    points[interior] += rng.uniform(-3.0, 3.0, size=points[interior].shape)
    triangles = Delaunay(points).simplices.astype(int)
    return points, triangles


def _triangular_solver_mesh() -> SolverMesh:
    vertices, triangles = _irregular_triangular_mesh()
    planar = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),),
    )
    n_cells = planar.n_cells
    botm = np.stack([np.full(n_cells, _BOTM[0]), np.full(n_cells, _BOTM[1])])
    return SolverMesh(
        planar_mesh=planar,
        top=np.full(n_cells, _TOP),
        botm=botm,
        inactive_mask=np.zeros((2, n_cells), dtype=bool),
    )


def _resolve_lake_on(mesh: SolverMesh) -> list[int]:
    vertex_grid = build_vertex_grid_for_intersection(mesh)
    return resolve_lake_cells(None, lake_id="lac0", polygon=_LAKE_POLYGON, vertex_grid=vertex_grid)


def _cell_edges(nodes: np.ndarray) -> list[tuple[int, int]]:
    seq = [int(n) for n in nodes]
    return [
        tuple(sorted((seq[i], seq[(i + 1) % len(seq)])))  # type: ignore[misc]
        for i in range(len(seq))
    ]


def _edge_length(vertices: np.ndarray, edge: tuple[int, int]) -> float:
    a, b = vertices[edge[0]], vertices[edge[1]]
    return float(np.hypot(b[0] - a[0], b[1] - a[1]))


def _perpendicular_distance(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    length_sq = float(ab @ ab)
    if length_sq == 0.0:
        return float(np.hypot(point[0] - a[0], point[1] - a[1]))
    ap = point - a
    cross = float(ab[0] * ap[1] - ab[1] * ap[0])
    return abs(cross) / float(np.sqrt(length_sq))


def _true_horizontal_pairs(
    vertices: np.ndarray,
    triangles: np.ndarray,
    lake_cells: list[int],
    idomain: np.ndarray,
) -> set[tuple[int, float, float]]:
    """Recompute the expected (neighbour, connwidth, connlen) HORIZONTAL pairs.

    Mirrors the production loop: per lake cell, per edge, per shared-edge
    neighbour that is active and non-lake at layer 0.
    """
    lake_set = set(lake_cells)
    edges_by_cell = {cid: _cell_edges(triangles[cid]) for cid in range(triangles.shape[0])}
    centroids = vertices[triangles].mean(axis=1)
    pairs: set[tuple[int, float, float]] = set()
    for lake_cell in sorted(lake_set):
        for edge in edges_by_cell[lake_cell]:
            width = _edge_length(vertices, edge)
            if width <= 0.0:
                continue
            for neighbour, edges in edges_by_cell.items():
                if neighbour == lake_cell or neighbour in lake_set:
                    continue
                if edge not in edges:
                    continue
                if int(idomain[0, neighbour]) != 1:
                    continue
                connlen = _perpendicular_distance(
                    centroids[neighbour], vertices[edge[0]], vertices[edge[1]]
                )
                if connlen <= 0.0:
                    continue
                pairs.add((neighbour, round(width, 9), round(connlen, 9)))
    return pairs


def _connectiondata_on_triangular_mesh() -> tuple[SolverMesh, list[int], list[list]]:
    mesh = _triangular_solver_mesh()
    lake_cells = _resolve_lake_on(mesh)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": lake_cells})
    rows = build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=lake_cells, bedleak=0.5, solver_mesh=masked
    )
    return masked, lake_cells, rows


def test_lake_cells_resolve_on_irregular_triangular_mesh() -> None:
    mesh = _triangular_solver_mesh()
    assert not mesh.is_structured
    lake_cells = _resolve_lake_on(mesh)
    assert lake_cells, "the lake polygon must intersect the irregular mesh"
    centroids = mesh.cell_centroids()
    # Every resolved cell clusters around the lake footprint (40..60), not
    # scattered across the domain. A triangle straddling the polygon edge may
    # have its centroid a few metres outside, so allow a small halo.
    for cell in lake_cells:
        x, y = centroids[cell]
        assert 30.0 <= x <= 70.0
        assert 30.0 <= y <= 70.0


def test_lake_cells_become_idomain_zero() -> None:
    masked, lake_cells, _rows = _connectiondata_on_triangular_mesh()
    idomain = masked.idomain()
    for cell in lake_cells:
        assert idomain[0, cell] == 0  # occupied surface layer inactive
        assert idomain[1, cell] == 1  # aquifer below stays active to leak into


def test_one_vertical_connection_per_lake_column() -> None:
    _masked, lake_cells, rows = _connectiondata_on_triangular_mesh()
    vertical = [r for r in rows if r[3] == "VERTICAL"]
    assert len(vertical) == len(lake_cells)
    vert_cells = sorted(int(r[2][1]) for r in vertical)
    assert vert_cells == sorted(lake_cells)
    for r in vertical:
        assert r[2][0] == 1  # first active layer below the occupied surface layer


def test_horizontal_targets_only_active_non_lake_neighbours() -> None:
    masked, lake_cells, rows = _connectiondata_on_triangular_mesh()
    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    assert horizontal, "the lake must have bank-seepage HORIZONTAL connections"
    lake_set = set(lake_cells)
    idomain = masked.idomain()
    for r in horizontal:
        lay, neighbour = int(r[2][0]), int(r[2][1])
        assert lay == 0  # surface lake occupies layer 0 only
        assert neighbour not in lake_set
        assert idomain[lay, neighbour] == 1


def test_connwidth_and_connlen_match_true_geometry() -> None:
    _masked, lake_cells, rows = _connectiondata_on_triangular_mesh()
    vertices, triangles = _irregular_triangular_mesh()
    idomain = np.ones((2, triangles.shape[0]), dtype=int)
    for cell in lake_cells:
        idomain[0, cell] = 0

    horizontal = [r for r in rows if r[3] == "HORIZONTAL"]
    produced = {(int(r[2][1]), round(float(r[8]), 9), round(float(r[7]), 9)) for r in horizontal}
    expected = _true_horizontal_pairs(vertices, triangles, lake_cells, idomain)
    # connwidth = exact shared-edge length, connlen = exact perpendicular distance.
    assert produced == expected
    for r in horizontal:
        assert float(r[7]) > 0.0  # connlen strictly positive

    # The mesh is genuinely non-uniform: the shared-edge lengths are not all equal
    # (a unit grid would give a single connwidth value).
    connwidths = {round(float(r[8]), 6) for r in horizontal}
    assert len(connwidths) > 1


# --------------------------------------------------------------------------- #
# Mixed-polygon Voronoi DISV (resolve_lake_cells + MF6 convergence).
# --------------------------------------------------------------------------- #


def _voronoi_disv_gridprops() -> dict:
    """Build mixed-polygon DISV gridprops from a refined Voronoi tessellation.

    ``flopy.utils.voronoi.VoronoiGrid`` needs the external Triangle executable,
    which is not installed here, so the irregular cells come from a SciPy Voronoi
    of a coarse background plus a refined cluster around the lake, clipped to the
    domain and converted to DISV props with ``flopy.utils.cvfdutil`` (the same
    verts / iverts -> cell2d path ``VoronoiGrid.get_disv_gridprops`` uses).
    """
    from flopy.utils.cvfdutil import get_disv_gridprops, to_cvfd

    rng = np.random.default_rng(3)
    domain = box(0.0, 0.0, _DOMAIN, _DOMAIN)
    # Ghost ring outside the domain so interior cells stay bounded to the edge.
    ring = [(t, off) for t in np.linspace(0.0, _DOMAIN, 13) for off in (-6.0, _DOMAIN + 6.0)] + [
        (off, t) for t in np.linspace(0.0, _DOMAIN, 13) for off in (-6.0, _DOMAIN + 6.0)
    ]
    coarse = [(x, y) for x in np.linspace(8.0, 92.0, 6) for y in np.linspace(8.0, 92.0, 6)]
    fine = [
        (x + rng.uniform(-1.2, 1.2), y + rng.uniform(-1.2, 1.2))
        for x in np.linspace(36.0, 64.0, 8)
        for y in np.linspace(36.0, 64.0, 8)
    ]
    voronoi = Voronoi(np.array(ring + coarse + fine))

    vertdict: dict[int, list[tuple[float, float]]] = {}
    icell = 0
    for region_index in voronoi.point_region:
        region = voronoi.regions[region_index]
        if not region or -1 in region:
            continue
        cell = Polygon([tuple(voronoi.vertices[v]) for v in region]).intersection(domain)
        if cell.is_empty or cell.geom_type != "Polygon" or cell.area < 1e-6:
            continue
        vertdict[icell] = list(cell.exterior.coords)
        icell += 1

    verts, iverts = to_cvfd(vertdict, verbose=False)
    return get_disv_gridprops(verts, iverts)


def _voronoi_vertex_grid(gridprops: dict, idomain: np.ndarray):
    from flopy.discretization import VertexGrid

    ncpl = int(gridprops["ncpl"])
    return VertexGrid(
        vertices=gridprops["vertices"],
        cell2d=gridprops["cell2d"],
        top=np.full(ncpl, _TOP),
        botm=np.stack([np.full(ncpl, _BOTM[0]), np.full(ncpl, _BOTM[1])]),
        idomain=idomain,
        nlay=2,
        ncpl=ncpl,
    )


def test_voronoi_grid_has_mixed_polygon_cells() -> None:
    gridprops = _voronoi_disv_gridprops()
    vertex_counts = {int(row[3]) for row in gridprops["cell2d"]}
    # Genuinely irregular: cells have several different vertex counts, unlike the
    # uniform 4-vertex cells of a structured grid.
    assert len(vertex_counts) > 1
    assert min(vertex_counts) >= 5


def test_resolve_lake_cells_on_voronoi_vertex_grid() -> None:
    gridprops = _voronoi_disv_gridprops()
    ncpl = int(gridprops["ncpl"])
    idomain = np.ones((2, ncpl), dtype=int)
    vertex_grid = _voronoi_vertex_grid(gridprops, idomain)
    lake_cells = resolve_lake_cells(
        None, lake_id="lac0", polygon=_LAKE_POLYGON, vertex_grid=vertex_grid
    )
    assert lake_cells, "the lake polygon must intersect the Voronoi grid"
    xc, yc = vertex_grid.xcellcenters, vertex_grid.ycellcenters
    # Resolved cells cluster around the lake footprint (40..60); a Voronoi cell
    # straddling the polygon edge may sit a little outside, so allow a small halo.
    for cell in lake_cells:
        assert 30.0 <= float(xc[cell]) <= 70.0
        assert 30.0 <= float(yc[cell]) <= 70.0


def test_resolve_lake_cells_intersected_area_matches_polygon() -> None:
    gridprops = _voronoi_disv_gridprops()
    ncpl = int(gridprops["ncpl"])
    idomain = np.ones((2, ncpl), dtype=int)
    vertex_grid = _voronoi_vertex_grid(gridprops, idomain)
    cells, areas = resolve_lake_cells(
        None, lake_id="lac0", polygon=_LAKE_POLYGON, vertex_grid=vertex_grid, with_areas=True
    )
    assert set(areas) == set(cells)
    # The intersected areas sum to the true polygon area (edge cells under-fill),
    # not the over-counted full-cell footprint that drove area_scale > 1.
    assert sum(areas.values()) == pytest.approx(_LAKE_POLYGON.area, rel=1e-3)
    assert all(area > 0.0 for area in areas.values())


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_lak_converges_on_voronoi_grid(tmp_path: Path) -> None:
    import flopy

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    gridprops = _voronoi_disv_gridprops()
    ncpl = int(gridprops["ncpl"])
    idomain = np.ones((2, ncpl), dtype=int)
    vertex_grid = _voronoi_vertex_grid(gridprops, idomain)
    lake_cells = resolve_lake_cells(
        None, lake_id="lac0", polygon=_LAKE_POLYGON, vertex_grid=vertex_grid
    )
    for cell in lake_cells:
        idomain[0, cell] = 0

    xc = np.array([row[1] for row in gridprops["cell2d"]])
    yc = np.array([row[2] for row in gridprops["cell2d"]])
    margin = 12.0
    edge = (xc < margin) | (xc > _DOMAIN - margin) | (yc < margin) | (yc > _DOMAIN - margin)

    top = np.full(ncpl, _TOP)
    botm = np.stack([np.full(ncpl, _BOTM[0]), np.full(ncpl, _BOTM[1])])

    exe = str(ensure_solver_binary("mf6"))
    sim = flopy.mf6.MFSimulation(sim_name="vor", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 1, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="vor", save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=2,
        ncpl=ncpl,
        nvert=int(gridprops["nvert"]),
        top=top,
        botm=botm,
        vertices=gridprops["vertices"],
        cell2d=gridprops["cell2d"],
        idomain=idomain,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=0.1, save_specific_discharge=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    chd = [[(1, int(c)), 80.0] for c in np.where(edge)[0] if idomain[1, c] == 1]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})

    connectiondata = [
        [0, iconn, (1, int(cell)), "VERTICAL", 1.0, 0.0, 0.0, 0.0, 0.0]
        for iconn, cell in enumerate(lake_cells)
    ]
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        print_stage=True,
        save_flows=True,
        nlakes=1,
        ntables=1,
        packagedata=[[0, 95.0, len(connectiondata), "lac0"]],
        connectiondata=connectiondata,
        tables=[[0, "lac0.laktab"]],
        surfdep=0.1,
    )
    flopy.mf6.ModflowUtllaktab(
        gwf,
        nrow=3,
        ncol=3,
        table=[(90.0, 0.0, 0.0), (95.0, 450.0, 90.0), (100.0, 900.0, 90.0)],
        filename="lac0.laktab",
        parent_file=lak,
    )
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="vor.hds", saverecord=[("HEAD", "ALL")])
    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 LAK run did not converge on the irregular Voronoi grid"
