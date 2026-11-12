"""First-order (FOSM) width of calibrated parameters.

The Jacobian of simulated values (observation units) on parameters is built by
forward differences, and the covariance is s2 * inv(J'J). On the linear model
y = A p it has a closed form, which the tests hold the code against.
"""

from __future__ import annotations

import pickle
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config_phases import CalibUncertaintyDecl
from hydromodpy.calibration.metrics import composite as _composite
from hydromodpy.calibration.optim.fosm import (
    ParameterUncertainty,
    forward_difference_jacobian,
    linearized_covariance,
    uncertainty_from_covariance,
)
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import search
from hydromodpy.calibration.runners import trial as _trial
from hydromodpy.calibration.runners.search import attach_a_linearized_width
from hydromodpy.core.exceptions import UncertaintyNotAvailableError
from tests.unit.calibration._factories_runners import bare_trial_ctx

A = np.array([[1.0, 0.0], [1.0, 1.0], [0.0, 2.0], [2.0, 1.0], [1.0, 3.0]])
NAMES = ("K", "Sy")
TRUTH = {"K": 2.0, "Sy": 0.5}


def _simulate(parameters):
    p = np.array([parameters["K"], parameters["Sy"]], dtype=float)
    return A @ p


def _simulate_all(runs):
    return [_simulate(run) for run in runs]


REFERENCE = {"K": 2.0, "Sy": 0.5}


def _model(values) -> np.ndarray:
    k, sy = float(values["K"]), float(values["Sy"])
    return np.array([k**2, k * sy, np.exp(sy)])


def _capturing():
    asked: list[dict] = []

    def simulate_all(runs):
        asked.extend(runs)
        return [_model(run) for run in runs]

    return simulate_all, asked


RESIDUALS = np.array([0.1, -0.2, 0.05, 0.15, -0.1])


def recorded_runs(parameter, value):
    seen: list[float] = []

    def record(runs):
        seen.extend(run[parameter] for run in runs)
        return [np.zeros(2)] * len(runs)

    forward_difference_jacobian((parameter,), {parameter: value}, record, relative_step=0.01)
    return seen


def test_linear_model_gives_its_matrix():
    # Forward differences are exact on a linear model, to machine precision.
    jacobian = forward_difference_jacobian(NAMES, TRUTH, _simulate_all)
    assert jacobian == pytest.approx(A, abs=1e-9)


def test_derivatives_ignore_run_order():
    simulate_all, _ = _capturing()
    jacobian = forward_difference_jacobian(("K", "Sy"), REFERENCE, simulate_all, relative_step=1e-6)
    expected = np.array([[4.0, 0.0], [0.5, 2.0], [0.0, np.exp(0.5)]])
    assert jacobian == pytest.approx(expected, rel=1e-4, abs=1e-5)


def test_step_scales_with_value():
    # One perturbed run, a per cent away, then the reference run.
    assert recorded_runs("K", 100.0) == [pytest.approx(101.0), pytest.approx(100.0)]


def test_step_at_zero():
    # Zero has no scale of its own to take a fraction of.
    assert recorded_runs("K", 0.0)[0] == pytest.approx(0.01)


def test_missing_run_and_no_parameter():
    with pytest.raises(ValueError):
        forward_difference_jacobian(("K",), {"K": 1.0}, lambda runs: [np.zeros(3)])

    assert forward_difference_jacobian((), {}, lambda runs: [np.zeros(3)]).shape == (3, 0)


def test_covariance_on_a_linear_model():
    dof = A.shape[0] - A.shape[1]
    expected = (float(RESIDUALS @ RESIDUALS) / dof) * np.linalg.inv(A.T @ A)
    assert linearized_covariance(A, RESIDUALS) == pytest.approx(expected)


def test_perfect_fit_has_no_width():
    covariance = linearized_covariance(A, np.zeros(A.shape[0]))
    assert covariance == pytest.approx(np.zeros((2, 2)))


