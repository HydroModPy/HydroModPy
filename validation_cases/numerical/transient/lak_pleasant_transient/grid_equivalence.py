"""Run the same lake-aquifer problem on a regular and an irregular DISV grid.

The transient multi-layer LAK case (geometry.py / runtime_lak.py) is built twice
with the SAME physics and forced through the production LAK builders:

* REGULAR: the 15x15 quad DISV from ``runtime_lak.run_hmp`` (40 m cells).
* IRREGULAR: a Delaunay TRIANGLE DISV over the same 600 m square, the same four
  layers and the same lake footprint, refined to ~20 m around the lake so the
  triangle footprint tiles the lake polygon exactly (nodes are pinned on the lake
  boundary lines so ``GridIntersect`` returns the same 200 m x 200 m area as the
  quad grid). HMP ``SolverMesh`` carries homogeneous triangle cells only, so an
  irregular triangulation is the non-rectangular mesh the builder consumes.

Both grids share the abacus, bedleak, aquifer K / recharge, TDIS and the
per-period rainfall / evaporation / runoff, so the only thing that changes is the
mesh. The comparison reports the per-period lake stage on each grid, the max
absolute stage difference and the relative difference of the steady lake-aquifer
exchange flux (the GWF term of the LAK budget), which is the cleanest
grid-independence signal.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.spatial import Delaunay, cKDTree
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders.lake import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_period_data,
    build_vertex_grid_for_intersection,
    resolve_lake_cells,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

from .geometry import CASE_DIR, PleasantTransientGeometry, load_geometry
from .runtime_lak import TransientLakeRunResult, run_hmp

_LAKE_ID = "plainfield"
_MODEL_NAME = "lakplsnt_tri"

# Triangle mesh resolution near the lake. 20 m halves the 40 m quad cell so the
# lake footprint is at least as well resolved, while pinning nodes on the lake
# boundary lines keeps the triangle footprint area equal to the quad footprint.
_FINE_M = 20.0
# Background halo (one quad cell) kept clear of background nodes around the lake so
# the fine cluster controls the cells touching the lake polygon.
_HALO_M = 40.0
# Fixed RNG seed so the jittered triangulation is deterministic across platforms.
_MESH_SEED = 42


@dataclass(frozen=True, slots=True)
class GridRunResult:
    """Per-period stages, the steady exchange flux and the mesh counts of one run."""

    label: str
    n_cells: int
    is_structured: bool
    n_lake_cells: int
    connection_counts: dict[str, int]
    period_stages: tuple[float, ...]
    steady_exchange_m3_per_s: float
    final_exchange_m3_per_s: float
    max_budget_percent: float


@dataclass(frozen=True, slots=True)
class GridEquivalenceScenario:
    """Regular-vs-irregular comparison of the same lake-aquifer problem."""

    geometry: PleasantTransientGeometry
    regular: GridRunResult
    irregular: GridRunResult
    per_period_abs_diff_m: tuple[float, ...] = field(default_factory=tuple)

    @property
    def max_abs_stage_diff_m(self) -> float:
        """Largest per-period absolute lake-stage difference between the grids."""
        return max(self.per_period_abs_diff_m)

    @property
    def steady_exchange_rel_diff(self) -> float:
        """Relative difference of the steady lake-aquifer exchange flux.

        The steady period is the deterministic, storage-free state, so its
        lake-aquifer GWF flux is the cleanest grid-independence signal.
        """
        reg = self.regular.steady_exchange_m3_per_s
        irr = self.irregular.steady_exchange_m3_per_s
        denom = abs(reg)
        if denom == 0.0:
            return abs(irr)
        return abs(reg - irr) / denom

    @property
    def n_periods(self) -> int:
        return len(self.regular.period_stages)


def _lake_polygon(geometry: PleasantTransientGeometry) -> Polygon:
    """Return the lake footprint as a polygon in the mesh's model coordinates.

    ``runtime_lak`` lays the structured grid with row 0 at the highest y, so the
    footprint rows ``[row_start, row_stop)`` map to descending y bands.
    """
    cell = geometry.cell_size_m
    x0 = geometry.col_start * cell
    x1 = geometry.col_stop * cell
    y_top = geometry.nrow * cell
    y1 = y_top - geometry.row_start * cell
    y0 = y_top - geometry.row_stop * cell
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _triangular_solver_mesh(geometry: PleasantTransientGeometry) -> SolverMesh:
    """Build the irregular triangle ``SolverMesh`` over the same domain and layers.

    Background nodes sit on the 40 m grid (jittered) away from the lake; a fine
    ~20 m cluster covers the lake plus a one-cell halo, with the nodes on the lake
    boundary lines pinned so the triangle footprint tiles the lake polygon exactly.
    """
    domain = geometry.ncol * geometry.cell_size_m
    poly = _lake_polygon(geometry)
    x0, y0, x1, y1 = poly.bounds
    rng = np.random.default_rng(_MESH_SEED)

    coarse = geometry.cell_size_m
    grid = np.arange(0.0, domain + 1.0, coarse)
    gx, gy = np.meshgrid(grid, grid)
    background = np.column_stack([gx.ravel(), gy.ravel()]).astype(float)
    away = (
        (background[:, 0] < x0 - _HALO_M)
        | (background[:, 0] > x1 + _HALO_M)
        | (background[:, 1] < y0 - _HALO_M)
        | (background[:, 1] > y1 + _HALO_M)
    )
    background = background[away]
    interior = (
        (background[:, 0] > 0.0)
        & (background[:, 0] < domain)
        & (background[:, 1] > 0.0)
        & (background[:, 1] < domain)
    )
    background[interior] += rng.uniform(-8.0, 8.0, size=background[interior].shape)

    fine_x = np.unique(
        np.concatenate([np.arange(x0 - _HALO_M, x1 + _HALO_M + 1.0, _FINE_M), [x0, x1]])
    )
    fine_y = np.unique(
        np.concatenate([np.arange(y0 - _HALO_M, y1 + _HALO_M + 1.0, _FINE_M), [y0, y1]])
    )
    fx, fy = np.meshgrid(fine_x, fine_y)
    fine = np.column_stack([fx.ravel(), fy.ravel()]).astype(float)
    on_boundary = (
        np.isclose(fine[:, 0], x0)
        | np.isclose(fine[:, 0], x1)
        | np.isclose(fine[:, 1], y0)
        | np.isclose(fine[:, 1], y1)
    )
    movable = (
        ~on_boundary
        & (fine[:, 0] > 0.0)
        & (fine[:, 0] < domain)
        & (fine[:, 1] > 0.0)
        & (fine[:, 1] < domain)
    )
    fine[movable] += rng.uniform(-_FINE_M * 0.2, _FINE_M * 0.2, size=fine[movable].shape)

    points = np.vstack([background, fine])
    points = _dedupe_points(points, _FINE_M * 0.45)
    triangles = Delaunay(points).simplices.astype(int)
    planar = HydroMesh(
        vertices=points,
        cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),),
    )
    n_cells = planar.n_cells
    botm = np.stack([np.full(n_cells, b) for b in geometry.botm_m])
    return SolverMesh(
        planar_mesh=planar,
        top=np.full(n_cells, geometry.top_m),
        botm=botm,
        inactive_mask=np.zeros((geometry.nlay, n_cells), dtype=bool),
    )


def _dedupe_points(points: np.ndarray, radius: float) -> np.ndarray:
    """Drop points closer than ``radius`` so the triangulation stays well-shaped."""
    keep = np.ones(len(points), dtype=bool)
    tree = cKDTree(points)
    for i in range(len(points)):
        if not keep[i]:
            continue
        for j in tree.query_ball_point(points[i], radius):
            if j > i:
                keep[j] = False
    return points[keep]


def _lake_definition(geometry: PleasantTransientGeometry, *, period: int) -> dict[str, Any]:
    """Lake definition for one stress period, with that period's forcing values.

    Identical to the regular case's definition except the polygon is the real lake
    footprint so the irregular grid can resolve the lake cells itself.
    """
    return {
        "polygon": _lake_polygon(geometry),
        "bedleak": geometry.bedleak_per_s,
        "abacus": {
            "stage": [row[0] for row in geometry.abacus_rows],
            "volume": [row[1] for row in geometry.abacus_rows],
            "sarea": [row[2] for row in geometry.abacus_rows],
        },
        "stageinit": geometry.stage_init_m,
        "rainfall": {"value": geometry.rainfall_m_per_s[period], "units": "m/s"},
        "evaporation": {"value": geometry.evaporation_m_per_s[period], "units": "m/s"},
        "runoff": {"value": geometry.runoff_m3_per_s[period], "units": "m3/s"},
    }


def _build_irregular_simulation(
    workspace: Path,
    geometry: PleasantTransientGeometry,
    mesh: SolverMesh,
    lake_cells: list[int],
):
    """Build the transient SI MF6 simulation on the irregular triangle grid.

    Mirrors ``runtime_lak.build_hmp_simulation``: same TDIS, IMS, NPF, STO, IC,
    recharge and per-period LAK forcing. Only the discretisation and the CHD edge
    selection differ (the irregular grid has no row / column structure, so the
    constant-head cells are picked by their x position).
    """
    import flopy

    masked = apply_lake_idomain_mask(
        mesh,
        lake_cell_ids_by_lake={_LAKE_ID: lake_cells},
        occupied_layers=geometry.occupied_layers,
    )
    model = SimpleNamespace(
        model_output_name=_MODEL_NAME,
        model_name=_MODEL_NAME,
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={"lakes": {_LAKE_ID: _lake_definition(geometry, period=0)}},
        ),
    )
    lak_args = build_lak_package_args(
        model,
        solver_mesh=masked,
        lake_cell_ids_by_lake={_LAKE_ID: lake_cells},
        occupied_layers=geometry.occupied_layers,
    )
    assert lak_args is not None, "the lake must be active in the irregular build"
    laktab_specs = lak_args.pop("laktab_specs")
    for key in (
        "obs_continuous",
        "lake_obs_meta",
        "mover_records",
        "mover_maxpackages",
        "ts_specs",
    ):
        lak_args.pop(key, None)
    lak_args["perioddata"] = {
        period: build_lake_period_data(
            None, lakes={_LAKE_ID: _lake_definition(geometry, period=period)}
        )[0]
        for period in range(geometry.n_periods)
    }

    exe = str(ensure_solver_binary("mf6"))
    sim = flopy.mf6.MFSimulation(sim_name=_MODEL_NAME, sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim, nper=geometry.n_periods, perioddata=geometry.tdis_perioddata, time_units="seconds"
    )
    ims = flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        complexity="MODERATE",
        linear_acceleration="bicgstab",
        outer_maximum=geometry.outer_maximum,
        outer_dvclose=geometry.outer_dvclose,
        inner_maximum=geometry.inner_maximum,
        inner_dvclose=geometry.inner_dvclose,
        rcloserecord=f"{geometry.rclose} strict",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname=_MODEL_NAME, newtonoptions="newton", save_flows=True)
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=geometry.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain(),
        length_units="meters",
    )
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,
        k=geometry.k11_m_per_s,
        k33=list(geometry.k33_m_per_s),
        save_specific_discharge=True,
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        sy=geometry.specific_yield,
        ss=geometry.specific_storage_per_s,
        steady_state=geometry.steady_state_flags,
        transient=geometry.transient_flags,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=geometry.strt_m)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: _irregular_chd(geometry, masked)})
    flopy.mf6.ModflowGwfrcha(gwf, recharge=geometry.recharge_m_per_s)

    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **lak_args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf,
            nrow=len(spec["table"]),
            ncol=3,
            table=spec["table"],
            filename=spec["filename"],
            parent_file=lak,
        )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{_MODEL_NAME}.hds",
        budget_filerecord=f"{_MODEL_NAME}.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    return sim, gwf, lak_args["connectiondata"]


def _irregular_chd(geometry: PleasantTransientGeometry, mesh: SolverMesh) -> list[list[Any]]:
    """Constant heads on the left / right domain edges of the irregular grid.

    The regular case fixes the left and right COLUMNS; the triangle grid has no
    columns, so cells whose centroid sits within half a cell of the x edges carry
    the same heads, in the same layers (only where the layer bottom is below the
    boundary head, which MF6 requires).
    """
    domain = geometry.ncol * geometry.cell_size_m
    margin = geometry.cell_size_m * 0.6
    centroids = mesh.cell_centroids()
    idomain = mesh.idomain()
    rows: list[list[Any]] = []
    for cell in range(mesh.n_cells):
        x = float(centroids[cell, 0])
        if x < margin:
            head = geometry.head_left_m
        elif x > domain - margin:
            head = geometry.head_right_m
        else:
            continue
        for lay in range(geometry.nlay):
            if head > geometry.botm_m[lay] and int(idomain[lay, cell]) == 1:
                rows.append([(lay, cell), head])
    return rows


def _stage_per_period(gwf, n_periods: int) -> tuple[float, ...]:
    """Return the lake stage at the end of every stress period (last step of each)."""
    stage_obj = gwf.lak.output.stage()
    last_by_period: dict[int, tuple[int, int]] = {}
    for kstp, kper in stage_obj.get_kstpkper():
        last_by_period[int(kper)] = (int(kstp), int(kper))
    return tuple(
        float(np.ravel(stage_obj.get_data(kstpkper=last_by_period[period]))[-1])
        for period in range(n_periods)
    )


def _exchange_flux_per_period(path: Path, n_periods: int) -> tuple[float, ...]:
    """Return the net lake-aquifer GWF exchange flux per period (m3/s, + into lake).

    The LAK budget CSV is one row per time step; the net GWF term is
    ``GWF_IN - GWF_OUT``. The steady period is the first row; the remaining periods
    share an equal step count, so we take each period's closing row.
    """
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Empty LAK budget CSV: {path}")
    net = [float(r["GWF_IN"]) - float(r["GWF_OUT"]) for r in rows]
    transient_periods = n_periods - 1
    if transient_periods <= 0:
        return (net[-1],)
    remaining = len(net) - 1
    per_transient = remaining // transient_periods
    out = [net[0]]
    for period in range(transient_periods):
        out.append(net[1 + (period + 1) * per_transient - 1])
    return tuple(out)


def _run_irregular(workspace: Path, geometry: PleasantTransientGeometry) -> GridRunResult:
    """Build, run and summarise the irregular triangle-grid LAK simulation."""
    mesh = _triangular_solver_mesh(geometry)
    vertex_grid = build_vertex_grid_for_intersection(mesh)
    lake_cells = resolve_lake_cells(
        None, lake_id=_LAKE_ID, polygon=_lake_polygon(geometry), vertex_grid=vertex_grid
    )
    sim, gwf, connectiondata = _build_irregular_simulation(workspace, geometry, mesh, lake_cells)
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"Irregular triangle LAK run did not converge:\n{buff}")

    period_stages = _stage_per_period(gwf, geometry.n_periods)
    exchange = _exchange_flux_per_period(
        workspace / f"{_MODEL_NAME}.lak.budget.csv", geometry.n_periods
    )
    budget_percent = _max_budget_percent(workspace / f"{_MODEL_NAME}.lak.budget.csv")
    return GridRunResult(
        label="irregular_triangle",
        n_cells=mesh.n_cells,
        is_structured=mesh.is_structured,
        n_lake_cells=len(lake_cells),
        connection_counts=dict(Counter(str(r[3]).upper() for r in connectiondata)),
        period_stages=period_stages,
        steady_exchange_m3_per_s=exchange[0],
        final_exchange_m3_per_s=exchange[-1],
        max_budget_percent=budget_percent,
    )


def _run_regular(workspace: Path, geometry: PleasantTransientGeometry) -> GridRunResult:
    """Run the regular quad-grid case and read its lake-aquifer exchange flux."""
    hmp: TransientLakeRunResult = run_hmp(workspace, geometry=geometry)
    budget_path = workspace / "lakplsnt.lak.budget.csv"
    exchange = _exchange_flux_per_period(budget_path, geometry.n_periods)
    return GridRunResult(
        label="regular_quad",
        n_cells=geometry.n_cells,
        is_structured=True,
        n_lake_cells=len(geometry.lake_cell_ids),
        connection_counts=dict(hmp.connection_counts),
        period_stages=hmp.period_stages,
        steady_exchange_m3_per_s=exchange[0],
        final_exchange_m3_per_s=exchange[-1],
        max_budget_percent=max(abs(p) for p in hmp.period_budget_percent),
    )


def _max_budget_percent(path: Path) -> float:
    """Worst absolute LAK percent discrepancy across all steps."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return max(abs(float(r["PERCENT_DIFFERENCE"])) for r in rows)


def run_grid_equivalence_scenario(*, workspace: Path) -> GridEquivalenceScenario:
    """Run the regular and irregular grids and assemble the comparison."""
    geometry = load_geometry()
    workspace.mkdir(parents=True, exist_ok=True)
    regular = _run_regular(workspace / "regular", geometry)
    irregular = _run_irregular(workspace / "irregular", geometry)
    abs_diff = tuple(
        abs(r - i) for r, i in zip(regular.period_stages, irregular.period_stages, strict=True)
    )
    return GridEquivalenceScenario(
        geometry=geometry,
        regular=regular,
        irregular=irregular,
        per_period_abs_diff_m=abs_diff,
    )


def load_tolerances() -> dict:
    """Load the grid-equivalence tolerances from the dedicated TOML."""
    import tomllib

    path = CASE_DIR / "tolerances_grid_equivalence.toml"
    with path.open("r", encoding="utf-8") as fh:
        return tomllib.loads(fh.read().lstrip("﻿"))


__all__ = [
    "GridEquivalenceScenario",
    "GridRunResult",
    "load_tolerances",
    "run_grid_equivalence_scenario",
]
