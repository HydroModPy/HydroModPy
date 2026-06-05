"""Audit P0 - MF6 GWT first-order decay analytical validation.

With no advection and no dispersion, a uniform initial concentration decays as
``C(t) = C0 * exp(-k t)`` under the MF6 MST first-order decay term. The MF6 GWT
clock is SECONDS, so the decay rate ``k`` is in ``1/s``. This guards the
per-second unit contract for ``transport.modflow6gwt.parameters.rate_decay``: a
per-day value would be ~86400x too large and annihilate the solute.

Tolerance rationale - ``tests/TOLERANCES.md`` row 35: max relative concentration
error < 1 % (decay is exact in MST; the allowance covers finite time-stepping).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from tests._helpers.tolerances import tol


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_gwt_first_order_decay_per_second(tmp_path) -> None:
    import flopy

    max_rel = tol("mf6_gwt_first_order_decay_0d")  # TOLERANCES.md row 35
    exe = str(ensure_solver_binary("mf6"))
    c0 = 1.0
    k = 1.0e-6  # 1/s on the SECONDS clock
    total_seconds = 1.0e6
    # MF6 MST integrates decay with implicit Euler (C_{n+1} = C_n / (1 + k*dt)),
    # first-order in time; 200 steps keep k*dt = 5e-3 small enough to stay within
    # the 1 % envelope of the analytical exp(-k t).
    nstp = 200
    sample_times = [2.5e5, 5.0e5, 1.0e6]

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim, nper=1, perioddata=[(total_seconds, nstp, 1.0)], time_units="seconds"
    )

    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    sim.register_ims_package(ims, [gwf.name])
    # Closed single cell: no boundary, no stress, so the flow field is zero and
    # only first-order decay acts on the stored solute (a 0D batch reactor).
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=1, ncol=1, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    flopy.mf6.ModflowGwfic(gwf, strt=1.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0)
    flopy.mf6.ModflowGwfsto(gwf, ss=1.0e-5, iconvert=0, transient={0: True})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )

    gwt = flopy.mf6.ModflowGwt(sim, modelname="trans")
    ims_t = flopy.mf6.ModflowIms(
        sim, complexity="SIMPLE", linear_acceleration="BICGSTAB", filename="trans.ims"
    )
    sim.register_ims_package(ims_t, [gwt.name])
    flopy.mf6.ModflowGwtdis(gwt, nlay=1, nrow=1, ncol=1, delr=1.0, delc=1.0, top=1.0, botm=0.0)
    flopy.mf6.ModflowGwtic(gwt, strt=c0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=0.25, first_order_decay=True, decay=k)
    flopy.mf6.ModflowGwtadv(gwt, scheme="upstream")
    flopy.mf6.ModflowGwtoc(
        gwt,
        concentration_filerecord="trans.ucn",
        saverecord=[("CONCENTRATION", "ALL")],
    )
    flopy.mf6.ModflowGwfgwt(sim, exgtype="GWF6-GWT6", exgmnamea="flow", exgmnameb="trans")

    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    if not success:
        raise AssertionError("GWT decay validation run did not terminate normally.")

    import flopy.utils.binaryfile as bf

    ucn = bf.HeadFile(str(tmp_path / "trans.ucn"), text="concentration")
    try:
        for t in sample_times:
            conc = float(np.asarray(ucn.get_data(totim=t)).reshape(-1)[0])
            expected = c0 * float(np.exp(-k * t))
            rel_error = abs(conc - expected) / abs(expected)
            assert rel_error < max_rel, (
                f"t={t}s: C={conc}, expected {expected} (k={k} 1/s); rel error {rel_error}"
            )
    finally:
        ucn.close()
