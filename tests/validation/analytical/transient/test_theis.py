"""Theis (1935) transient confined pumping benchmark against MODFLOW 6.

A fully penetrating well pumps at a constant rate ``Q`` in a homogeneous
isotropic confined aquifer of transmissivity ``T`` and storativity ``S``.
The drawdown field is radial::

    s(r, t) = Q / (4 pi T) * W(u),  u = r^2 S / (4 T t)

with well function ``W(u) = E_1(u)`` (exponential integral). The numerical
reference is an MF6 IMS-backed confined GWF model. The grid is
**telescoping** — a fine inner patch resolves the near-well drawdown and
coarse outer cells push the Dirichlet boundary far enough that its
influence on the observation window stays well below the test tolerance.
Drawdown is evaluated at three radial distances (10 m, 50 m, 100 m) and
three times (1 d, 3 d, 10 d) and compared pointwise against ``s(r, t)``.

Tolerance rationale — ``tests/TOLERANCES.md`` rows 4/5:
   * NSE against analytical drawdown must exceed 0.999.
   * Maximum absolute error across all (r, t) pairs: 1% relative.

Scope — ``solver_sanity``:
   The model is built directly on the flopy SDK (telescoping grid, central
   well, outer CHD ring) because the geometry sits outside what the
   hydromodpy launcher TOML exposes. This test therefore validates
   **MODFLOW 6 against the Theis analytical solution**, not the
   hydromodpy pipeline. It protects against solver-level regressions and
   bundled-binary drift, not against hydromodpy refactors.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.special import exp1

from tests.regression.golden_utils import assert_required_executables

PUMPING_RATE_M3_PER_DAY = 100.0
TRANSMISSIVITY_M2_PER_DAY = 100.0
STORATIVITY = 1.0e-4
AQUIFER_THICKNESS_M = 10.0
HYDRAULIC_CONDUCTIVITY_M_PER_DAY = TRANSMISSIVITY_M2_PER_DAY / AQUIFER_THICKNESS_M
SPECIFIC_STORAGE = STORATIVITY / AQUIFER_THICKNESS_M

# Telescoping grid: 1 m cells inside a 21-cell-wide fine patch, then
# geometric growth at 1.2 outward. With 40 growth cells per side the
# domain half-width reaches ~8.8 km — well beyond the radius of
# influence r_i ~ sqrt(4 T t / S) ~ 6.3 km at t = 10 d.
MIN_CELL_SIZE_M = 1.0
GROWTH_RATIO = 1.2
N_UNIFORM_SIDE = 10
N_GROWTH_SIDE = 40

OBSERVATION_RADII_M = (10.0, 50.0, 100.0)
OBSERVATION_TIMES_D = (1.0, 3.0, 10.0)

INITIAL_HEAD_M = 50.0

N_STRESS_PERIODS = 10
PERIOD_LENGTH_D = 1.0
NSTP_PER_PERIOD = 20


def _build_telescoping_axis() -> np.ndarray:
    """Return ``delr`` / ``delc`` array symmetric about a central cell.

    Central cell has size ``MIN_CELL_SIZE_M``; ``N_UNIFORM_SIDE`` cells of
    the same size flank each side, then ``N_GROWTH_SIDE`` cells grow by
    ``GROWTH_RATIO`` outward. The resulting axis is symmetric and odd,
    putting the well exactly at the middle cell.
    """
    side: list[float] = [MIN_CELL_SIZE_M] * N_UNIFORM_SIDE
    current = MIN_CELL_SIZE_M
    for _ in range(N_GROWTH_SIDE):
        current *= GROWTH_RATIO
        side.append(current)
    return np.asarray(list(reversed(side)) + [MIN_CELL_SIZE_M] + side, dtype=float)


def _cell_centers(delta: np.ndarray) -> np.ndarray:
    """Return cell-centre coordinates for an axis with cell widths ``delta``."""
    edges = np.concatenate(([0.0], np.cumsum(delta)))
    return 0.5 * (edges[:-1] + edges[1:])


def _theis_drawdown(radius_m: float, elapsed_d: float) -> float:
    """Return the analytical Theis drawdown ``s = Q / (4 pi T) * W(u)``."""
    u = (radius_m * radius_m * STORATIVITY) / (4.0 * TRANSMISSIVITY_M2_PER_DAY * elapsed_d)
    return float(PUMPING_RATE_M3_PER_DAY / (4.0 * math.pi * TRANSMISSIVITY_M2_PER_DAY) * exp1(u))


def _build_and_run_theis_model(workspace: Path) -> tuple[list[float], list[float]]:
    """Run the MF6 confined Theis model and return numerical/analytical drawdowns.

    The returned lists are ordered ``[(r, t) for r in radii for t in times]``.
    """
    import flopy  # local import — heavy dependency

    repo_root = Path(__file__).resolve().parents[4]
    mf6_exe = repo_root / "bin" / "linux" / "mf6"

    delr = _build_telescoping_axis()
    delc = delr.copy()
    n_cells = int(delr.size)
    centre_index = n_cells // 2
    x_centers = _cell_centers(delr)
    y_centers = _cell_centers(delc)
    well_x = x_centers[centre_index]
    well_y = y_centers[centre_index]

    sim = flopy.mf6.MFSimulation(
        sim_name="theis",
        sim_ws=str(workspace),
        exe_name=str(mf6_exe),
        version="mf6",
    )

    tdis_perioddata = [(PERIOD_LENGTH_D, NSTP_PER_PERIOD, 1.2) for _ in range(N_STRESS_PERIODS)]
    flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=N_STRESS_PERIODS,
        perioddata=tdis_perioddata,
    )
    flopy.mf6.ModflowIms(
        sim,
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-6,
        inner_dvclose=1e-8,
        linear_acceleration="CG",
    )

    gwf = flopy.mf6.ModflowGwf(sim, modelname="theis", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1,
        nrow=n_cells,
        ncol=n_cells,
        delr=delr,
        delc=delc,
        top=INITIAL_HEAD_M,
        botm=INITIAL_HEAD_M - AQUIFER_THICKNESS_M,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=INITIAL_HEAD_M)
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=0,  # confined
        k=HYDRAULIC_CONDUCTIVITY_M_PER_DAY,
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=SPECIFIC_STORAGE,
        sy=0.0,
        steady_state={0: False},
        transient={0: True},
    )

    well_record = [((0, centre_index, centre_index), -PUMPING_RATE_M3_PER_DAY)]
    wel_spd = {period: well_record for period in range(N_STRESS_PERIODS)}
    flopy.mf6.ModflowGwfwel(gwf, stress_period_data=wel_spd)

    chd_cells: list[tuple[tuple[int, int, int], float]] = []
    for col in range(n_cells):
        chd_cells.append(((0, 0, col), INITIAL_HEAD_M))
        chd_cells.append(((0, n_cells - 1, col), INITIAL_HEAD_M))
    for row in range(1, n_cells - 1):
        chd_cells.append(((0, row, 0), INITIAL_HEAD_M))
        chd_cells.append(((0, row, n_cells - 1), INITIAL_HEAD_M))
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd_cells})

    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{gwf.name}.hds",
        saverecord=[("HEAD", "ALL")],
    )

    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 Theis simulation did not converge"

    head_file = flopy.utils.HeadFile(workspace / f"{gwf.name}.hds")
    totim_array = np.asarray(head_file.get_times())

    numerical: list[float] = []
    analytical: list[float] = []
    for radius in OBSERVATION_RADII_M:
        # Observations along the +x axis from the well cell.
        target_x = well_x + radius
        obs_j = int(np.argmin(np.abs(x_centers - target_x)))
        obs_i = centre_index
        discrete_radius = math.sqrt(
            (x_centers[obs_j] - well_x) ** 2 + (y_centers[obs_i] - well_y) ** 2
        )
        for requested_time in OBSERVATION_TIMES_D:
            time_idx = int(np.argmin(np.abs(totim_array - requested_time)))
            head_snapshot = head_file.get_data(totim=totim_array[time_idx])
            head_value = float(head_snapshot[0, obs_i, obs_j])
            numerical_drawdown = INITIAL_HEAD_M - head_value
            analytical_drawdown = _theis_drawdown(
                radius_m=discrete_radius,
                elapsed_d=float(totim_array[time_idx]),
            )
            numerical.append(numerical_drawdown)
            analytical.append(analytical_drawdown)

    return numerical, analytical


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.slow
@pytest.mark.solver_sanity
def test_theis_confined_pumping_matches_analytical_reference(tmp_path: Path) -> None:
    """Run the MF6 Theis model and compare drawdowns to ``W(u)`` at (r, t) probes."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    numerical, analytical = _build_and_run_theis_model(tmp_path)
    numerical_arr = np.asarray(numerical)
    analytical_arr = np.asarray(analytical)

    # Nash-Sutcliffe efficiency against the analytical trace.
    variance = float(np.sum((analytical_arr - analytical_arr.mean()) ** 2))
    residual = float(np.sum((numerical_arr - analytical_arr) ** 2))
    nse = 1.0 - residual / variance
    assert nse > 0.999, (
        f"Theis NSE too low: {nse:.6f} (residual={residual:.3e}, variance={variance:.3e})"
    )

    # Pointwise relative error below 1% at every (r, t) probe.
    relative_errors = np.abs(numerical_arr - analytical_arr) / np.maximum(
        np.abs(analytical_arr), 1e-12
    )
    max_rel = float(relative_errors.max())
    assert max_rel < 0.01, (
        f"Theis drawdown max relative error {max_rel:.4%} > 1%: "
        f"numerical={numerical_arr.tolist()}, analytical={analytical_arr.tolist()}"
    )
