"""Ogata-Banks (1961) 1D advection-dispersion benchmark against MODFLOW 6 GWT.

A semi-infinite column is initially solute-free and subjected to a
constant-concentration injection ``c0`` at ``x = 0`` under steady uniform
flow of pore velocity ``v`` with longitudinal dispersion coefficient
``D``. The analytical solution is the Ogata-Banks profile::

    c(x, t) = c0 / 2 * [ erfc((x - v t) / (2 sqrt(D t)))
                        + exp(v x / D) * erfc((x + v t) / (2 sqrt(D t))) ]

The reference is a 1D MF6 GWF + GWT model: flow is driven by a constant
injection flux on the left and a CHD sink on the right producing a
uniform pore velocity ``v``; transport is solved with a constant
concentration ``c0`` at the inlet and an open boundary at the outlet.
Numerical and analytical concentrations are compared at probe points
along the column at three times.

Tolerance rationale — ``tests/TOLERANCES.md`` row 7: NSE > 0.95 across
all (x, t) probes with a maximum pointwise relative error below 3 %.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.special import erfc

from tests.regression.golden_utils import assert_required_executables


COLUMN_LENGTH_M = 50.0
N_CELLS = 500
CELL_SIZE_M = COLUMN_LENGTH_M / N_CELLS
POROSITY = 0.3

PORE_VELOCITY_M_PER_DAY = 0.1
DISPERSION_M2_PER_DAY = 0.01

INLET_CONCENTRATION = 1.0
INITIAL_CONCENTRATION = 0.0

DURATION_D = 100.0
N_TRANSPORT_STEPS = 200  # dt = 0.5 day, Courant ~ 0.5 for v=0.1, dx=0.1

OBSERVATION_X_M = (1.0, 5.0, 10.0, 20.0)
OBSERVATION_TIMES_D = (20.0, 60.0, 100.0)


def _ogata_banks_concentration(x_m: float, t_d: float) -> float:
    """Return ``c(x, t)`` for the Ogata-Banks semi-infinite column solution."""
    v = PORE_VELOCITY_M_PER_DAY
    d = DISPERSION_M2_PER_DAY
    denom = 2.0 * math.sqrt(d * t_d)
    term1 = erfc((x_m - v * t_d) / denom)
    # ``exp(v x / D)`` can overflow float64 when v x / D is large; in that
    # regime ``erfc((x + v t) / denom)`` is vanishingly small and the product
    # is well-defined as zero. We compute the log-product to avoid issues.
    exp_arg = v * x_m / d
    erfc_arg = (x_m + v * t_d) / denom
    if exp_arg > 700.0:  # beyond float64 range for plain exp
        # log(erfc(y)) ~ -y^2 - log(y sqrt(pi)) for large y
        if erfc_arg > 0.0:
            log_erfc = -erfc_arg * erfc_arg - math.log(erfc_arg * math.sqrt(math.pi))
        else:
            log_erfc = math.log(erfc(erfc_arg))
        log_product = exp_arg + log_erfc
        term2 = math.exp(log_product) if log_product < 700.0 else float("inf")
    else:
        term2 = math.exp(exp_arg) * erfc(erfc_arg)
    return float(INLET_CONCENTRATION * 0.5 * (term1 + term2))


def _build_and_run_ogata_banks_model(
    workspace: Path,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the coupled GWF + GWT model and return ``(numerical, analytical)`` grids.

    The returned arrays are shaped ``(len(times), len(x_probes))``.
    """
    import flopy

    repo_root = Path(__file__).resolve().parents[4]
    mf6_exe = repo_root / "bin" / "linux" / "mf6"

    # Aquifer geometry — unit cross-section, uniform cells.
    aquifer_top = 1.0
    aquifer_bot = 0.0
    aquifer_thickness = aquifer_top - aquifer_bot
    hydraulic_conductivity = 1.0  # m/day — chosen with the head gradient so v matches

    # For pore velocity v = K * i / n  ⇒  head gradient i = v n / K.
    head_gradient = PORE_VELOCITY_M_PER_DAY * POROSITY / hydraulic_conductivity
    head_left = head_gradient * COLUMN_LENGTH_M
    head_right = 0.0

    sim = flopy.mf6.MFSimulation(
        sim_name="ogatabanks",
        sim_ws=str(workspace),
        exe_name=str(mf6_exe),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=1,
        perioddata=[(DURATION_D, N_TRANSPORT_STEPS, 1.0)],
    )

    # ----- Flow model ------------------------------------------------------
    gwf_name = "gwf1d"
    gwf = flopy.mf6.ModflowGwf(sim, modelname=gwf_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwf_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        linear_acceleration="CG",
    )
    sim.register_ims_package(sim.get_package(f"{gwf_name}.ims"), [gwf_name])

    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1,
        nrow=1,
        ncol=N_CELLS,
        delr=CELL_SIZE_M,
        delc=1.0,
        top=aquifer_top,
        botm=aquifer_bot,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=head_left)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=hydraulic_conductivity)
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=0.0,
        sy=0.0,
        steady_state={0: True},
    )
    # Carry a CONCENTRATION auxiliary on CHD so the GWT SSM package can
    # assign entering-water concentration; exiting water uses the local
    # cell concentration automatically.
    flopy.mf6.ModflowGwfchd(
        gwf,
        auxiliary=["CONCENTRATION"],
        stress_period_data={
            0: [
                ((0, 0, 0), head_left, 0.0),
                ((0, 0, N_CELLS - 1), head_right, 0.0),
            ]
        },
        pname="CHD-1",
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{gwf_name}.cbc",
        head_filerecord=f"{gwf_name}.hds",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "ALL")],
    )

    # ----- Transport model -------------------------------------------------
    gwt_name = "gwt1d"
    gwt = flopy.mf6.ModflowGwt(sim, modelname=gwt_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        linear_acceleration="BICGSTAB",
    )
    sim.register_ims_package(sim.get_package(f"{gwt_name}.ims"), [gwt_name])

    flopy.mf6.ModflowGwtdis(
        gwt,
        nlay=1,
        nrow=1,
        ncol=N_CELLS,
        delr=CELL_SIZE_M,
        delc=1.0,
        top=aquifer_top,
        botm=aquifer_bot,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwtic(gwt, strt=INITIAL_CONCENTRATION)
    flopy.mf6.ModflowGwtadv(gwt, scheme="TVD")
    # Longitudinal dispersion only (1D column). The DSP package expects
    # the longitudinal dispersivity alpha_L; with zero molecular diffusion
    # the effective coefficient is alpha_L * |v|. So alpha_L = D / v.
    alpha_l = DISPERSION_M2_PER_DAY / PORE_VELOCITY_M_PER_DAY
    flopy.mf6.ModflowGwtdsp(gwt, xt3d_off=True, alh=alpha_l, ath1=alpha_l, diffc=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=POROSITY)
    flopy.mf6.ModflowGwtssm(gwt, sources=[["CHD-1", "AUX", "CONCENTRATION"]])
    flopy.mf6.ModflowGwtcnc(
        gwt,
        stress_period_data={0: [((0, 0, 0), INLET_CONCENTRATION)]},
    )
    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{gwt_name}.cbc",
        concentration_filerecord=f"{gwt_name}.ucn",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
    )

    flopy.mf6.ModflowGwfgwt(
        sim,
        exgtype="GWF6-GWT6",
        exgmnamea=gwf_name,
        exgmnameb=gwt_name,
    )

    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 Ogata-Banks simulation did not converge"

    conc_file = flopy.utils.HeadFile(
        workspace / f"{gwt_name}.ucn",
        text="CONCENTRATION",
    )
    times = np.asarray(conc_file.get_times())

    x_centers = np.arange(N_CELLS) * CELL_SIZE_M + 0.5 * CELL_SIZE_M

    numerical = np.zeros((len(OBSERVATION_TIMES_D), len(OBSERVATION_X_M)))
    analytical = np.zeros_like(numerical)
    for ti, requested_time in enumerate(OBSERVATION_TIMES_D):
        time_idx = int(np.argmin(np.abs(times - requested_time)))
        snapshot = conc_file.get_data(totim=times[time_idx])[0, 0, :]
        for xi, probe_x in enumerate(OBSERVATION_X_M):
            cell_idx = int(np.argmin(np.abs(x_centers - probe_x)))
            numerical[ti, xi] = float(snapshot[cell_idx])
            analytical[ti, xi] = _ogata_banks_concentration(
                float(x_centers[cell_idx]), float(times[time_idx])
            )

    return numerical, analytical


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.slow
def test_ogata_banks_1d_transport_matches_analytical_reference(tmp_path: Path) -> None:
    """Run the MF6 GWF+GWT column and compare ``c(x, t)`` to the Ogata-Banks profile."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    numerical, analytical = _build_and_run_ogata_banks_model(tmp_path)
    numerical_flat = numerical.ravel()
    analytical_flat = analytical.ravel()

    # Keep only probes with non-trivial analytical signal to avoid NaNs in
    # relative-error denominators. Values below this threshold are still
    # included in the NSE calculation.
    signal_mask = analytical_flat > 1e-3

    variance = float(np.sum((analytical_flat - analytical_flat.mean()) ** 2))
    residual = float(np.sum((numerical_flat - analytical_flat) ** 2))
    nse = 1.0 - residual / variance
    assert nse > 0.95, (
        f"Ogata-Banks NSE too low: {nse:.6f} (residual={residual:.3e}, "
        f"variance={variance:.3e})"
    )

    if signal_mask.any():
        relative_errors = np.abs(numerical_flat[signal_mask] - analytical_flat[signal_mask]) / np.abs(
            analytical_flat[signal_mask]
        )
        max_rel = float(relative_errors.max())
        assert max_rel < 0.03, (
            f"Ogata-Banks max relative error {max_rel:.4%} > 3%: "
            f"numerical={numerical_flat.tolist()}, analytical={analytical_flat.tolist()}"
        )
