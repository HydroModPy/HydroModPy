"""Hantush-Jacob (1955) leaky-aquifer benchmark against MODFLOW 6.

A fully penetrating well pumps at constant rate ``Q`` in a confined aquifer
overlain by a leaky aquitard of thickness ``b'`` and vertical conductivity
``K'``. A source bed of constant head sits above the aquitard. Under these
assumptions the analytical drawdown is the Hantush solution::

    s(r, t) = Q / (4 pi T) * W(u, r / B)

with ``u = r^2 S / (4 T t)``, ``B = sqrt(T b' / K')`` the leakage factor
and the Hantush well function

    W(u, beta) = int_u^inf (1/y) exp(-y - beta^2 / (4 y)) dy.

The numerical reference is a three-layer MF6 IMS model:

  * layer 0: source bed - all cells are CHD at the initial head,
  * layer 1: aquitard - thickness ``b'`` and K = ``K'``, no storage,
  * layer 2: main pumped aquifer - thickness ``b``, K such that
    ``T = K b``, specific storage such that ``S = S_s b``.

A telescoping grid concentrates resolution near the well; the outer
Dirichlet ring sits well beyond the radius of influence
``~sqrt(4 T t / S)``. Drawdown is compared at radii 10/50/100 m and
times 1/3/10 d.

Tolerance rationale - ``tests/TOLERANCES.md`` row 6: NSE > 0.99 and
maximum pointwise relative error below 2 %.

Scope - ``solver_sanity``:
   The three-layer sandwich (source / aquitard / pumped aquifer) and the
   telescoping grid are built directly on the flopy SDK because the
   hydromodpy launcher TOML does not expose this geometry. The test
   therefore validates **MODFLOW 6 against the Hantush analytical
   solution**, not the hydromodpy pipeline.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import quad

from tests.regression.golden_utils import (
    assert_required_executables,
    resolve_bundled_executable,
)

PUMPING_RATE_M3_PER_DAY = 100.0
TRANSMISSIVITY_M2_PER_DAY = 100.0
STORATIVITY = 1.0e-4
AQUIFER_THICKNESS_M = 10.0
HYDRAULIC_CONDUCTIVITY_M_PER_DAY = TRANSMISSIVITY_M2_PER_DAY / AQUIFER_THICKNESS_M
SPECIFIC_STORAGE = STORATIVITY / AQUIFER_THICKNESS_M

AQUITARD_THICKNESS_M = 1.0
AQUITARD_K_M_PER_DAY = 0.01
LEAKAGE_FACTOR_B_M = math.sqrt(
    TRANSMISSIVITY_M2_PER_DAY * AQUITARD_THICKNESS_M / AQUITARD_K_M_PER_DAY
)

# The source layer is a numerical convenience holding the constant-head
# boundary above the aquitard. It must add negligible resistance to the
# vertical-flow pathway so the effective leakance from source to pumped
# aquifer reduces to K'/b'. A thin, highly conductive layer does exactly
# that: 0.5 * b_source / K_source becomes orders of magnitude smaller
# than 0.5 * b' / K'.
SOURCE_THICKNESS_M = 0.001
SOURCE_K_M_PER_DAY = 1.0e6

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
    side: list[float] = [MIN_CELL_SIZE_M] * N_UNIFORM_SIDE
    current = MIN_CELL_SIZE_M
    for _ in range(N_GROWTH_SIDE):
        current *= GROWTH_RATIO
        side.append(current)
    return np.asarray(list(reversed(side)) + [MIN_CELL_SIZE_M] + side, dtype=float)


def _cell_centers(delta: np.ndarray) -> np.ndarray:
    edges = np.concatenate(([0.0], np.cumsum(delta)))
    return 0.5 * (edges[:-1] + edges[1:])


def _hantush_well_function(u: float, beta: float) -> float:
    """Return ``W(u, beta) = int_u^inf (1/y) exp(-y - beta^2/(4 y)) dy``.

    Evaluated with scipy's adaptive quadrature. The integrand is smooth
    and strictly positive on ``[u, infty)`` for ``u > 0, beta > 0``, so
    the default tolerances are more than sufficient for the 2 %
    benchmark tolerance.
    """
    if u <= 0.0:
        raise ValueError("u must be strictly positive")

    def integrand(y: float) -> float:
        return math.exp(-y - (beta * beta) / (4.0 * y)) / y

    value, _abserr = quad(integrand, u, np.inf, limit=200)
    return float(value)


def _hantush_drawdown(radius_m: float, elapsed_d: float) -> float:
    u = (radius_m * radius_m * STORATIVITY) / (4.0 * TRANSMISSIVITY_M2_PER_DAY * elapsed_d)
    beta = radius_m / LEAKAGE_FACTOR_B_M
    w = _hantush_well_function(u, beta)
    return float(PUMPING_RATE_M3_PER_DAY / (4.0 * math.pi * TRANSMISSIVITY_M2_PER_DAY) * w)


def _build_and_run_hantush_model(workspace: Path) -> tuple[list[float], list[float]]:
    import flopy

    mf6_exe = resolve_bundled_executable("mf6")

    delr = _build_telescoping_axis()
    delc = delr.copy()
    n_cells = int(delr.size)
    centre_index = n_cells // 2
    x_centers = _cell_centers(delr)
    y_centers = _cell_centers(delc)
    well_x = x_centers[centre_index]
    well_y = y_centers[centre_index]

    sim = flopy.mf6.MFSimulation(
        sim_name="hantush",
        sim_ws=str(workspace),
        exe_name=str(mf6_exe),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=N_STRESS_PERIODS,
        perioddata=[(PERIOD_LENGTH_D, NSTP_PER_PERIOD, 1.2)] * N_STRESS_PERIODS,
    )
    flopy.mf6.ModflowIms(
        sim,
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-6,
        inner_dvclose=1e-8,
        linear_acceleration="CG",
    )

    gwf = flopy.mf6.ModflowGwf(sim, modelname="hantush", save_flows=True)

    # Three layers stacked downward: source / aquitard / main aquifer.
    top = INITIAL_HEAD_M + SOURCE_THICKNESS_M
    botm = [
        INITIAL_HEAD_M,  # bottom of source
        INITIAL_HEAD_M - AQUITARD_THICKNESS_M,  # bottom of aquitard
        INITIAL_HEAD_M - AQUITARD_THICKNESS_M - AQUIFER_THICKNESS_M,
    ]
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=3,
        nrow=n_cells,
        ncol=n_cells,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
        length_units="METERS",
    )

    flopy.mf6.ModflowGwfic(gwf, strt=INITIAL_HEAD_M)

    # icelltype=0 everywhere (confined). K horizontal / vertical by layer.
    k_layers = [
        SOURCE_K_M_PER_DAY,
        AQUITARD_K_M_PER_DAY,
        HYDRAULIC_CONDUCTIVITY_M_PER_DAY,
    ]
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=0,
        k=k_layers,
        k33=k_layers,
    )

    # Storage: only the pumped aquifer has storage; aquitard and source
    # layers are storageless to match the Hantush assumption.
    ss_layers = [0.0, 0.0, SPECIFIC_STORAGE]
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=ss_layers,
        sy=0.0,
        steady_state={0: False},
        transient={0: True},
    )

    well_record = [((2, centre_index, centre_index), -PUMPING_RATE_M3_PER_DAY)]
    wel_spd = {period: well_record for period in range(N_STRESS_PERIODS)}
    flopy.mf6.ModflowGwfwel(gwf, stress_period_data=wel_spd)

    # CHD on all source-layer cells (layer 0) and on the outer rim of the
    # pumped aquifer (layer 2) to close the radial domain.
    chd_cells: list[tuple[tuple[int, int, int], float]] = []
    for row in range(n_cells):
        for col in range(n_cells):
            chd_cells.append(((0, row, col), INITIAL_HEAD_M))
    for col in range(n_cells):
        chd_cells.append(((2, 0, col), INITIAL_HEAD_M))
        chd_cells.append(((2, n_cells - 1, col), INITIAL_HEAD_M))
    for row in range(1, n_cells - 1):
        chd_cells.append(((2, row, 0), INITIAL_HEAD_M))
        chd_cells.append(((2, row, n_cells - 1), INITIAL_HEAD_M))
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd_cells})

    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{gwf.name}.hds",
        saverecord=[("HEAD", "ALL")],
    )

    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 Hantush simulation did not converge"

    head_file = flopy.utils.HeadFile(workspace / f"{gwf.name}.hds")
    totim_array = np.asarray(head_file.get_times())

    numerical: list[float] = []
    analytical: list[float] = []
    for radius in OBSERVATION_RADII_M:
        target_x = well_x + radius
        obs_j = int(np.argmin(np.abs(x_centers - target_x)))
        obs_i = centre_index
        discrete_radius = math.sqrt(
            (x_centers[obs_j] - well_x) ** 2 + (y_centers[obs_i] - well_y) ** 2
        )
        for requested_time in OBSERVATION_TIMES_D:
            time_idx = int(np.argmin(np.abs(totim_array - requested_time)))
            head_snapshot = head_file.get_data(totim=totim_array[time_idx])
            head_value = float(head_snapshot[2, obs_i, obs_j])  # pumped layer
            numerical_drawdown = INITIAL_HEAD_M - head_value
            analytical_drawdown = _hantush_drawdown(
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
def test_hantush_leaky_aquifer_matches_analytical_reference(tmp_path: Path) -> None:
    """Run the MF6 Hantush model and compare drawdowns to ``W(u, r/B)``."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )

    numerical, analytical = _build_and_run_hantush_model(tmp_path)
    numerical_arr = np.asarray(numerical)
    analytical_arr = np.asarray(analytical)

    variance = float(np.sum((analytical_arr - analytical_arr.mean()) ** 2))
    residual = float(np.sum((numerical_arr - analytical_arr) ** 2))
    nse = 1.0 - residual / variance
    assert nse > 0.99, (
        f"Hantush NSE too low: {nse:.6f} (residual={residual:.3e}, variance={variance:.3e})"
    )

    relative_errors = np.abs(numerical_arr - analytical_arr) / np.maximum(
        np.abs(analytical_arr), 1e-12
    )
    max_rel = float(relative_errors.max())
    assert max_rel < 0.02, (
        f"Hantush drawdown max relative error {max_rel:.4%} > 2%: "
        f"numerical={numerical_arr.tolist()}, analytical={analytical_arr.tolist()}"
    )
