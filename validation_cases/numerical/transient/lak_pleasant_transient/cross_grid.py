"""Run the Plainfield lake problem on a ragged Voronoi DISV and compare it with the quad grid.

The triangle leg lives in ``grid_equivalence.py``. This module adds the Voronoi
dual, the default HydroModPy grid, so the production LAK builder is also checked
on cells with 5 to 7 edges. The physics, TDIS, abacus, forcing and constant-head
edges are the ones of the triangle leg; only the mesh changes.

The Voronoi seeds are a jittered lattice. Inside the lake, every seed within one
lattice spacing of a lake boundary line is mirrored across that line. The
perpendicular bisector of a seed and its mirror is the line itself, so the
Voronoi edges run exactly along the 200 m x 200 m lake polygon, as the quad and
triangle footprints do.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, box

from hydromodpy.solver.modflow6.builders.lake import (
    resolve_lake_cells,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from validation_cases.shared.solver_mesh import solver_mesh_of

from .geometry import CASE_DIR, PleasantTransientGeometry, load_geometry
from .grid_equivalence import (
    _LAKE_ID,
    _MODEL_NAME,
    GridEquivalenceScenario,
    GridRunResult,
    _build_irregular_simulation,
    _dedupe_points,
    _exchange_flux_per_period,
    _lake_polygon,
    _max_budget_percent,
    _run_regular,
    _stage_per_period,
    run_grid_equivalence_scenario,
)

# Lattice spacing of the seeds around the lake, as for the triangle leg.
_FINE_M = 20.0
_HALO_M = 40.0
_MESH_SEED = 7
# Jitter of the background seeds (m) and of the lake lattice (fraction of the spacing).
_BACKGROUND_JITTER_M = 8.0
_FINE_JITTER_FRAC = 0.2

IrregularKind = Literal["triangle", "voronoi"]


def _voronoi_solver_mesh(geometry: PleasantTransientGeometry) -> SolverMesh:
    """Voronoi ``SolverMesh`` over the 600 m square, edges on the lake boundary lines."""
    domain = geometry.ncol * geometry.cell_size_m
    cell = geometry.cell_size_m
    poly = _lake_polygon(geometry)
    x0, y0, x1, y1 = poly.bounds
    rng = np.random.default_rng(_MESH_SEED)

    # Background seeds at the quad cell centers. The two columns that carry the
    # constant heads keep their x so that their centroids stay inside the margin.
    centres = np.arange(cell / 2.0, domain, cell)
    bx, by = np.meshgrid(centres, centres)
    background = np.column_stack([bx.ravel(), by.ravel()]).astype(float)
    away = (
        (background[:, 0] < x0 - _HALO_M)
        | (background[:, 0] > x1 + _HALO_M)
        | (background[:, 1] < y0 - _HALO_M)
        | (background[:, 1] > y1 + _HALO_M)
    )
    background = background[away]
    edge_col = np.isclose(background[:, 0], cell / 2.0) | np.isclose(
        background[:, 0], domain - cell / 2.0
    )
    jitter = rng.uniform(-_BACKGROUND_JITTER_M, _BACKGROUND_JITTER_M, size=background.shape)
    jitter[edge_col, 0] = 0.0
    background += jitter

    # Fine lattice offset by half a spacing from the lake lines, so that the
    # first row inside and outside sit symmetrically about each line.
    half = _FINE_M / 2.0
    fine_x = np.arange(x0 - _HALO_M + half, x1 + _HALO_M, _FINE_M)
    fine_y = np.arange(y0 - _HALO_M + half, y1 + _HALO_M, _FINE_M)
    fx, fy = np.meshgrid(fine_x, fine_y)
    fine = np.column_stack([fx.ravel(), fy.ravel()]).astype(float)
    fine += rng.uniform(-_FINE_M * _FINE_JITTER_FRAC, _FINE_M * _FINE_JITTER_FRAC, size=fine.shape)

    inside = (fine[:, 0] > x0) & (fine[:, 0] < x1) & (fine[:, 1] > y0) & (fine[:, 1] < y1)
    near = (
        (fine[:, 0] < x0 + _FINE_M)
        | (fine[:, 0] > x1 - _FINE_M)
        | (fine[:, 1] < y0 + _FINE_M)
        | (fine[:, 1] > y1 - _FINE_M)
    )
    # Outside points within one spacing of the lake are replaced by the mirrors.
    outside_near = (
        ~inside
        & (fine[:, 0] > x0 - _FINE_M)
        & (fine[:, 0] < x1 + _FINE_M)
        & (fine[:, 1] > y0 - _FINE_M)
        & (fine[:, 1] < y1 + _FINE_M)
    )
    interior_band = fine[inside & near]
    mirrors = _mirror_across_lake_lines(interior_band, (x0, y0, x1, y1))
    fine = np.vstack([fine[~outside_near], mirrors])

    points = np.vstack([background, fine])
    points = _dedupe_points(points, _FINE_M * 0.45)
    planar = voronoi_planar_mesh(points, box(0.0, 0.0, domain, domain))
    n_cells = planar.n_cells
    botm = np.stack([np.full(n_cells, b) for b in geometry.botm_m])
    return solver_mesh_of(
        planar,
        top=np.full(n_cells, geometry.top_m),
        botm=botm,
        inactive_mask=np.zeros((geometry.nlay, n_cells), dtype=bool),
        centers=points,
    )


def _mirror_across_lake_lines(
    seeds: np.ndarray, bounds: tuple[float, float, float, float]
) -> np.ndarray:
    """Seeds plus their images across the four lake boundary lines (and the corner images)."""
    x0, y0, x1, y1 = bounds
    out = [seeds]
    for line, axis in ((x0, 0), (x1, 0), (y0, 1), (y1, 1)):
        near = np.abs(seeds[:, axis] - line) < _FINE_M
        image = seeds[near].copy()
        image[:, axis] = 2.0 * line - image[:, axis]
        out.append(image)
    # Corner images: reflect the x images across the y lines.
    for xline in (x0, x1):
        for yline in (y0, y1):
            near = (np.abs(seeds[:, 0] - xline) < _FINE_M) & (np.abs(seeds[:, 1] - yline) < _FINE_M)
            image = seeds[near].copy()
            image[:, 0] = 2.0 * xline - image[:, 0]
            image[:, 1] = 2.0 * yline - image[:, 1]
            out.append(image)
    return np.vstack(out)


def _run_voronoi(workspace: Path, geometry: PleasantTransientGeometry) -> GridRunResult:
    """Build, run and summarize the Voronoi-grid LAK simulation."""
    mesh = _voronoi_solver_mesh(geometry)
    lake_cells = resolve_lake_cells(
        None, lake_id=_LAKE_ID, polygon=_lake_polygon(geometry), cell_mesh=mesh.cell_mesh
    )
    sim, gwf, connectiondata = _build_irregular_simulation(workspace, geometry, mesh, lake_cells)
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"Voronoi LAK run did not converge:\n{buff}")

    budget_csv = workspace / f"{_MODEL_NAME}.lak.budget.csv"
    exchange = _exchange_flux_per_period(budget_csv, geometry.n_periods)
    return GridRunResult(
        label="irregular_voronoi",
        n_cells=mesh.n_cells,
        is_structured=mesh.is_structured,
        n_lake_cells=len(lake_cells),
        connection_counts=dict(Counter(str(r[3]).upper() for r in connectiondata)),
        period_stages=_stage_per_period(gwf, geometry.n_periods),
        steady_exchange_m3_per_s=exchange[0],
        final_exchange_m3_per_s=exchange[-1],
        max_budget_percent=_max_budget_percent(budget_csv),
    )


def run_regular_grid(*, workspace: Path) -> tuple[PleasantTransientGeometry, GridRunResult]:
    """Run only the regular 15x15 quad leg, the reference of both cross-grid legs."""
    geometry = load_geometry()
    workspace.mkdir(parents=True, exist_ok=True)
    return geometry, _run_regular(workspace, geometry)


def run_cross_grid_scenario(*, workspace: Path, kind: IrregularKind) -> GridEquivalenceScenario:
    """Run the regular quad grid and one irregular grid, then assemble the comparison."""
    if kind == "triangle":
        return run_grid_equivalence_scenario(workspace=workspace)
    if kind != "voronoi":
        raise ValueError(f"kind must be 'triangle' or 'voronoi', got {kind!r}")
    geometry = load_geometry()
    workspace.mkdir(parents=True, exist_ok=True)
    regular = _run_regular(workspace / "regular", geometry)
    irregular = _run_voronoi(workspace / "irregular", geometry)
    abs_diff = tuple(
        abs(r - i) for r, i in zip(regular.period_stages, irregular.period_stages, strict=True)
    )
    return GridEquivalenceScenario(
        geometry=geometry,
        regular=regular,
        irregular=irregular,
        per_period_abs_diff_m=abs_diff,
    )


def load_cross_grid_tolerances(kind: IrregularKind) -> dict:
    """Tolerances of one irregular leg: the triangle file, or the Voronoi one."""
    import tomllib

    name = {
        "triangle": "tolerances_grid_equivalence.toml",
        "voronoi": "tolerances_grid_equivalence_voronoi.toml",
    }[kind]
    with (CASE_DIR / name).open("r", encoding="utf-8") as fh:
        return tomllib.loads(fh.read().lstrip("﻿"))


__all__ = ["load_cross_grid_tolerances", "run_cross_grid_scenario", "run_regular_grid"]
