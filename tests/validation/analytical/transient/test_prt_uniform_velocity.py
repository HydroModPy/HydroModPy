"""WP15 - PRT analytical validation on a uniform velocity field.

For a constant-gradient (uniform) flow field, Pollock's method is exact, so a
particle moves as ``x(t) = x0 + v*t`` with ``v = q / porosity`` (``q`` is the
specific discharge). The pore velocity ``v`` is read back from the model's
DATA-SPDIS instead of being hard-coded, then the track positions are checked
against the analytical streamline.

Tolerance rationale - ``tests/TOLERANCES.md`` row 34: max relative position
error < 1 % (Pollock is exact for uniform velocity; the allowance covers
cell-crossing arithmetic).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from tests._helpers.tolerances import tol


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_prt_uniform_velocity_streamline(tmp_path) -> None:
    import flopy

    max_rel = tol("mf6_prt_uniform_velocity_streamline")  # TOLERANCES.md row 34
    exe = str(ensure_solver_binary("mf6"))
    ncol, dx, porosity = 20, 1.0, 0.25
    x0 = 2.5  # cell 2 center
    track_times = [20.0, 40.0]

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(100.0, 1, 1.0)], time_units="seconds")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=1, ncol=ncol, delr=dx, delc=1.0, top=1.0, botm=0.0)
    flopy.mf6.ModflowGwfic(gwf, strt=1.5)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0, save_specific_discharge=True)
    flopy.mf6.ModflowGwfchd(
        gwf, stress_period_data={0: [[(0, 0, 0), 2.0], [(0, 0, ncol - 1), 1.0]]}
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )

    prt = flopy.mf6.ModflowPrt(sim, modelname="prt")
    flopy.mf6.ModflowPrtdis(prt, nlay=1, nrow=1, ncol=ncol, delr=dx, delc=1.0, top=1.0, botm=0.0)
    flopy.mf6.ModflowPrtmip(prt, porosity=porosity)
    flopy.mf6.ModflowPrtprp(
        prt,
        nreleasepts=1,
        packagedata=[(0, (0, 0, 2), x0, 0.5, 0.5)],
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

    import flopy.utils.binaryfile as bf

    try:
        cbb = bf.CellBudgetFile(str(tmp_path / "flow.cbc"))
        spdis = cbb.get_data(text="DATA-SPDIS")[0]
    except Exception:
        cbb = bf.CellBudgetFile(str(tmp_path / "flow.cbc"), precision="double")
        spdis = cbb.get_data(text="DATA-SPDIS")[0]
    qx = float(np.mean(np.asarray(spdis["qx"])[5:15]))  # uniform interior specific discharge
    v = qx / porosity  # pore velocity

    track = pd.read_csv(tmp_path / "prt.trk.csv")
    time_col = "t" if "t" in track.columns else "time"
    for t in track_times:
        rows = track[np.isclose(track[time_col], t)]
        assert not rows.empty, f"no track sample at t={t}"
        x_computed = float(rows["x"].iloc[0])
        x_expected = x0 + v * t
        rel_error = abs(x_computed - x_expected) / abs(v * t)
        assert rel_error < max_rel, (
            f"t={t}: x={x_computed}, expected {x_expected} (v={v}); rel error {rel_error}"
        )
