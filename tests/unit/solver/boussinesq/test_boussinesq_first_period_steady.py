"""The first stress period of a transient Boussinesq run, and the fluxes of a period.

``flow.first_period_steady`` (true by default) makes MODFLOW 6 and NWT solve
period 0 of a transient run at steady state. Boussinesq ignored the key: the
same file started from the initial condition on Boussinesq and from a steady
state on MODFLOW. Boussinesq now solves period 0 with the stationary solve of
its engine, then integrates the next periods in time from that state.

A period cut into time steps exports the head of its last step and the mean
of the step fluxes, weighted by their length: a stamp closes its period. The
PETSc closures that cut a period into internal steps (VI substeps, TS steps)
export the mean of those steps as well.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.model import ModelTime
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.drivers import steady as steady_driver
from hydromodpy.solver.boussinesq.drivers import transient as transient_driver
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.boussinesq.runtime_contract import TransientStepInputs
from hydromodpy.solver.boussinesq.state import BoussinesqState
from tests._helpers.model_factory import make_model

from ._row_runs import DAY_S, N_CELLS, OUTLET_M, fixed_forcing, row_mesh

START_M = 30.0
# Recharge of periods 0, 1 and 2, in m/s.
RATES_M_S = (2.0e-3 / DAY_S, 10.0e-3 / DAY_S, 0.0)


def _solver(
    tmp_path: Path,
    *,
    name: str,
    flow_regime: str,
    first_period_steady: bool,
    head_m: np.ndarray,
    period_lengths_seconds: tuple[float, ...] = (),
    nstp_per_period: int = 1,
    runtime_backend: str = "local",
    surface_interaction_model: str = "auto",
    **runtime_options: object,
) -> Boussinesq:
    """Return a solver on the row mesh, its state set to ``head_m``."""
    mesh = row_mesh()
    model = make_model(
        time=ModelTime(
            grid=SimpleNamespace(
                period_lengths_seconds=period_lengths_seconds, nstp_per_period=nstp_per_period
            ),
            regime=flow_regime,
            first_period_steady=first_period_steady,
        )
    )
    runtime = BoussinesqOptions(
        backend=runtime_backend,
        surface_interaction_model=surface_interaction_model,
        tol_residual_inf=1.0e-12,
        **runtime_options,
    )
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        model=model,
        runtime=runtime,
        model_folder=tmp_path,
        model_name=name,
    )
    head = np.asarray(head_m, dtype=float)
    solver.state = BoussinesqState.initial(head_m=head, saturated_thickness_m=head.copy())
    return solver


def _start_heads() -> np.ndarray:
    head = np.full(N_CELLS, START_M)
    head[0] = OUTLET_M
    return head


def _steady_heads(tmp_path: Path, monkeypatch, *, rate_m_s: float, **kwargs) -> np.ndarray:
    """Return the stationary solve of one forcing, from the start heads as a guess."""
    monkeypatch.setattr(
        steady_driver, "resolve_runtime_forcing_by_period", fixed_forcing((rate_m_s,))
    )
    solver = _solver(
        tmp_path,
        name="steady",
        flow_regime="steady",
        first_period_steady=True,
        head_m=_start_heads(),
        **kwargs,
    )
    assert steady_driver.run_steady_runtime(solver)
    return np.asarray(solver.state.head_m, dtype=float)


@pytest.mark.parametrize("runtime_backend", ["local", "scipy_sparse"])
def test_a_steady_first_period_is_the_stationary_solve_of_its_forcing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_backend: str
) -> None:
    steady = _steady_heads(
        tmp_path, monkeypatch, rate_m_s=RATES_M_S[0], runtime_backend=runtime_backend
    )
    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing(RATES_M_S)
    )
    run = _solver(
        tmp_path,
        name="first_steady",
        flow_regime="transient",
        first_period_steady=True,
        head_m=_start_heads(),
        period_lengths_seconds=(DAY_S,) * 3,
        runtime_backend=runtime_backend,
    )

    assert transient_driver.run_transient_runtime(run)

    history = np.asarray(run.state.head_history_m, dtype=float)
    assert run.runtime_summary["first_period_steady"] is True
    np.testing.assert_allclose(history[1], steady, rtol=0.0, atol=1.0e-10)
    # A steady period holds its state from its start: no storage change on it.
    np.testing.assert_array_equal(history[0], history[1])
    # The start heads were the guess only: they sit 10 m above the steady state.
    assert np.max(np.abs(history[1] - _start_heads())) > 9.0


def test_the_periods_after_a_steady_first_period_run_in_time_from_its_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steady = _steady_heads(tmp_path, monkeypatch, rate_m_s=RATES_M_S[0])
    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing(RATES_M_S)
    )
    run = _solver(
        tmp_path,
        name="first_steady",
        flow_regime="transient",
        first_period_steady=True,
        head_m=_start_heads(),
        period_lengths_seconds=(DAY_S,) * 3,
    )
    assert transient_driver.run_transient_runtime(run)

    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing(RATES_M_S[1:])
    )
    from_steady = _solver(
        tmp_path,
        name="from_steady",
        flow_regime="transient",
        first_period_steady=False,
        head_m=steady,
        period_lengths_seconds=(DAY_S,) * 2,
    )
    assert transient_driver.run_transient_runtime(from_steady)

    np.testing.assert_allclose(
        run.state.head_history_m[2:], from_steady.state.head_history_m[1:], rtol=0.0, atol=1.0e-9
    )
    # Period 1 takes five times the recharge of period 0: the run did move in time.
    assert np.max(run.state.head_history_m[2] - run.state.head_history_m[1]) > 1.0e-3


def test_without_the_key_the_first_period_runs_in_time_from_the_initial_condition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steady = _steady_heads(tmp_path, monkeypatch, rate_m_s=RATES_M_S[0])
    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing(RATES_M_S)
    )
    run = _solver(
        tmp_path,
        name="first_transient",
        flow_regime="transient",
        first_period_steady=False,
        head_m=_start_heads(),
        period_lengths_seconds=(DAY_S,) * 3,
    )
    assert transient_driver.run_transient_runtime(run)

    forcing = fixed_forcing(RATES_M_S)(run, nper=1)
    one_step = run._resolve_solver_contract().runtime_backend.solve_transient_step(
        TransientStepInputs(
            mesh=run.mesh,
            head_prev_m=_start_heads(),
            dt_seconds=DAY_S,
            options=run._runtime_options(),
            head_initial_guess_m=_start_heads(),
            recharge_rate_m_s=forcing.recharge_series_m_s[0],
            well_flux_m3_s=forcing.well_flux_by_period_m3_s[0],
            prescribed_head_m_by_cell=forcing.prescribed_heads_by_period[0],
            drainage_conductance_m2_s=0.0,
        )
    )
    history = np.asarray(run.state.head_history_m, dtype=float)
    assert run.runtime_summary["first_period_steady"] is False
    np.testing.assert_array_equal(history[0], _start_heads())
    np.testing.assert_allclose(history[1], one_step.head_m, rtol=0.0, atol=1.0e-12)
    # One day drains a few meters of the 10 m above the steady state, not all of them.
    assert np.max(history[1] - steady) > 1.0


def _time(regime: str, *, first_period_steady: bool) -> ModelTime:
    return ModelTime(grid=None, regime=regime, first_period_steady=first_period_steady)


@pytest.mark.petsc
def test_ts_vi_obstacle_solves_its_steady_first_period_with_the_vi_obstacle_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steady = _steady_heads(
        tmp_path,
        monkeypatch,
        rate_m_s=RATES_M_S[0],
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
    )
    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing(RATES_M_S)
    )
    run = _solver(
        tmp_path,
        name="ts_vi_first_steady",
        flow_regime="transient",
        first_period_steady=True,
        head_m=_start_heads(),
        period_lengths_seconds=(DAY_S,) * 3,
        runtime_backend="petsc",
        surface_interaction_model="ts_vi_obstacle",
    )
    contract = run._resolve_solver_contract()

    assert transient_driver.stationary_backend(contract).method.id == "head_only_vi_obstacle"
    assert transient_driver.run_transient_runtime(run)
    np.testing.assert_allclose(run.state.head_history_m[1], steady, rtol=0.0, atol=1.0e-10)


def _relaxation(
    tmp_path: Path, monkeypatch, *, n_periods: int, n_steps: int, **solver_options: object
) -> Boussinesq:
    """Drain the start heads through the held cell over 4 days, without recharge."""
    monkeypatch.setattr(
        transient_driver, "resolve_runtime_forcing_by_period", fixed_forcing((0.0,) * n_periods)
    )
    solver = _solver(
        tmp_path,
        name=f"relax_{n_periods}_{n_steps}",
        flow_regime="transient",
        first_period_steady=False,
        head_m=_start_heads(),
        period_lengths_seconds=(4.0 * DAY_S / n_periods,) * n_periods,
        nstp_per_period=n_steps,
        **solver_options,
    )
    assert transient_driver.run_transient_runtime(solver)
    return solver


_FLUX_HISTORIES = (
    "recharge_rate_history_m_s",
    "well_flux_history_m3_s",
    "saturation_excess_history_m_s",
    "dry_deficit_history_m_s",
    "internal_edge_flux_history_m3_s",
    "boundary_edge_flux_history_m3_s",
    "prescribed_head_flux_history_m3_s",
    "drainage_flux_history_m3_s",
    "residual_history_m3_s",
)


def test_a_period_cut_into_time_steps_exports_the_mean_of_its_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stamp closes its period: the head of the last step, the mean flux.

    Four periods of one day solve the same four backward-Euler steps as one
    period of four days cut into four steps, so their rows are the raw steps.
    """
    sub_stepped = _relaxation(tmp_path, monkeypatch, n_periods=1, n_steps=4)
    by_step = _relaxation(tmp_path, monkeypatch, n_periods=4, n_steps=1)

    np.testing.assert_allclose(
        sub_stepped.state.head_history_m[1:], by_step.state.head_history_m[-1:], rtol=0, atol=0
    )
    for name in _FLUX_HISTORIES:
        period = np.asarray(getattr(sub_stepped.state, name))[1:]
        steps = np.asarray(getattr(by_step.state, name))[1:]
        assert period.shape == (1, steps.shape[1]), name
        np.testing.assert_allclose(period[0], steps.mean(axis=0), rtol=1e-12, atol=1e-18)

    outflow = np.asarray(sub_stepped.state.prescribed_head_flux_history_m3_s)[1:].sum(axis=1)
    by_day = np.asarray(by_step.state.prescribed_head_flux_history_m3_s)[1:].sum(axis=1)
    # The outflow falls over the period: the mean is not the value of the last day.
    assert np.mean(by_day) > 1.5 * by_day[-1]
    assert outflow[0] == pytest.approx(np.mean(by_day), rel=1e-12)

    # The storage change of the period, from the heads at both ends, closes the
    # budget with the mean outflow. The held cell keeps its head.
    mesh = row_mesh()
    heads = np.asarray(sub_stepped.state.head_history_m)
    stored = (heads[-1, 1:] - heads[0, 1:]) * mesh.storage_coefficient[1:] * mesh.cell_area_m2[1:]
    assert -stored.sum() / (4.0 * DAY_S) == pytest.approx(outflow[0], rel=1e-9)


