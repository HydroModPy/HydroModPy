"""DISV meshes for closed-form validation tests built straight on flopy.

A closed-form test that writes its MODFLOW 6 model with flopy normally uses a
rectilinear DIS grid. These builders give the same test a strip or a radial
mesh made of triangles or Voronoi polygons instead, as the keyword arguments of
``flopy.mf6.ModflowGwfdisv`` (and of the GWT and PRT DISV packages).

The meshes go through HydroModPy's own ``SolverMesh``: the triangles are a
``HydroMesh`` triangle block, the polygons come from ``voronoi_planar_mesh``,
and ``SolverMesh.to_disv_kwargs`` writes the vertices and ``cell2d``. A triangle
cell center is its vertex mean (what HydroModPy writes for a triangle grid), a
Voronoi cell center is its seed.

Two-point flux and XT3D: on a triangle mesh the line between two cell centers
is not perpendicular to the shared face, so the two-point flux is not consistent.
``DisvMesh.xt3d`` applies the rule HydroModPy uses in
``hydromodpy.solver.modflow6.build.xt3d_mode``: XT3D is always on for triangle
cells, and for other cells it is switched on when the p95 of the connection
non-orthogonality exceeds 30 degrees or more than 5 % of the connections exceed
30 degrees. A Voronoi mesh is orthogonal by construction and stays off. The
decision and the non-orthogonality numbers are in ``DisvMesh.xt3d_reason``.

Jitter is deterministic (fixed seed, legacy RandomState whose stream NumPy keeps frozen).
Points on a domain boundary only move
along that boundary, so the domain outline stays exact.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Point, Polygon, box

from hydromodpy.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.quality import nonorthogonality_summary
from hydromodpy.solver.modflow6.build import resolve_xt3d_options, xt3d_mode
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from

KINDS = ("triangle", "voronoi")
DEFAULT_SEED = 20261013


def _stub_model() -> SimpleNamespace:
    """A model with no XT3D override and an isotropic K, as the automatic rule sees it."""
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    return SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime, process_specific=None))


@dataclass(frozen=True)
class DisvMesh:
    """A DISV mesh with its geometry, boundary cells and XT3D decision."""

    kind: str
    solver_mesh: SolverMesh
    centers: np.ndarray
    areas: np.ndarray
    boundary_cells: np.ndarray
    nonorthogonality: dict[str, float]
    xt3d: bool
    xt3d_mode: str
    xt3d_reason: str
    _polygons: list[Polygon] = field(default_factory=list, repr=False, compare=False)

    @property
    def ncpl(self) -> int:
        """Number of cells per layer."""
        return self.solver_mesh.n_cells

    @property
    def nlay(self) -> int:
        """Number of layers."""
        return self.solver_mesh.nlay

    def disv_kwargs(self) -> dict[str, Any]:
        """Keyword arguments of ``ModflowGwfdisv`` / ``ModflowGwtdisv`` / ``ModflowPrtdisv``."""
        kwargs = self.solver_mesh.to_disv_kwargs()
        kwargs["nlay"] = self.nlay
        return kwargs

    def cell_containing(self, x: float, y: float) -> int:
        """Index of the planar cell that holds the point ``(x, y)``."""
        point = Point(x, y)
        near = np.argsort(np.hypot(self.centers[:, 0] - x, self.centers[:, 1] - y))[:12]
        for ic in near:
            if self._polygons[int(ic)].buffer(1e-9).covers(point):
                return int(ic)
        raise ValueError(f"no cell holds the point ({x}, {y})")

    def cells_on_side(self, axis: str, value: float, atol: float = 1e-9) -> list[int]:
        """Cells with a vertex on the line ``axis == value`` (``axis`` is ``"x"`` or ``"y"``)."""
        column = {"x": 0, "y": 1}[axis]
        out = []
        for ic, poly in enumerate(self._polygons):
            coords = np.asarray(poly.exterior.coords)[:, column]
            if np.any(np.abs(coords - value) <= atol):
                out.append(ic)
        return out

    def nearest_cell(self, x: float, y: float) -> int:
        """Index of the cell whose center is the closest to ``(x, y)``."""
        return int(np.argmin(np.hypot(self.centers[:, 0] - x, self.centers[:, 1] - y)))


def _boundary_cells(planar: HydroMesh) -> np.ndarray:
    """Cells that own at least one boundary edge (an edge held by a single cell)."""
    edge_cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ic, nodes in enumerate(planar.flat_connectivity):
        nodes = [int(n) for n in nodes if n >= 0]
        for k, a in enumerate(nodes):
            b = nodes[(k + 1) % len(nodes)]
            edge_cells[(min(a, b), max(a, b))].append(ic)
    owners = {cells[0] for cells in edge_cells.values() if len(cells) == 1}
    return np.asarray(sorted(owners), dtype=int)


def _finish(
    kind: str,
    planar: HydroMesh,
    top: float,
    botm: list[float],
    seeds: np.ndarray | None = None,
) -> DisvMesh:
    ncpl = planar.n_cells
    botm_arr = np.tile(np.asarray(botm, dtype=float).reshape(-1, 1), (1, ncpl))
    solver_mesh = solver_mesh_from(
        planar,
        top=np.full(ncpl, float(top)),
        botm=botm_arr,
        inactive_mask=np.zeros_like(botm_arr, dtype=bool),
        centers=seeds,
    )
    model = _stub_model()
    mode = xt3d_mode(model, solver_mesh)
    enabled = resolve_xt3d_options(model, solver_mesh) is not None
    m = nonorthogonality_summary(planar, centers=solver_mesh.generator_centers)
    reason = (
        f"HydroModPy rule {mode}: XT3D {'on' if enabled else 'off'} "
        f"(p95 {m['p95']:.1f} deg, {100 * m['frac_gt_30']:.1f} % of connections above 30 deg, "
        f"median {m['median']:.1f} deg)"
    )
    verts = np.asarray(planar.vertices, dtype=float)
    polygons = [Polygon(verts[c[c >= 0]]) for c in planar.flat_connectivity]
    return DisvMesh(
        kind=kind,
        solver_mesh=solver_mesh,
        centers=solver_mesh.cell_centers(),
        areas=solver_mesh.cell_areas(),
        boundary_cells=_boundary_cells(planar),
        nonorthogonality=m,
        xt3d=enabled,
        xt3d_mode=mode,
        xt3d_reason=reason,
        _polygons=polygons,
    )


def _triangle_mesh(points: np.ndarray) -> HydroMesh:
    tri = Delaunay(points)
    used = np.unique(tri.simplices)
    if used.size != len(points):
        raise ValueError("Delaunay dropped seed points; the jitter produced a degenerate set")
    return HydroMesh(
        vertices=points,
        cell_blocks=(CellBlock(cell_type=CellType.TRIANGLE, connectivity=tri.simplices),),
    )


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")


def strip_mesh(
    kind: str,
    *,
    length: float,
    width: float,
    spacing: float,
    top: float,
    botm: list[float],
    jitter: float = 0.4,
    seed: int = DEFAULT_SEED,
) -> DisvMesh:
    """A rectangle ``[0, length] x [0, width]`` of triangles or Voronoi polygons.

    The lattice spacing is ``spacing`` along x (adjusted to divide ``length``)
    and along y. Every interior point moves by up to ``jitter * spacing`` in
    each direction. Points on a side move along that side only.

    Triangle: Delaunay triangulation of the lattice vertices (corners and sides
    included). Voronoi: the seeds are the lattice cell centers, clipped to the
    rectangle.
    """
    _check_kind(kind)
    rng = np.random.RandomState(seed)
    nx = max(1, round(length / spacing))
    ny = max(1, round(width / spacing))
    hx, hy = length / nx, width / ny
    amp = jitter * min(hx, hy)

    if kind == "triangle":
        xs = np.arange(nx + 1) * hx
        ys = np.arange(ny + 1) * hy
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        ix = np.repeat(np.arange(nx + 1), ny + 1)
        iy = np.tile(np.arange(ny + 1), nx + 1)
        move_x = (ix > 0) & (ix < nx)
        move_y = (iy > 0) & (iy < ny)
        pts[:, 0] += rng.uniform(-amp, amp, len(pts)) * move_x
        pts[:, 1] += rng.uniform(-amp, amp, len(pts)) * move_y
        planar = _triangle_mesh(pts)
    else:
        xs = (np.arange(nx) + 0.5) * hx
        ys = (np.arange(ny) + 0.5) * hy
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        ix = np.repeat(np.arange(nx), ny)
        iy = np.tile(np.arange(ny), nx)
        # The first and last columns and rows keep their distance to the side.
        move_x = (ix > 0) & (ix < nx - 1)
        move_y = (iy > 0) & (iy < ny - 1)
        pts[:, 0] += rng.uniform(-amp, amp, len(pts)) * move_x
        pts[:, 1] += rng.uniform(-amp, amp, len(pts)) * move_y
        planar = voronoi_planar_mesh(pts, box(0.0, 0.0, length, width))
        return _finish(kind, planar, top, botm, seeds=pts)
    return _finish(kind, planar, top, botm)


def radial_seeds(
    *,
    r_fine: float,
    r_max: float,
    growth: float,
    jitter: float,
    seed: int,
    jitter_outer: bool = False,
) -> np.ndarray:
    """Seeds of concentric rings at geometric radii, plus one seed at the origin.

    Ring ``k`` sits at ``r_fine * growth**k``. Every ring holds the number of
    seeds that makes the arc spacing match the staggered radial spacing, and odd
    rings are turned by half a step, so the pattern is near hexagonal in
    ``(ln r, theta)``. Seeds move by up to ``jitter`` of the local spacing; the
    outermost ring moves along the ring only (unless ``jitter_outer``).
    """
    rng = np.random.RandomState(seed)
    n_ring = max(6, round(2.0 * math.pi * 0.866 / (growth - 1.0)))
    radii = []
    r = r_fine
    while r <= r_max * (1.0 + 1e-9):
        radii.append(r)
        r *= growth
    pts = [np.zeros((1, 2))]
    for k, r in enumerate(radii):
        theta0 = 0.5 * (2.0 * math.pi / n_ring) * (k % 2)
        theta = theta0 + 2.0 * math.pi * np.arange(n_ring) / n_ring
        radial_step = r * (1.0 - 1.0 / growth)
        arc_step = 2.0 * math.pi * r / n_ring
        dr = rng.uniform(-1.0, 1.0, n_ring) * jitter * radial_step
        if k == len(radii) - 1 and not jitter_outer:
            dr = np.zeros(n_ring)
        dt = rng.uniform(-1.0, 1.0, n_ring) * jitter * arc_step / r
        rr, tt = r + dr, theta + dt
        pts.append(np.column_stack([rr * np.cos(tt), rr * np.sin(tt)]))
    return np.vstack(pts)


def radial_mesh(
    kind: str,
    *,
    r_max: float,
    top: float,
    botm: list[float],
    r_fine: float = 1.0,
    growth: float = 1.2,
    jitter: float = 0.4,
    seed: int = DEFAULT_SEED,
) -> DisvMesh:
    """A disc around the origin, fine at the center and coarsening geometrically.

    Triangle: Delaunay triangulation of the ring seeds; the well sits in the
    triangle that holds the origin. Voronoi: the origin seed is the well cell;
    the polygons are clipped to a circle half a ring step beyond the last ring.
    """
    _check_kind(kind)
    pts = radial_seeds(r_fine=r_fine, r_max=r_max, growth=growth, jitter=jitter, seed=seed)
    if kind == "triangle":
        planar = _triangle_mesh(pts)
    else:
        r_last = float(np.hypot(pts[:, 0], pts[:, 1]).max())
        clip = Point(0.0, 0.0).buffer(r_last * (1.0 + 0.5 * (growth - 1.0)), quad_segs=64)
        planar = voronoi_planar_mesh(pts, clip)
        return _finish(kind, planar, top, botm, seeds=pts)
    return _finish(kind, planar, top, botm)
