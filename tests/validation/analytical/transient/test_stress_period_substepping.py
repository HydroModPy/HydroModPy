"""What actually governs transient accuracy inside a stress period.

A stress period holds a constant forcing, and HydroModPy stores only its end
state. Against the closed form of a step at a Dirichlet boundary,
``h(x, t) = dh * erfc(x / (2 sqrt(D t)))`` with ``D = K b / S``, this case pins
three statements that are easy to get backwards:

1. ``simulation.time.substeps_per_period`` is the knob. The default of one
   backward-Euler step over the whole period carries an order of magnitude more
   error than ten.
2. A geometric partition (MODFLOW TSMULT) cannot help. Within a period the
   forcing is constant, so the backward-Euler end state is a commuting product
   over the steps: it depends on the multiset of step sizes and not on their
   order, and equal steps minimise its error. A growth ratio and its reciprocal
   give the same error, both worse than equal steps. This is why HydroModPy
   declares TSMULT = 1 and exposes no growth field.
3. Adaptive time stepping must not undo the request. MF6 ignores the TDIS NSTP
   of a period ATS covers, so the ATS record has to carry the declared step as
   both its starting and its maximum value.

A fourth test leaves the closed form for HydroModPy's own configuration, a
seasonal recharge on a hillslope drained by surface DRN cells and a river. There
the default of one step per period is not a small bias: it moves the monthly
discharge, the quantity a calibration scores against, by tens of percent. The
default is left at 1 because the right count is a property of the model
(``tau = L**2 S / (K b)`` against the period length) and the cost is linear in
it, but a run that leaves it there is making a choice, not accepting a neutral
value.

Tolerances: ``tests/TOLERANCES.md`` rows 65-68.
"""

from __future__ import annotations

import math
from pathlib import Path

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import build_ats_perioddata
from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables

# A confined column: one row, one layer, uniform cells. Round SI numbers rather
# than a field site, so the closed form holds exactly.
NCOL = 200
DX = 5.0  # m
K = 1.0e-6  # m/s, a plausible fractured-bedrock value
THICKNESS = 10.0  # m
SPECIFIC_STORAGE = 1.0e-4  # 1/m
STORATIVITY = SPECIFIC_STORAGE * THICKNESS
DIFFUSIVITY = K * THICKNESS / STORATIVITY  # m2/s
PERIOD_SECONDS = 31.0 * 86400.0
HEAD_STEP = 1.0  # m, imposed at x = 0 at t = 0

# The column must stay semi-infinite over the period, or the closed form picks
# up a reflection the model does not have.
_PENETRATION_M = 4.0 * math.sqrt(DIFFUSIVITY * PERIOD_SECONDS)


def _exact_head(x: np.ndarray, t: float) -> np.ndarray:
    """Carslaw and Jaeger step response of a semi-infinite column."""
    from scipy.special import erfc

    return HEAD_STEP * erfc(x / (2.0 * math.sqrt(DIFFUSIVITY * t)))


def _run_column(
    workspace: Path, *, nstp: int, tsmult: float = 1.0, ats: bool = False
) -> np.ndarray:
    """Head profile at the end of the period, for one time-step declaration."""
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    workspace.mkdir(parents=True, exist_ok=True)
    sim = flopy.mf6.MFSimulation(
        sim_name="step",
        sim_ws=str(workspace),
        exe_name=str(ensure_solver_binary("mf6")),
        version="mf6",
    )
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(PERIOD_SECONDS, nstp, tsmult)],
        time_units="seconds",
    )
    if ats:
        records = build_ats_perioddata(
            perlen=np.array([PERIOD_SECONDS]),
            nstp=np.array([nstp]),
            steady=np.array([False]),
            dtmin_s=1.0,
        )
        flopy.mf6.ModflowUtlats(tdis, maxats=len(records), perioddata=records)
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE", outer_maximum=50, inner_maximum=100)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="step")
    flopy.mf6.ModflowGwfdis(
        gwf, nlay=1, nrow=1, ncol=NCOL, delr=DX, delc=1.0, top=THICKNESS, botm=0.0
    )
    flopy.mf6.ModflowGwfic(gwf, strt=0.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=K)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=SPECIFIC_STORAGE, transient={0: True})
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[((0, 0, 0), HEAD_STEP)])
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="step.hds", saverecord=[("HEAD", "LAST")])
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise AssertionError(f"MODFLOW 6 did not converge for nstp={nstp}: {buff}")

    head = flopy.utils.HeadFile(str(workspace / "step.hds"))
    try:
        return np.asarray(head.get_data(totim=PERIOD_SECONDS)).ravel()
    finally:
        head.close()