@pytest.mark.petsc
@pytest.mark.parametrize(
    ("closure", "option"),
    [("vi_obstacle", "vi_substeps_per_period"), ("ts_vi_obstacle", "ts_vi_steps_per_period")],
)
def test_a_petsc_closure_exports_the_mean_of_its_internal_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, closure: str, option: str
) -> None:
    """The internal steps of a PETSc closure are steps of the period too."""
    petsc = {"runtime_backend": "petsc", "surface_interaction_model": closure}
    internal = _relaxation(tmp_path, monkeypatch, n_periods=1, n_steps=1, **petsc, **{option: 4})
    by_day = _relaxation(tmp_path, monkeypatch, n_periods=4, n_steps=1, **petsc, **{option: 1})

    np.testing.assert_allclose(
        internal.state.head_history_m[1:], by_day.state.head_history_m[-1:], rtol=0, atol=1e-9
    )
    for name in ("prescribed_head_flux_history_m3_s", "residual_history_m3_s"):
        period = np.asarray(getattr(internal.state, name))[1:]
        steps = np.asarray(getattr(by_day.state, name))[1:]
        assert period.shape == (1, steps.shape[1]), name
        np.testing.assert_allclose(period[0], steps.mean(axis=0), rtol=1e-7, atol=1e-12)
    by_day_outflow = np.asarray(by_day.state.prescribed_head_flux_history_m3_s)[1:].sum(axis=1)
    assert np.mean(by_day_outflow) > 1.5 * by_day_outflow[-1]
