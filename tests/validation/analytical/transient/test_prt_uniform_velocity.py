"""MODFLOW 6 PRT particle paths in a uniform velocity field.

Compared with: the straight particle path `x(t) = x0 + v t` in a uniform flow, `v = q / porosity`.

For a constant-gradient (uniform) flow field, Pollock's method is exact, so a
particle moves as ``x(t) = x0 + v*t`` with ``v = q / porosity`` (``q`` is the
specific discharge). The pore velocity ``v`` is read back from the model's
DATA-SPDIS instead of being hard-coded, then the track positions are checked
against the analytical streamline.

Three grids run the same strip. ``modflow6`` is a rectilinear DIS column.
``modflow6_irregular_tri`` and ``modflow6_voronoi`` are DISV strips of
jittered triangles and Voronoi polygons (``tests/validation/helpers/disv_meshes.py``),
the topology HydroModPy always gives PRT. The end cells hold the exact linear
head at their centres, so the flow is uniform for any mesh whose flux is
consistent. The triangle strip has a p95 connection non-orthogonality of 40 deg,
above the 30 deg trigger, so HydroModPy's rule switches XT3D on and the test runs
with it; the Voronoi strip is orthogonal and runs with the two-point flux.

Control run on the same triangles with the two-point flux (XT3D off): the
streamline is off by 17 %, so the non-orthogonal flux, not the tracking, is
what XT3D repairs. Measured here with XT3D as the rule decides: triangles 2.5e-4,
Voronoi 2.6e-6, DIS 1e-15.

Tolerance rationale - ``tests/TOLERANCES.md`` row 34: max relative position
error < 1 % (Pollock is exact for uniform velocity; the allowance covers
cell-crossing arithmetic). The same row holds for the DISV strips, where the
polygons are split into sub-cells for tracking. The transverse drift of the
particle is held to the same bound.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from tests._helpers.tolerances import tol
from tests.validation.helpers import assert_metric_below
from tests.validation.helpers.disv_meshes import strip_mesh

NOT_APPLICABLE = {
    "modflow_nwt": (
        "MODFLOW-NWT has no PRT. HydroModPy tracks particles on NWT with MODPATH 6, "
        "a separate code with its own input; this file runs the MODFLOW 6 PRT package."
    ),
    "boussinesq": (
        "The Boussinesq solver has no particle tracking: the registry holds no transport "
        "adapter for it and the solver page lists its transport as refused. "
        "This file runs MODFLOW 6 PRT."
    ),
    "boussinesq_local": (
        "The Boussinesq solver has no particle tracking: the registry holds no transport "
        "adapter for it and the solver page lists its transport as refused. "
        "This file runs MODFLOW 6 PRT."
    ),
}

STRIP_LENGTH_M = 20.0
STRIP_WIDTH_M = 3.0
DISV_SPACING_M = 1.0
# Of 120 triangles the p95 of the non-orthogonality moves from 30 to 40 deg with the seed, so the seed
# is pinned to one whose strip is clearly above the 30 deg XT3D trigger (40.5 deg, 16 % of connections).
DISV_JITTER = 0.45
DISV_SEED = 1
DISV_KIND = {"modflow6_irregular_tri": "triangle", "modflow6_voronoi": "voronoi"}


def _read_spdis(workspace: Path) -> np.ndarray:
    import flopy.utils.binaryfile as bf

    try:
        cbb = bf.CellBudgetFile(str(workspace / "flow.cbc"))
        return cbb.get_data(text="DATA-SPDIS")[0]
    except Exception:
        cbb = bf.CellBudgetFile(str(workspace / "flow.cbc"), precision="double")
        return cbb.get_data(text="DATA-SPDIS")[0]


def _run_prt_strip(
    workspace: Path, solver: str, force_xt3d: bool | None = None
) -> tuple[float, float, str]:
    """Run flow + PRT on the strip and return ``(x error, y drift, grid note)``.

    Both errors are relative to the distance ``v t`` travelled at the last
    track time. ``modflow6`` is the rectilinear DIS column; the other solvers
    are DISV strips. ``force_xt3d`` overrides HydroModPy's XT3D rule (control runs).
    """
    import flopy

    exe = str(ensure_solver_binary("mf6"))
    porosity = 0.25
    x0 = 2.5  # centre of the third unit-wide cell
    y0 = 0.5 if solver == "modflow6" else 0.5 * STRIP_WIDTH_M
    track_times = [20.0, 40.0]
    head_left, head_right = 2.0, 1.0

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(workspace), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(100.0, 1, 1.0)], time_units="seconds")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    prt = flopy.mf6.ModflowPrt(sim, modelname="prt")

    if solver == "modflow6":
        ncol, dx = 20, 1.0
        dis = {"nlay": 1, "nrow": 1, "ncol": ncol, "delr": dx, "delc": 1.0}
        flopy.mf6.ModflowGwfdis(gwf, top=1.0, botm=0.0, **dis)
        flopy.mf6.ModflowPrtdis(prt, top=1.0, botm=0.0, **dis)
        chd = [[(0, 0, 0), head_left], [(0, 0, ncol - 1), head_right]]
        release_cell: tuple = (0, 0, 2)
        release_xyz = (x0, y0, 0.5)
        interior = slice(5, 15)
        note = "DIS 20 x 1"
        xt3d = None
        linear_acceleration = "CG"
    else:
        mesh = strip_mesh(
            DISV_KIND[solver],
            length=STRIP_LENGTH_M,
            width=STRIP_WIDTH_M,
            spacing=DISV_SPACING_M,
            jitter=DISV_JITTER,
            seed=DISV_SEED,
            top=1.0,
            botm=[0.0],
        )
        flopy.mf6.ModflowGwfdisv(gwf, **mesh.disv_kwargs())
        flopy.mf6.ModflowPrtdisv(prt, **mesh.disv_kwargs())
        xc = mesh.centers[:, 0]
        # Exact linear head h(x) = 2 - (x - 0.5) / 19 held on the cells that touch an end.
        slope = (head_left - head_right) / (STRIP_LENGTH_M - DISV_SPACING_M)
        chd = [
            [(0, int(ic)), head_left - slope * (xc[ic] - 0.5 * DISV_SPACING_M)]
            for ic in mesh.cells_on_side("x", 0.0) + mesh.cells_on_side("x", STRIP_LENGTH_M)
        ]
        release_cell = (0, mesh.cell_containing(x0, y0))
        release_xyz = (x0, y0, 0.5)
        interior = np.flatnonzero((xc > 5.0) & (xc < 15.0))
        note = f"DISV {mesh.kind} {mesh.ncpl} cells; {mesh.xt3d_reason}"
        use_xt3d = mesh.xt3d if force_xt3d is None else force_xt3d
        xt3d = ["XT3D"] if use_xt3d else None
        linear_acceleration = "BICGSTAB" if xt3d else "CG"

    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE", linear_acceleration=linear_acceleration)
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfic(gwf, strt=1.5)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0, save_specific_discharge=True, xt3doptions=xt3d)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )

    flopy.mf6.ModflowPrtmip(prt, porosity=porosity)
    flopy.mf6.ModflowPrtprp(
        prt,
        nreleasepts=1,
        packagedata=[(0, release_cell, *release_xyz)],
        perioddata={0: ["FIRST"]},
        # flopy defaults COORDINATE_CHECK_METHOD to the dev-only "eager" tag,
        # which the release MF6 binary rejects; None suppresses it.
        coordinate_check_method=None,
    )
    flopy.mf6.ModflowPrtoc(
        prt,
        trackcsv_filerecord="prt.trk.csv",
        track_release=True,
        track_timestep=True,
        track_terminate=True,
        track_usertime=True,
        ntracktimes=len(track_times),
        tracktimes=[(t,) for t in track_times],
    )
    ems = flopy.mf6.ModflowEms(sim, filename="prt.ems")
    sim.register_solution_package(ems, [prt.name])
    flopy.mf6.ModflowGwfprt(sim, exgtype="GWF6-PRT6", exgmnamea="flow", exgmnameb="prt")

    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    if not success:
        raise AssertionError("PRT validation run did not terminate normally.")

    spdis = _read_spdis(workspace)
    qx = float(np.mean(np.asarray(spdis["qx"])[interior]))  # uniform interior specific discharge
    v = qx / porosity  # pore velocity

    track = pd.read_csv(workspace / "prt.trk.csv")
    time_col = "t" if "t" in track.columns else "time"
    x_errors, y_drifts = [], []
    for t in track_times:
        rows = track[np.isclose(track[time_col], t)]
        assert not rows.empty, f"no track sample at t={t}"
        travelled = abs(v * t)
        x_errors.append(abs(float(rows["x"].iloc[0]) - (x0 + v * t)) / travelled)
        y_drifts.append(abs(float(rows["y"].iloc[0]) - y0) / travelled)
    return max(x_errors), max(y_drifts), note


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.allow_subprocess
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow6", marks=pytest.mark.slow),
        pytest.param("modflow6_irregular_tri", marks=pytest.mark.fast),
        pytest.param("modflow6_voronoi", marks=pytest.mark.fast),
    ],
)
def test_prt_uniform_velocity_streamline(solver: str, tmp_path: Path) -> None:
    """Track one particle through the uniform strip and compare it to ``x0 + v t``."""
    max_rel = tol("mf6_prt_uniform_velocity_streamline")  # TOLERANCES.md row 34
    x_error, y_drift, _grid = _run_prt_strip(tmp_path, solver)
    assert_metric_below("Largest relative position error along the track", x_error, max_rel)
    assert_metric_below("Largest relative transverse drift of the particle", y_drift, max_rel)