def _rmse_against_closed_form(simulated: np.ndarray) -> float:
    # The boundary cell holds the imposed head, so it says nothing about the
    # time integration and is left out.
    x = ((np.arange(NCOL, dtype=float) + 0.5) * DX)[1:]
    return float(np.sqrt(np.mean((simulated[1:] - _exact_head(x, PERIOD_SECONDS)) ** 2)))


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
def test_the_column_stays_semi_infinite_over_the_period() -> None:
    """Guard the closed form: the pulse must not reach the far end."""
    assert _PENETRATION_M < NCOL * DX


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_substeps_are_what_buys_transient_accuracy(tmp_path: Path) -> None:
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=False, require_modflow6=True, require_modpath=False, require_mt3dms=False
    )

    single = _rmse_against_closed_form(_run_column(tmp_path / "n1", nstp=1))
    ten = _rmse_against_closed_form(_run_column(tmp_path / "n10", nstp=10))
    thirty = _rmse_against_closed_form(_run_column(tmp_path / "n30", nstp=30))

    # The default of one step per period is an order of magnitude worse.
    assert (
        single > tol("stress_period_sub_stepping_mf6__rmse_ratio_between_nstp_1_and_nstp_10") * ten
    )
    assert thirty < ten


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_a_geometric_partition_cannot_beat_equal_steps(tmp_path: Path) -> None:
    """Why HydroModPy declares TSMULT = 1 and exposes no growth field."""
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=False, require_modflow6=True, require_modpath=False, require_mt3dms=False
    )

    equal = _rmse_against_closed_form(_run_column(tmp_path / "r1", nstp=10))
    growing = _rmse_against_closed_form(_run_column(tmp_path / "r2", nstp=10, tsmult=2.0))
    shrinking = _rmse_against_closed_form(_run_column(tmp_path / "rhalf", nstp=10, tsmult=0.5))

    assert equal < growing
    assert equal < shrinking
    # A ratio and its reciprocal only reverse the order of the same step sizes,
    # and the end state does not see that order. The identity is exact in exact
    # arithmetic; what is left is the iterative closure, which COMPLEXITY SIMPLE
    # declares at DVCLOSE = 1e-3 m. Measured here: 2e-8 m.
    assert abs(growing - shrinking) < tol(
        "stress_period_sub_stepping_mf6__rmse_difference_between_tsmult_r_and_1_r"
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_adaptive_stepping_preserves_the_declared_substeps(tmp_path: Path) -> None:
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=False, require_modflow6=True, require_modpath=False, require_mt3dms=False
    )

    plain = _rmse_against_closed_form(_run_column(tmp_path / "plain", nstp=10))
    adaptive = _rmse_against_closed_form(_run_column(tmp_path / "ats", nstp=10, ats=True))

    # Nothing fails on this column, so ATS never cuts and must reproduce the
    # declared partition exactly. An unbounded dtmax would give the nstp=1 error.
    assert adaptive == pytest.approx(
        plain,
        rel=tol("adaptive_time_stepping_mf6__rmse_relative_difference_ats_on_against_ats_off"),
    )


# A hillslope in HydroModPy's own configuration: seasonal recharge, a river at
# the toe, and a DRN on every other cell so the water table seeps once it reaches
# the land surface. Confined storage with Ss = S / b keeps the storativity at the
# bedrock value while the closed-form-free comparison is against a refined run.
_SLOPE_NCOL = 40
_SLOPE_DX = 5.0  # m
_SLOPE_THICKNESS = 30.0  # m
_SLOPE_STORATIVITY = 0.01
_RIVER_HEAD = 28.0  # m
_DRAIN_CONDUCTANCE = 1.0e-3 * _SLOPE_DX  # m2/s per cell
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MONTH_RECHARGE_MM = (90, 75, 60, 45, 25, 10, 5, 8, 30, 60, 85, 95)
# K = 3e-6 m/s puts tau at about 1.7 months, the band where one step per period
# is furthest from the refined answer.
_SLOPE_K = 3.0e-6


def _run_seasonal_hillslope(workspace: Path, *, nstp: int) -> np.ndarray:
    """Total outflow per month, river plus seepage, for one sub-step count."""
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    workspace.mkdir(parents=True, exist_ok=True)
    perlen = [days * 86400.0 for days in _MONTH_DAYS]
    recharge = {index: mm * 1.0e-3 / perlen[index] for index, mm in enumerate(_MONTH_RECHARGE_MM)}

    sim = flopy.mf6.MFSimulation(
        sim_name="slope",
        sim_ws=str(workspace),
        exe_name=str(ensure_solver_binary("mf6")),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(
        sim,
        nper=len(perlen),
        perioddata=[(length, nstp, 1.0) for length in perlen],
        time_units="seconds",
    )
    flopy.mf6.ModflowIms(sim, complexity="MODERATE", outer_maximum=200, inner_maximum=300)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="slope", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1,
        nrow=1,
        ncol=_SLOPE_NCOL,
        delr=_SLOPE_DX,
        delc=1.0,
        top=_SLOPE_THICKNESS,
        botm=0.0,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=_RIVER_HEAD)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=_SLOPE_K)
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=_SLOPE_STORATIVITY / _SLOPE_THICKNESS,
        transient=dict.fromkeys(range(len(perlen)), True),
    )
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[((0, 0, 0), _RIVER_HEAD)])
    flopy.mf6.ModflowGwfdrn(
        gwf,
        stress_period_data=[
            ((0, 0, col), _SLOPE_THICKNESS, _DRAIN_CONDUCTANCE) for col in range(1, _SLOPE_NCOL)
        ],
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge)
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="slope.hds",
        budget_filerecord="slope.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise AssertionError(f"MODFLOW 6 did not converge for nstp={nstp}: {buff}")

    budget = flopy.utils.CellBudgetFile(str(workspace / "slope.cbc"))
    try:
        monthly = []
        for kstpkper in budget.get_kstpkper():
            total = 0.0
            for text in (b"DRN", b"CHD"):
                records = budget.get_data(text=text, kstpkper=kstpkper)
                total += float(sum(record["q"].sum() for record in records))
            monthly.append(total)
    finally:
        budget.close()
    return np.asarray(monthly, dtype=float)


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.slow
def test_one_step_per_period_moves_the_discharge_a_calibration_scores(tmp_path: Path) -> None:
    """The shipped default is a choice, not a neutral value."""
    assert_required_executables(
        require_modflow=False, require_modflow6=True, require_modpath=False, require_mt3dms=False
    )

    single = _run_seasonal_hillslope(tmp_path / "nstp1", nstp=1)
    refined = _run_seasonal_hillslope(tmp_path / "nstp30", nstp=30)

    drift = float(np.max(np.abs((single - refined) / refined)))

    assert drift > tol(
        "one_step_per_stress_period_mf6__monthly_discharge_drift_against_a_refined_run"
    )
