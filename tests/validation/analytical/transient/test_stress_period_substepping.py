"""Time steps inside a stress period against a closed-form step response.

Compared with: the response to a head step at a Dirichlet boundary, `h(x, t) = dh erfc(x / (2 sqrt(D t)))` with `D = K b / S`; the fourth test compares one step per period with a run of 30 steps; the fifth takes the Fourier series of a head step on a linearized unconfined strip.

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
   order, and equal steps minimize its error. A growth ratio and its reciprocal
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

The first, second and fourth tests run on MODFLOW 6 and on MODFLOW-NWT, both
built straight in flopy: NWT is backward Euler with TSMULT as well, and the
rows 65, 66 and 68 hold for it unchanged. The third test is MODFLOW 6 only, as
MODFLOW-NWT has no adaptive time stepping. The fifth test runs the Boussinesq
solver, PETSc and default engine, through its own driver. That driver takes
``substeps_per_period`` equal backward-Euler steps per period, so statement 1
holds there; it has no growth ratio and no ATS, so statements 2 and 3 do not
apply. The PETSc run sets ``ts_vi_steps_per_period = 1`` so that the driver is
the only source of sub-steps.

Tolerances: ``tests/TOLERANCES.md`` rows 65-68, and the floor of
``_BOUSSINESQ_RATIO_FLOOR`` for the fifth test.
"""

from __future__ import annotations

import math
from pathlib import Path

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.solver_options import build_ats_perioddata
from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_above, assert_metric_below, record_metric

NOT_APPLICABLE = {
    "modflow6_irregular_tri": "The substep count is written to TDIS by a function that takes no mesh, and the closed form is a 1D column. Another mesh would add a spatial error and no information about the time stepping.",
    "modflow6_voronoi": "The substep count is written to TDIS by a function that takes no mesh, and the closed form is a 1D column. Another mesh would add a spatial error and no information about the time stepping.",
}

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


def _run_column_nwt(workspace: Path, *, nstp: int, tsmult: float = 1.0) -> np.ndarray:
    """The same column on MODFLOW-NWT: a held cell, confined storage, no ATS."""
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    workspace.mkdir(parents=True, exist_ok=True)
    mf = flopy.modflow.Modflow(
        "step",
        version="mfnwt",
        exe_name=str(ensure_solver_binary("mfnwt")),
        model_ws=str(workspace),
    )
    flopy.modflow.ModflowDis(
        mf,
        nlay=1,
        nrow=1,
        ncol=NCOL,
        delr=DX,
        delc=1.0,
        top=THICKNESS,
        botm=0.0,
        nper=1,
        perlen=PERIOD_SECONDS,
        nstp=nstp,
        tsmult=tsmult,
        steady=False,
        itmuni=1,
        lenuni=2,
    )
    ibound = np.ones((1, 1, NCOL), dtype=int)
    ibound[0, 0, 0] = -1
    strt = np.zeros((1, 1, NCOL))
    strt[0, 0, 0] = HEAD_STEP
    flopy.modflow.ModflowBas(mf, ibound=ibound, strt=strt)
    flopy.modflow.ModflowUpw(mf, laytyp=0, hk=K, vka=K, ss=SPECIFIC_STORAGE)
    flopy.modflow.ModflowNwt(mf, headtol=1.0e-9, fluxtol=1.0e-10, maxiterout=500)
    flopy.modflow.ModflowOc(mf, stress_period_data={(0, nstp - 1): ["save head"]})
    mf.write_input()
    success, buff = mf.run_model(silent=True)
    if not success:
        raise AssertionError(f"MODFLOW-NWT did not converge for nstp={nstp}: {buff}")

    head = flopy.utils.HeadFile(str(workspace / "step.hds"))
    try:
        return np.asarray(head.get_data(kstpkper=(nstp - 1, 0))).ravel()
    finally:
        head.close()


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
def test_the_column_stays_semi_infinite_over_the_period() -> None:
    """Guard the closed form: the pulse must not reach the far end."""
    assert _PENETRATION_M < NCOL * DX


