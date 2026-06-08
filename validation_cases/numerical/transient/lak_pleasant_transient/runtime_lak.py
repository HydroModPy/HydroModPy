"""HMP-side build of the transient multi-layer LAK case via the DISV LAK builder.

This is the path under regression: one reservoir incised across the TOP 2 layers
of a 4-layer aquifer on a structured-as-DISV grid, built in SI (meters/seconds)
through HMP's ``solver/modflow6/builders/lake.py``. The CONNECTIONDATA carries
HORIZONTAL bank seepage in layers 0 and 1 plus a VERTICAL leakage to layer 2; the
abacus is emitted as a ``ModflowUtllaktab``; and the per-lake rainfall /
evaporation / runoff ride the LAK ``perioddata``, varying between stress periods.

``build_hmp_connectiondata`` is pure (no solver run) so the connection structure
can be inspected in isolation; ``run_hmp`` assembles the full transient simulation
and runs MF6 for the regression golden.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from hydromodpy.solver.modflow6.builders.lake import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_connectiondata,
    build_lake_period_data,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

from .geometry import PleasantTransientGeometry, load_geometry

_MODEL_NAME = "lakplsnt"
_LAKE_ID = "plainfield"


@dataclass(frozen=True, slots=True)
class TransientLakeRunResult:
    """Scalar per-period outputs of one finished transient LAK run (meters/seconds).

    ``period_stages`` is the lake stage at the END of each stress period.
    ``period_budget_percent`` is the LAK water-balance percent discrepancy at the
    end of each period. ``connection_counts`` maps the upper-cased claktype to its
    count and ``horizontal_by_layer`` the HORIZONTAL connection count per layer.
    """

    workspace: Path
    period_stages: tuple[float, ...]
    period_budget_percent: tuple[float, ...]
    n_connections: int
    connection_counts: dict[str, int] = field(default_factory=dict)
    horizontal_by_layer: dict[int, int] = field(default_factory=dict)


def _structured_planar_mesh(*, nrow: int, ncol: int, cell_size: float) -> HydroMesh:
    """Build a structured quad ``HydroMesh`` with uniform ``cell_size`` cells.

    Rows run top (highest y) to bottom so flat row-major cell ids match the
    ``(row, col)`` order used by the lake footprint.
    """
    x_edges = np.arange(ncol + 1, dtype=float) * cell_size
    y_edges = (np.arange(nrow + 1, dtype=float) * cell_size)[::-1]
    vertices = np.array(
        [[x_edges[i], y_edges[j]] for j in range(nrow + 1) for i in range(ncol + 1)],
        dtype=float,
    )
    connectivity = np.empty((nrow * ncol, 4), dtype=int)
    for r in range(nrow):
        for c in range(ncol):
            ic = r * ncol + c
            n0 = r * (ncol + 1) + c
            connectivity[ic] = [n0, n0 + 1, n0 + ncol + 2, n0 + ncol + 1]
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        structured_shape=(nrow, ncol),
    )


def build_hmp_solver_mesh(geometry: PleasantTransientGeometry) -> SolverMesh:
    """Build the SI ``SolverMesh`` (all cells active, no lake mask yet)."""
    planar = _structured_planar_mesh(
        nrow=geometry.nrow, ncol=geometry.ncol, cell_size=geometry.cell_size_m
    )
    n_cells = geometry.n_cells
    top = np.full(n_cells, geometry.top_m)
    botm = np.stack([np.full(n_cells, b) for b in geometry.botm_m])
    inactive = np.zeros((geometry.nlay, n_cells), dtype=bool)
    return SolverMesh(planar_mesh=planar, top=top, botm=botm, inactive_mask=inactive)


def _abacus(geometry: PleasantTransientGeometry) -> dict[str, list[float]]:
    """Return the Plainfield abacus as a ``{stage, volume, sarea}`` column mapping."""
    return {
        "stage": [row[0] for row in geometry.abacus_rows],
        "volume": [row[1] for row in geometry.abacus_rows],
        "sarea": [row[2] for row in geometry.abacus_rows],
    }


def _lake_definition(geometry: PleasantTransientGeometry, *, period: int) -> dict[str, Any]:
    """Lake definition for one stress period, with that period's forcing values."""
    return {
        "polygon": None,
        "bedleak": geometry.bedleak_per_s,
        "abacus": _abacus(geometry),
        "stageinit": geometry.stage_init_m,
        "rainfall": {"value": geometry.rainfall_m_per_s[period], "units": "m/s"},
        "evaporation": {"value": geometry.evaporation_m_per_s[period], "units": "m/s"},
        "runoff": {"value": geometry.runoff_m3_per_s[period], "units": "m3/s"},
    }


