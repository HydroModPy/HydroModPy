"""HMP-side build of ex-gwf-lak-p01 through the home-grown DISV LAK builder.

This is the path under validation: the same single surface lake on the same
five-layer aquifer, but built in SI (meters/seconds) through HMP's
``solver/modflow6/builders/lake.py`` on a DISV grid. The CONNECTIONDATA is the
home-grown VERTICAL + HORIZONTAL set (NOT ``get_lak_connections``), the abacus is
emitted as a ``ModflowUtllaktab`` and the per-lake rainfall / evaporation ride the
LAK ``perioddata`` after unit conversion.

``build_hmp_solver_mesh`` and ``build_hmp_connectiondata`` are pure (no solver
run) so the builder unit test can isolate the CONNECTIONDATA path; ``run_hmp``
assembles the full simulation and runs MF6 for the numerical comparison.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from hydromodpy.solver.modflow6.builders.lake import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_connectiondata,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

from .geometry import LakeP01Geometry, load_geometry
from .reference import LakeRunResult, read_lake_budget_csv

_MODEL_NAME = "lakp01hmp"


def _variable_spacing_planar_mesh(*, delr_m: np.ndarray, delc_m: np.ndarray) -> HydroMesh:
    """Build a structured quad ``HydroMesh`` honouring variable column/row widths.

    Cumulative edges give the real p01 cell sizes; rows run top (highest y) to
    bottom so flat row-major cell ids match the upstream ``(row, col)`` order.
    """
    nrow = int(delc_m.size)
    ncol = int(delr_m.size)
    x_edges = np.concatenate([[0.0], np.cumsum(delr_m)])
    y_edges = np.concatenate([[0.0], np.cumsum(delc_m[::-1])])[::-1]
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


def build_hmp_solver_mesh(geometry: LakeP01Geometry) -> SolverMesh:
    """Build the SI ``SolverMesh`` (all cells active, no lake mask yet)."""
    planar = _variable_spacing_planar_mesh(delr_m=geometry.delr_m, delc_m=geometry.delc_m)
    n_cells = geometry.n_cells
    top = np.full(n_cells, geometry.top_m)
    botm = np.stack([np.full(n_cells, b) for b in geometry.botm_m])
    inactive = np.zeros((geometry.nlay, n_cells), dtype=bool)
    return SolverMesh(planar_mesh=planar, top=top, botm=botm, inactive_mask=inactive)


def _hmp_model(geometry: LakeP01Geometry) -> SimpleNamespace:
    """Build the minimal HMP-model namespace the LAK builder reads.

    The LAK builder only needs ``model_output_name``, ``time_units`` and the flow
    ``active_bc`` / ``sinks_sources.lakes`` payload; the rest of the model is built
    directly with flopy in :func:`run_hmp`.
    """
    abacus = geometry.abacus_si_rows()
    return SimpleNamespace(
        model_output_name=_MODEL_NAME,
        model_name=_MODEL_NAME,
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": None,
                        "bedleak": geometry.bedleak_per_s,
                        "abacus": abacus,
                        "stageinit": geometry.stage_init_m,
                        "rainfall": {"value": geometry.rainfall_m_per_s, "units": "m/s"},
                        "evaporation": {
                            "value": geometry.evaporation_m_per_s,
                            "units": "m/s",
                        },
                    }
                }
            },
        ),
    )


def build_hmp_connectiondata(
    geometry: LakeP01Geometry | None = None,
) -> list[list[Any]]:
    """Build the home-grown CONNECTIONDATA on the masked p01 mesh (no solver run)."""
    geom = geometry if geometry is not None else load_geometry()
    mesh = build_hmp_solver_mesh(geom)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": geom.lake_cell_ids})
    return build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=geom.lake_cell_ids,
        bedleak=geom.bedleak_per_s,
        solver_mesh=masked,
    )


def build_hmp_simulation(workspace: Path, *, geometry: LakeP01Geometry | None = None):
    """Build the full SI MF6 simulation with the home-grown LAK package."""
    import flopy

    geom = geometry if geometry is not None else load_geometry()
    exe = str(ensure_solver_binary("mf6"))
    mesh = build_hmp_solver_mesh(geom)
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lac0": geom.lake_cell_ids})

    model = _hmp_model(geom)
    lak_args = build_lak_package_args(
        model, solver_mesh=masked, lake_cell_ids_by_lake={"lac0": geom.lake_cell_ids}
    )
    assert lak_args is not None, "the lake must be active in the HMP build"
    laktab_specs = lak_args.pop("laktab_specs")
    lak_args.pop("obs_continuous", None)
    lak_args.pop("lake_obs_meta", None)
    lak_args.pop("mover_records", None)
    lak_args.pop("mover_maxpackages", None)

    sim = flopy.mf6.MFSimulation(sim_name=_MODEL_NAME, sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=((geom.period_length_seconds, geom.n_steps, geom.ts_multiplier),),
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
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=geom.specific_yield, ss=geom.specific_storage_per_s)
    flopy.mf6.ModflowGwfic(gwf, strt=geom.strt_m)

    chd_spd: list[list[Any]] = []
    for lay in range(geom.nlay):
        for r in range(geom.nrow):
            chd_spd.append([(lay, r * geom.ncol + 0), geom.head_left_m])
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


def run_hmp(workspace: Path, *, geometry: LakeP01Geometry | None = None) -> LakeRunResult:
    """Build, run, and summarise the HMP SI LAK build."""
    from collections import Counter

    sim, gwf, connectiondata = build_hmp_simulation(workspace, geometry=geometry)
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError(f"HMP LAK run did not converge:\n{buff}")

    final_stage = float(np.ravel(gwf.lak.output.stage().get_data())[-1])
    gwf_in, gwf_out, percent = read_lake_budget_csv(workspace / f"{_MODEL_NAME}.lak.budget.csv")
    counts = Counter(str(row[3]).upper() for row in connectiondata)
    return LakeRunResult(
        label="hmp",
        workspace=workspace,
        length_unit="meters",
        final_stage=final_stage,
        lake_gwf_in=gwf_in,
        lake_gwf_out=gwf_out,
        budget_percent_discrepancy=percent,
        n_connections=len(connectiondata),
        connection_counts=dict(counts),
    )


__all__ = [
    "build_hmp_connectiondata",
    "build_hmp_simulation",
    "build_hmp_solver_mesh",
    "run_hmp",
]