_MODFLOW_SOLVERS = [
    pytest.param("modflow6", False, True, id="modflow6", marks=pytest.mark.mf6),
    pytest.param("modflow_nwt", True, False, id="modflow_nwt"),
]
_COLUMN_RUNNERS = {"modflow6": _run_column, "modflow_nwt": _run_column_nwt}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(("solver", "require_modflow", "require_modflow6"), _MODFLOW_SOLVERS)
def test_substeps_are_what_buys_transient_accuracy(
    solver: str, require_modflow: bool, require_modflow6: bool, tmp_path: Path
) -> None:
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )
    run = _COLUMN_RUNNERS[solver]

    single = _rmse_against_closed_form(run(tmp_path / "n1", nstp=1))
    ten = _rmse_against_closed_form(run(tmp_path / "n10", nstp=10))
    thirty = _rmse_against_closed_form(run(tmp_path / "n30", nstp=30))

    # The default of one step per period is an order of magnitude worse.
    assert_metric_above(
        "RMSE with 1 step over RMSE with 10 steps",
        single / ten,
        tol("stress_period_sub_stepping_mf6__rmse_ratio_between_nstp_1_and_nstp_10"),
    )
    assert thirty < ten


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(("solver", "require_modflow", "require_modflow6"), _MODFLOW_SOLVERS)
def test_a_geometric_partition_cannot_beat_equal_steps(
    solver: str, require_modflow: bool, require_modflow6: bool, tmp_path: Path
) -> None:
    """Why HydroModPy declares TSMULT = 1 and exposes no growth field."""
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )
    run = _COLUMN_RUNNERS[solver]

    equal = _rmse_against_closed_form(run(tmp_path / "r1", nstp=10))
    growing = _rmse_against_closed_form(run(tmp_path / "r2", nstp=10, tsmult=2.0))
    shrinking = _rmse_against_closed_form(run(tmp_path / "rhalf", nstp=10, tsmult=0.5))

    assert equal < growing
    assert equal < shrinking
    # A ratio and its reciprocal only reverse the order of the same step sizes,
    # and the end state does not see that order. The identity is exact in exact
    # arithmetic; what is left is the iterative closure, which COMPLEXITY SIMPLE
    # declares at DVCLOSE = 1e-3 m. Measured here: 2e-8 m on MODFLOW 6, and 2e-9 m on
    # MODFLOW-NWT at HEADTOL = 1e-9 m.
    assert_metric_below(
        "RMSE difference between TSMULT 2 and 1/2",
        abs(growing - shrinking),
        tol("stress_period_sub_stepping_mf6__rmse_difference_between_tsmult_r_and_1_r"),
        unit="m",
    )


@pytest.mark.mf6
@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
def test_adaptive_stepping_preserves_the_declared_substeps(tmp_path: Path) -> None:
    pytest.importorskip("scipy")
    assert_required_executables(
        require_modflow=False, require_modflow6=True, require_modpath=False, require_mt3dms=False
    )

    plain = _rmse_against_closed_form(_run_column(tmp_path / "plain", nstp=10))
    adaptive = _rmse_against_closed_form(_run_column(tmp_path / "ats", nstp=10, ats=True))

    # Nothing fails on this column, so ATS never cuts and must reproduce the
    # declared partition exactly. An unbounded dtmax would give the nstp=1 error.
    rel = tol("adaptive_time_stepping_mf6__rmse_relative_difference_ats_on_against_ats_off")
    record_metric(
        "Relative RMSE difference, ATS on against off", abs(adaptive - plain) / plain, rel, op="<="
    )
    assert adaptive == pytest.approx(plain, rel=rel)


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


def _run_seasonal_hillslope_nwt(workspace: Path, *, nstp: int) -> np.ndarray:
    """The same hillslope on MODFLOW-NWT: total outflow per month, drains plus river."""
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    workspace.mkdir(parents=True, exist_ok=True)
    perlen = [days * 86400.0 for days in _MONTH_DAYS]
    n_periods = len(perlen)

    mf = flopy.modflow.Modflow(
        "slope",
        version="mfnwt",
        exe_name=str(ensure_solver_binary("mfnwt")),
        model_ws=str(workspace),
    )
    flopy.modflow.ModflowDis(
        mf,
        nlay=1,
        nrow=1,
        ncol=_SLOPE_NCOL,
        delr=_SLOPE_DX,
        delc=1.0,
        top=_SLOPE_THICKNESS,
        botm=0.0,
        nper=n_periods,
        perlen=perlen,
        nstp=[nstp] * n_periods,
        tsmult=1.0,
        steady=[False] * n_periods,
        itmuni=1,
        lenuni=2,
    )
    ibound = np.ones((1, 1, _SLOPE_NCOL), dtype=int)
    ibound[0, 0, 0] = -1
    flopy.modflow.ModflowBas(mf, ibound=ibound, strt=_RIVER_HEAD)
    flopy.modflow.ModflowUpw(
        mf, laytyp=0, hk=_SLOPE_K, vka=_SLOPE_K, ss=_SLOPE_STORATIVITY / _SLOPE_THICKNESS, ipakcb=53
    )
    # Single precision NWT cannot close heads of 28 m below about 1e-6 m.
    flopy.modflow.ModflowNwt(mf, headtol=1.0e-6, fluxtol=1.0e-6, maxiterout=500)
    flopy.modflow.ModflowDrn(
        mf,
        stress_period_data={
            0: [[0, 0, col, _SLOPE_THICKNESS, _DRAIN_CONDUCTANCE] for col in range(1, _SLOPE_NCOL)]
        },
        ipakcb=53,
    )
    flopy.modflow.ModflowRch(
        mf,
        nrchop=3,
        rech={
            index: np.full((1, _SLOPE_NCOL), mm * 1.0e-3 / perlen[index])
            for index, mm in enumerate(_MONTH_RECHARGE_MM)
        },
        ipakcb=53,
    )
    flopy.modflow.ModflowOc(
        mf,
        stress_period_data={
            (index, nstp - 1): ["save head", "save budget"] for index in range(n_periods)
        },
    )
    mf.write_input()
    success, buff = mf.run_model(silent=True)
    if not success:
        raise AssertionError(f"MODFLOW-NWT did not converge for nstp={nstp}: {buff}")

    budget = flopy.utils.CellBudgetFile(str(workspace / "slope.cbc"))
    try:
        monthly = []
        for index in range(n_periods):
            total = 0.0
            for text in (b"DRAINS", b"CONSTANT HEAD"):
                records = budget.get_data(text=text, kstpkper=(nstp - 1, index))
                total += float(sum(record["q"].sum() for record in records))
            monthly.append(total)
    finally:
        budget.close()
    return np.asarray(monthly, dtype=float)