def _hmp_model(geometry: PleasantTransientGeometry) -> SimpleNamespace:
    """Minimal HMP-model namespace the LAK builder reads (period-0 forcings)."""
    return SimpleNamespace(
        model_output_name=_MODEL_NAME,
        model_name=_MODEL_NAME,
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={"lakes": {_LAKE_ID: _lake_definition(geometry, period=0)}},
        ),
    )


def build_hmp_connectiondata(
    geometry: PleasantTransientGeometry | None = None,
) -> list[list[Any]]:
    """Build the multi-layer CONNECTIONDATA on the masked mesh (no solver run)."""
    geom = geometry if geometry is not None else load_geometry()
    mesh = build_hmp_solver_mesh(geom)
    masked = apply_lake_idomain_mask(
        mesh,
        lake_cell_ids_by_lake={_LAKE_ID: geom.lake_cell_ids},
        occupied_layers=geom.occupied_layers,
    )
    return build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=geom.lake_cell_ids,
        bedleak=geom.bedleak_per_s,
        solver_mesh=masked,
        occupied_layers=geom.occupied_layers,
    )


def horizontal_connections_by_layer(connectiondata: list[list[Any]]) -> dict[int, int]:
    """Count HORIZONTAL connections per layer (proves the multi-layer geometry)."""
    counts: Counter[int] = Counter()
    for row in connectiondata:
        if str(row[3]).upper() == "HORIZONTAL":
            counts[int(row[2][0])] += 1
    return dict(sorted(counts.items()))


def _build_lak_period_data(geometry: PleasantTransientGeometry) -> dict[int, list[list[Any]]]:
    """Build the LAK ``perioddata`` for every stress period via the production builder."""
    perioddata: dict[int, list[list[Any]]] = {}
    for period in range(geometry.n_periods):
        lakes = {_LAKE_ID: _lake_definition(geometry, period=period)}
        perioddata[period] = build_lake_period_data(None, lakes=lakes)[0]
    return perioddata


def build_hmp_simulation(workspace: Path, *, geometry: PleasantTransientGeometry | None = None):
    """Build the full transient SI MF6 simulation with the multi-layer LAK package."""
    import flopy

    geom = geometry if geometry is not None else load_geometry()
    exe = str(ensure_solver_binary("mf6"))
    mesh = build_hmp_solver_mesh(geom)
    masked = apply_lake_idomain_mask(
        mesh,
        lake_cell_ids_by_lake={_LAKE_ID: geom.lake_cell_ids},
        occupied_layers=geom.occupied_layers,
    )

    model = _hmp_model(geom)
    lak_args = build_lak_package_args(
        model,
        solver_mesh=masked,
        lake_cell_ids_by_lake={_LAKE_ID: geom.lake_cell_ids},
        occupied_layers=geom.occupied_layers,
    )
    assert lak_args is not None, "the lake must be active in the HMP build"
    laktab_specs = lak_args.pop("laktab_specs")
    lak_args.pop("obs_continuous", None)
    lak_args.pop("lake_obs_meta", None)
    lak_args.pop("mover_records", None)
    lak_args.pop("mover_maxpackages", None)
    # Replace the single-period perioddata the builder seeds with the full
    # per-period forcing schedule, built through the same production helper.
    lak_args["perioddata"] = _build_lak_period_data(geom)

    sim = flopy.mf6.MFSimulation(sim_name=_MODEL_NAME, sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim,
        nper=geom.n_periods,
        perioddata=geom.tdis_perioddata,
        time_units="seconds",
    )
    ims = flopy.mf6.ModflowIms(
        sim,
        print_option="summary",
        complexity="MODERATE",
        linear_acceleration="bicgstab",
        outer_maximum=geom.outer_maximum,
        outer_dvclose=geom.outer_dvclose,
        inner_maximum=geom.inner_maximum,
        inner_dvclose=geom.inner_dvclose,
        rcloserecord=f"{geom.rclose} strict",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname=_MODEL_NAME, newtonoptions="newton", save_flows=True)
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=geom.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain(),
        length_units="meters",
    )
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,
        k=geom.k11_m_per_s,
        k33=list(geom.k33_m_per_s),
        save_specific_discharge=True,
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        sy=geom.specific_yield,
        ss=geom.specific_storage_per_s,
        steady_state=geom.steady_state_flags,
        transient=geom.transient_flags,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=geom.strt_m)

    # Constant heads on the left / right columns, only in layers whose bottom sits
    # below the boundary head (MF6 rejects a CHD head below its cell bottom). The
    # upper, partially saturated layers reach equilibrium through NPF.
    chd_spd: list[list[Any]] = []
    for lay in range(geom.nlay):
        botm = geom.botm_m[lay]
        for r in range(geom.nrow):
            if geom.head_left_m > botm:
                chd_spd.append([(lay, r * geom.ncol + 0), geom.head_left_m])
            if geom.head_right_m > botm:
                chd_spd.append([(lay, r * geom.ncol + (geom.ncol - 1)), geom.head_right_m])
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd_spd})
    flopy.mf6.ModflowGwfrcha(gwf, recharge=geom.recharge_m_per_s)

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