def test_sigma_and_correlation_of_each_parameter():
    covariance = linearized_covariance(A, RESIDUALS)
    for index, item in enumerate(uncertainty_from_covariance(NAMES, TRUTH, covariance)):
        assert item.sigma == pytest.approx(np.sqrt(covariance[index, index]))
        assert item.correlations[item.parameter] == pytest.approx(1.0)


def test_relative_width_at_zero_value():
    item = ParameterUncertainty(parameter="K", value=0.0, sigma=1.0, correlations={})
    assert item.relative_sigma is None
    assert item.to_dict()["relative_sigma"] is None


# Two observations and two parameters leave no degrees of freedom. The second
# column is twice the first, so J'J is singular.
COLLINEAR = np.column_stack([A[:, 0], 2.0 * A[:, 0]])


def no_runs_answered(runs):
    return []


def uneven_runs(runs):
    return [np.zeros(5), np.zeros(4)]


JACOBIAN_REFUSALS = [
    pytest.param(no_runs_answered, -0.5, "has to be positive, got -0.5", id="negative step"),
    pytest.param(
        uneven_runs,
        0.01,
        "same observations in the same order",
        id="runs of different length",
    ),
]
COVARIANCE_REFUSALS = [
    pytest.param(A[:2], np.zeros(2), "degree", id="no degree of freedom"),
    pytest.param(
        COLLINEAR,
        np.full(5, 0.1),
        "did not identify its parameters separately",
        id="collinear parameters",
    ),
    pytest.param(A, np.zeros(3), "same observations", id="residuals of the wrong length"),
]


@pytest.mark.parametrize(("simulate_all", "step", "match"), JACOBIAN_REFUSALS)
def test_jacobian_refusals(simulate_all, step, match):
    with pytest.raises(ValueError, match=match):
        forward_difference_jacobian(("K",), {"K": 1.0}, simulate_all, relative_step=step)


@pytest.mark.parametrize(("jacobian", "residuals", "match"), COVARIANCE_REFUSALS)
def test_covariance_refusals(jacobian, residuals, match):
    with pytest.raises(ValueError, match=match):
        linearized_covariance(jacobian, residuals)


# The runner pass, driven over the same linear model, with no solver.


@pytest.fixture
def wired(monkeypatch):
    state: dict[str, object] = {"runs": 0}
    captured: dict[str, object] = {}

    def _capture(
        _outputs,
        *,
        ctx=None,
        objective_blocks=None,
        window=None,
        min_samples=1,
    ):
        # Recorded, not discarded: the runner is what reads the blocks off the
        # document, and a stub that shrugs at them would keep passing if it stopped.
        state["capture_kwargs"] = {
            "objective_blocks": objective_blocks,
            "window": window,
            "min_samples": min_samples,
        }
        del ctx

        def metric_fn(trial_ctx, *, objective=None, variable=None):
            del objective, variable
            captured["simulated"] = _simulate(trial_ctx)
            captured["observed"] = A @ np.array([TRUTH["K"], TRUTH["Sy"]]) + np.array(
                [0.1, -0.2, 0.05, 0.15, -0.1]
            )
            return 0.0, {}

        return metric_fn, captured

    def _run_trial_light(_ctx, values, **_kwargs):
        state["runs"] = int(state["runs"]) + 1
        # The capture reads the parameter set straight off the "trial context".
        _kwargs["metric_fn"](values)
        return SimpleNamespace(status="completed", primary_metric=0.0, duration_s=0.0, error=None)

    monkeypatch.setattr(_composite, "build_paired_vector_capture", _capture)
    monkeypatch.setattr(_trial, "run_trial_light", _run_trial_light)
    return state, captured


def make_report():
    return CalibrationReport(
        session_id="s",
        method="scipy_nelder_mead",
        n_trials=1,
        best_cost=0.5,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters=dict(TRUTH),
    )


def make_cfg():
    return SimpleNamespace(
        outputs={"gauge": SimpleNamespace(observes="NANCON")},
        objective_blocks=[],
        objective=None,
        variable=None,
        window=None,
        aggregate=SimpleNamespace(min_samples=1),
        reject_water_budget_above=None,
        parallel=1,
    )