_HILLSLOPE_RUNNERS = {
    "modflow6": _run_seasonal_hillslope,
    "modflow_nwt": _run_seasonal_hillslope_nwt,
}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(("solver", "require_modflow", "require_modflow6"), _MODFLOW_SOLVERS)
def test_one_step_per_period_moves_the_discharge_a_calibration_scores(
    solver: str, require_modflow: bool, require_modflow6: bool, tmp_path: Path
) -> None:
    """The shipped default is a choice, not a neutral value."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )
    run = _HILLSLOPE_RUNNERS[solver]

    single = run(tmp_path / "nstp1", nstp=1)
    refined = run(tmp_path / "nstp30", nstp=30)

    drift = float(np.max(np.abs((single - refined) / refined)))

    assert_metric_above(
        "Largest monthly discharge drift of 1 step against 30",
        drift,
        tol("one_step_per_stress_period_mf6__monthly_discharge_drift_against_a_refined_run"),
    )


# The Boussinesq driver on a linearized unconfined strip: a west head step at
# t = 0 held for one 12 h period, against the Fourier series of
# validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d.
# 20 x 2 square cells of 5 m, so the dense default engine solves each step in
# a few hundredths of a second.
_BOUSSINESQ_NX = 20
_BOUSSINESQ_NY = 2
# Floor of RMSE(1 step) / RMSE(10 steps), proposed as a row of tests/TOLERANCES.md
# (Stress-period sub-stepping, Boussinesq). Backward Euler is first order, so ten
# steps would gain a factor ten on the time error alone. The strip has a spatial
# error and the closed form is linearized, which hold the ratio just below ten:
# measured 9.68 on both engines. The floor is half of it.
_BOUSSINESQ_RATIO_FLOOR = tol(
    "stress_period_sub_stepping_boussinesq__rmse_ratio_between_nstp_1_and_nstp_10"
)


def _boussinesq_step_rmse(workspace: Path, *, solver: str, substeps: int) -> float:
    """RMSE of the end-of-period heads against the head-step closed form."""
    from types import SimpleNamespace

    from hydromodpy.model.flow import Flow
    from hydromodpy.solver.base.plan import ProcessRun, RunContext, SimulationPlan
    from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
    from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.reference import (
        expected_linearized_unconfined_boundary_step_profiles,
    )
    from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.runtime_boussinesq import (
        CASE_DIR,
    )
    from validation_cases.analytical.transient.runtime_boussinesq_1d import (
        build_flow_config,
        write_uniform_strip_bundle,
    )
    from validation_cases.shared import load_case_metadata
    from validation_cases.shared.boussinesq_analytical_runtime import (
        boussinesq_run_state,
        boussinesq_variant_config_name,
        boussinesq_variant_flow_section,
        boussinesq_variant_options,
    )
    from validation_cases.shared.boussinesq_uniform_strip import (
        aggregate_triangle_history_to_structured_fields,
    )
    from validation_cases.shared.strip_geometry import split_triangle_strip_geometry

    metadata = load_case_metadata(CASE_DIR)
    reference = dict(metadata["reference"])
    period_seconds = float(metadata["time"]["dt_seconds"])
    base_head = float(reference["base_head_m"])
    thickness = float(reference["reference_saturated_thickness_m"])
    length = float(reference["xmax"]) - float(reference["xmin"])

    workspace.mkdir(parents=True, exist_ok=True)
    bundle = write_uniform_strip_bundle(
        workspace / "mesh_bundle",
        nx=_BOUSSINESQ_NX,
        ny=_BOUSSINESQ_NY,
        length_x_m=length,
        width_y_m=10.0,
        z_top_m=base_head + thickness,
        z_bottom_m=base_head - thickness,
        hydraulic_conductivity_m_s=float(reference["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=float(reference["specific_yield"]),
    )
    flow_section: dict[str, object] = {
        "flow_regime": "transient",
        "ic": {"kind": "custom", "value": base_head},
        "bc": {
            "west_side": {"value": float(reference["west_head_m"])},
            "east_side": {"value": base_head},
        },
    }
    settings: dict[str, object] = {}
    if solver == "boussinesq":
        # The driver is the only source of sub-steps: one TS step per solve.
        settings = {
            "backend": "petsc",
            "surface_interaction_model": "ts_vi_obstacle",
            "ts_vi_steps_per_period": 1,
            "ts_vi_adapt": False,
            "ts_vi_type": "beuler",
            "ts_vi_snes_type": "vinewtonrsls",
        }
    simulations = workspace / "results_simulations"
    simulations.mkdir(exist_ok=True)
    state = boussinesq_run_state(
        flow=Flow(
            build_flow_config(
                boussinesq_variant_flow_section(flow_section, flow_regime="transient"),
                case_dir=CASE_DIR,
                config_name=boussinesq_variant_config_name(solver),
            )
        ),
        bundle_dir=bundle,
        simulations_folder=simulations,
        time_grid=SimpleNamespace(
            period_lengths_seconds=(period_seconds,),
            nstp_per_period=int(substeps),
            window=None,
        ),
        options=boussinesq_variant_options(
            flow_regime="transient",
            solver=solver,
            case_dir=CASE_DIR,
            config_name=boussinesq_variant_config_name(solver),
            written=settings,
        ),
    )
    run = ProcessRun(
        id="flow_validation::boussinesq",
        process_id="flow_validation",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name="Boussinesq sub-steps", description="Head step, N steps", runs=(run,)
        ),
        run=run,
        state=state,
    )
    model = BoussinesqFlowAdapter().execute(ctx).primary_model
    fields = aggregate_triangle_history_to_structured_fields(
        model, nx=_BOUSSINESQ_NX, ny=_BOUSSINESQ_NY, export_initial_state=False
    )
    simulated = np.asarray(fields["watertable_elevation"][0], dtype=float).mean(axis=0)

    strip = split_triangle_strip_geometry(
        xmin=float(reference["xmin"]), xmax=float(reference["xmax"]), ncol=_BOUSSINESQ_NX
    )
    expected = strip.profile(
        lambda points: expected_linearized_unconfined_boundary_step_profiles(
            x=points,
            west_x=strip.west_x,
            east_x=strip.east_x,
            eval_times_seconds=np.array([period_seconds]),
            period_start_seconds=np.array([0.0]),
            base_head_m=base_head,
            west_head_m=float(reference["west_head_m"]),
            hydraulic_conductivity_m_per_s=float(reference["hydraulic_conductivity_m_per_s"]),
            reference_saturated_thickness_m=thickness,
            specific_yield=float(reference["specific_yield"]),
            n_terms=int(reference["n_terms"]),
        ),
        within=(strip.west_x, strip.east_x),
    )[0]
    return float(np.sqrt(np.mean((simulated - expected) ** 2)))


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("boussinesq", id="boussinesq", marks=pytest.mark.petsc),
        pytest.param("boussinesq_local", id="boussinesq_local"),
    ],
)
def test_the_boussinesq_driver_takes_the_requested_substeps(solver: str, tmp_path: Path) -> None:
    """``substeps_per_period`` buys transient accuracy on both Boussinesq engines."""
    pytest.importorskip("scipy")
    if solver == "boussinesq":
        pytest.importorskip("petsc4py")

    single = _boussinesq_step_rmse(tmp_path / "n1", solver=solver, substeps=1)
    ten = _boussinesq_step_rmse(tmp_path / "n10", solver=solver, substeps=10)
    thirty = _boussinesq_step_rmse(tmp_path / "n30", solver=solver, substeps=30)

    assert_metric_above(
        "RMSE with 1 step over RMSE with 10 steps",
        single / ten,
        _BOUSSINESQ_RATIO_FLOOR,
    )
    assert thirty < ten