def _stage_per_period(gwf, n_periods: int) -> tuple[float, ...]:
    """Return the lake stage at the end of every stress period (last step of each)."""
    stage_obj = gwf.lak.output.stage()
    kstpkper = stage_obj.get_kstpkper()
    last_by_period: dict[int, tuple[int, int]] = {}
    for kstp, kper in kstpkper:
        last_by_period[int(kper)] = (int(kstp), int(kper))
    stages: list[float] = []
    for period in range(n_periods):
        data = stage_obj.get_data(kstpkper=last_by_period[period])
        stages.append(float(np.ravel(data)[-1]))
    return tuple(stages)


def _budget_percent_per_period(path: Path, n_periods: int) -> tuple[float, ...]:
    """Return the LAK percent-discrepancy at the end of every stress period.

    The LAK ``budgetcsv`` is one row per time step with ``totim`` and the period /
    step indices implicit in the cumulative time; we take the last row whose
    cumulative time falls in each period by reading the per-row balance and keeping
    the last row of each period from the equally spaced step schedule.
    """
    import csv

    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Empty LAK budget CSV: {path}")
    percents = [float(r["PERCENT_DIFFERENCE"]) for r in rows]
    return _last_value_per_period(percents, n_periods)


def _last_value_per_period(values: list[float], n_periods: int) -> tuple[float, ...]:
    """Split an equally periodic per-step series into per-period last values.

    The first period is steady (1 step); the remaining periods share an equal step
    count, so we recover the boundaries from the total row count.
    """
    total = len(values)
    transient_periods = n_periods - 1
    if transient_periods <= 0:
        return (values[-1],)
    steady_steps = 1
    remaining = total - steady_steps
    if remaining % transient_periods != 0:
        # Fall back to a single closing value if the schedule is irregular.
        return tuple([values[-1]] * n_periods)
    per_transient = remaining // transient_periods
    out = [values[steady_steps - 1]]
    for p in range(transient_periods):
        idx = steady_steps + (p + 1) * per_transient - 1
        out.append(values[idx])
    return tuple(out)


def run_hmp(
    workspace: Path, *, geometry: PleasantTransientGeometry | None = None
) -> TransientLakeRunResult:
    """Build, run, and summarise the transient multi-layer HMP LAK build."""
    geom = geometry if geometry is not None else load_geometry()
    sim, gwf, connectiondata = build_hmp_simulation(workspace, geometry=geom)
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"HMP transient LAK run did not converge:\n{buff}")

    period_stages = _stage_per_period(gwf, geom.n_periods)
    period_percent = _budget_percent_per_period(
        workspace / f"{_MODEL_NAME}.lak.budget.csv", geom.n_periods
    )
    counts = Counter(str(row[3]).upper() for row in connectiondata)
    return TransientLakeRunResult(
        workspace=workspace,
        period_stages=period_stages,
        period_budget_percent=period_percent,
        n_connections=len(connectiondata),
        connection_counts=dict(counts),
        horizontal_by_layer=horizontal_connections_by_layer(connectiondata),
    )


__all__ = [
    "TransientLakeRunResult",
    "build_hmp_connectiondata",
    "build_hmp_simulation",
    "build_hmp_solver_mesh",
    "horizontal_connections_by_layer",
    "run_hmp",
]