def make_space():
    return SimpleNamespace(names=("K", "Sy"))


def test_report_kept_without_a_width(monkeypatch):
    # A search already paid for is not thrown away over a declaration.
    def _refuses(*_args, **_kwargs):
        raise UncertaintyNotAvailableError("this document cannot carry a width")

    monkeypatch.setattr(_composite, "build_paired_vector_capture", _refuses)
    report = make_report()

    kept = attach_a_linearized_width(
        report,
        cfg=make_cfg(),
        trial_ctx=bare_trial_ctx(),
        space=make_space(),
        perturbation=0.01,
    )

    assert kept is report
    assert kept.parameter_uncertainty == ()


def test_broken_record_still_raises(monkeypatch):
    # Only the typed refusal is absorbed.
    def _breaks(*_args, **_kwargs):
        raise ValueError("observes station 'GHOST', which the discharge family did not load")

    monkeypatch.setattr(_composite, "build_paired_vector_capture", _breaks)

    with pytest.raises(ValueError, match="did not load"):
        attach_a_linearized_width(
            make_report(),
            cfg=make_cfg(),
            trial_ctx=bare_trial_ctx(),
            space=make_space(),
            perturbation=0.01,
        )


def test_parallel_runs_give_the_same_width(wired, monkeypatch):
    pools = []

    class _Pool:
        def __init__(self, evaluator_class, options, *, width):
            # What a real pool sends to its workers has to cross a process.
            pickle.dumps((evaluator_class, options))
            self.width, self.options, self.closed = width, options, False
            self._evaluator = evaluator_class(**options)
            self.trial_series_sink = self._evaluator.trial_series_sink
            pools.append(self)

        def evaluate(self, request):
            return self._evaluator.evaluate(request)

        def close(self):
            self.closed = True

    monkeypatch.setattr(search, "TrialWorkerPool", _Pool)
    cfg, retention = make_cfg(), object()
    kwargs = {"space": make_space(), "perturbation": 0.01}
    one_by_one = attach_a_linearized_width(
        make_report(), cfg=cfg, trial_ctx=bare_trial_ctx(), **kwargs
    )
    cfg.parallel = 8
    ctx = replace(bare_trial_ctx(), kept_solves=retention)
    side_by_side = attach_a_linearized_width(make_report(), cfg=cfg, trial_ctx=ctx, **kwargs)

    assert side_by_side.parameter_uncertainty == one_by_one.parameter_uncertainty
    [pool] = pools
    # One run per parameter and the reference, and no run keeps a solve.
    assert (pool.width, pool.closed, pool.options["trial_ctx"].kept_solves) == (3, True, None)


def test_width_reaches_the_report(wired):
    updated = attach_a_linearized_width(
        make_report(),
        cfg=make_cfg(),
        trial_ctx=bare_trial_ctx(),
        space=make_space(),
        perturbation=0.01,
    )
    assert updated.best_parameters == TRUTH
    assert {item.parameter for item in updated.parameter_uncertainty} == {"K", "Sy"}
    assert all(item.sigma > 0.0 for item in updated.parameter_uncertainty)
    assert "parameter_uncertainty" in updated.to_dict()


def test_report_without_answer_untouched(wired):
    empty = replace(make_report(), best_parameters=None)
    assert (
        attach_a_linearized_width(
            empty,
            cfg=make_cfg(),
            trial_ctx=bare_trial_ctx(),
            space=make_space(),
            perturbation=0.01,
        )
        is empty
    )


def test_posterior_is_refused_naming_the_offered_methods():
    # A posterior needs a likelihood, which needs residuals with an error model.
    with pytest.raises(ValueError, match="needs a likelihood") as caught:
        CalibUncertaintyDecl.model_validate({"method": "posterior"})
    assert "linearized" in str(caught.value)
    assert "multistart" in str(caught.value)
