"""Tests of `optim.fosm`."""

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

# From test_a_linearized_width_is_exact_where_the_model_is_linear.py
# A first-order covariance, confronted where first-order is exact.
#
# The reason a linearized covariance was withheld until it could be checked is that
# a plausible-looking width is worse than none: nobody can tell by reading it whether
# the arithmetic was right. On a linear model FOSM is not an approximation, so the
# answer has a closed form and the implementation can be held against it rather than
# against a feeling.
#
# The model here is y = A p, so the Jacobian IS A, and with independent residuals of
# variance s2 the covariance is exactly s2 * inv(A' A). Every assertion below compares
# to that expression, computed separately.


A = np.array([[1.0, 0.0], [1.0, 1.0], [0.0, 2.0], [2.0, 1.0], [1.0, 3.0]])
NAMES = ("K", "Sy")
TRUTH = {"K": 2.0, "Sy": 0.5}


def _simulate(parameters):
    p = np.array([parameters["K"], parameters["Sy"]], dtype=float)
    return A @ p


def _simulate_all(runs):
    return [_simulate(run) for run in runs]


class TestTheJacobian:
    def test_a_linear_model_reproduces_its_own_matrix(self) -> None:
        # Forward differences are exact on a linear model, to machine precision.
        J = forward_difference_jacobian(NAMES, TRUTH, _simulate_all)
        assert J == pytest.approx(A, abs=1e-9)

    def test_the_step_scales_with_the_value(self) -> None:
        seen: list[float] = []

        def _record(runs):
            seen.extend(run["K"] for run in runs)
            return [np.zeros(2)] * len(runs)

        forward_difference_jacobian(("K",), {"K": 100.0}, _record, relative_step=0.01)
        # One perturbed run, a per cent away, then the reference run.
        assert seen == [pytest.approx(101.0), pytest.approx(100.0)]

    def test_a_parameter_sitting_at_zero_still_gets_a_step(self) -> None:
        # Zero has no scale of its own to take a fraction of.
        seen: list[float] = []

        def _record(runs):
            seen.extend(run["K"] for run in runs)
            return [np.zeros(2)] * len(runs)

        forward_difference_jacobian(("K",), {"K": 0.0}, _record, relative_step=0.01)
        assert seen[0] == pytest.approx(0.01)

    def test_a_run_missing_from_the_answer_is_refused_and_no_parameter_gives_no_column(
        self,
    ) -> None:
        with pytest.raises(ValueError):
            forward_difference_jacobian(("K",), {"K": 1.0}, lambda runs: [np.zeros(3)])

        assert forward_difference_jacobian((), {}, lambda runs: [np.zeros(3)]).shape == (3, 0)

    def test_a_step_that_is_not_positive_is_refused(self) -> None:
        with pytest.raises(ValueError, match="has to be positive, got -0.5"):
            forward_difference_jacobian(("K",), {"K": 1.0}, lambda runs: [], relative_step=-0.5)

    def test_a_run_that_returns_a_different_number_of_values_is_refused(self) -> None:
        with pytest.raises(ValueError, match="same observations in the same order"):
            forward_difference_jacobian(("K",), {"K": 1.0}, lambda runs: [np.zeros(5), np.zeros(4)])


class TestTheCovariance:
    def test_it_equals_the_closed_form_on_a_linear_model(self) -> None:
        residuals = np.array([0.1, -0.2, 0.05, 0.15, -0.1])
        dof = A.shape[0] - A.shape[1]
        expected = (float(residuals @ residuals) / dof) * np.linalg.inv(A.T @ A)

        assert linearized_covariance(A, residuals) == pytest.approx(expected)

    def test_a_perfect_fit_has_no_width(self) -> None:
        covariance = linearized_covariance(A, np.zeros(A.shape[0]))
        assert covariance == pytest.approx(np.zeros((2, 2)))

    def test_a_fit_with_nothing_left_over_is_refused(self) -> None:
        # Two observations and two parameters leave no degrees of freedom, so there
        # is no residual variance to give the covariance its scale.
        with pytest.raises(ValueError, match="degree"):
            linearized_covariance(A[:2], np.zeros(2))

    def test_two_parameters_the_data_cannot_separate_are_refused(self) -> None:
        # The second column is twice the first: any change in one is exactly
        # reproducible by the other, so J'J is singular.
        collinear = np.column_stack([A[:, 0], 2.0 * A[:, 0]])
        with pytest.raises(ValueError, match="did not identify its parameters separately"):
            linearized_covariance(collinear, np.array([0.1, 0.1, 0.1, 0.1, 0.1]))

    def test_a_residual_vector_of_the_wrong_length_is_refused(self) -> None:
        with pytest.raises(ValueError, match="same observations"):
            linearized_covariance(A, np.zeros(3))


class TestWhatIsReported:
    def _uncertainty(self) -> tuple[ParameterUncertainty, ...]:
        residuals = np.array([0.1, -0.2, 0.05, 0.15, -0.1])
        return uncertainty_from_covariance(NAMES, TRUTH, linearized_covariance(A, residuals))

    def test_each_sigma_is_the_square_root_of_its_own_variance(self) -> None:
        residuals = np.array([0.1, -0.2, 0.05, 0.15, -0.1])
        covariance = linearized_covariance(A, residuals)
        for index, item in enumerate(self._uncertainty()):
            assert item.sigma == pytest.approx(np.sqrt(covariance[index, index]))

    def test_a_parameter_is_perfectly_correlated_with_itself(self) -> None:
        for item in self._uncertainty():
            assert item.correlations[item.parameter] == pytest.approx(1.0)

    def test_a_relative_width_is_none_at_a_value_of_zero(self) -> None:
        item = ParameterUncertainty(parameter="K", value=0.0, sigma=1.0, correlations={})
        assert item.relative_sigma is None
        assert item.to_dict()["relative_sigma"] is None


# -- the pass that attaches it to a report ------------------------------------
class TestThePassOverAReport:
    """The runner pass, driven over the same linear model, with no solver."""

    @pytest.fixture
    def wired(self, monkeypatch):

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
            return SimpleNamespace(
                status="completed", primary_metric=0.0, duration_s=0.0, error=None
            )

        monkeypatch.setattr(_composite, "build_paired_vector_capture", _capture)
        monkeypatch.setattr(_trial, "run_trial_light", _run_trial_light)
        return state, captured

    def _report(self):
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

    def _cfg(self):
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

    def _space(self):
        return SimpleNamespace(names=("K", "Sy"))

    def test_a_document_that_carries_no_width_keeps_its_report(self, monkeypatch) -> None:
        """A search already paid for is not thrown away over a declaration."""

        def _refuses(*_args, **_kwargs):
            raise UncertaintyNotAvailableError("this document cannot carry a width")

        monkeypatch.setattr(_composite, "build_paired_vector_capture", _refuses)
        report = self._report()

        kept = attach_a_linearized_width(
            report,
            cfg=self._cfg(),
            trial_ctx=bare_trial_ctx(),
            space=self._space(),
            perturbation=0.01,
        )

        assert kept is report
        assert kept.parameter_uncertainty == ()

    def test_a_record_that_failed_to_load_still_leaves_loudly(self, monkeypatch) -> None:
        """Only the typed refusal is absorbed; a broken document is not."""

        def _breaks(*_args, **_kwargs):
            raise ValueError("observes station 'GHOST', which the discharge family did not load")

        monkeypatch.setattr(_composite, "build_paired_vector_capture", _breaks)

        with pytest.raises(ValueError, match="did not load"):
            attach_a_linearized_width(
                self._report(),
                cfg=self._cfg(),
                trial_ctx=bare_trial_ctx(),
                space=self._space(),
                perturbation=0.01,
            )

    def test_runs_side_by_side_give_the_width_the_runs_one_by_one_give(
        self, wired, monkeypatch
    ) -> None:
        pools = []

        class _Pool:
            """Runs in this process, and says how it was built and closed."""

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
        cfg, retention = self._cfg(), object()
        kwargs = {"space": self._space(), "perturbation": 0.01}
        one_by_one = attach_a_linearized_width(
            self._report(), cfg=cfg, trial_ctx=bare_trial_ctx(), **kwargs
        )
        cfg.parallel = 8
        ctx = replace(bare_trial_ctx(), kept_solves=retention)
        side_by_side = attach_a_linearized_width(self._report(), cfg=cfg, trial_ctx=ctx, **kwargs)

        assert side_by_side.parameter_uncertainty == one_by_one.parameter_uncertainty
        [pool] = pools
        # One run per parameter and the reference, and no run keeps a solve.
        assert (pool.width, pool.closed, pool.options["trial_ctx"].kept_solves) == (3, True, None)

    def test_the_width_reaches_the_report_and_the_values_do_not_move(self, wired) -> None:
        updated = attach_a_linearized_width(
            self._report(),
            cfg=self._cfg(),
            trial_ctx=bare_trial_ctx(),
            space=self._space(),
            perturbation=0.01,
        )
        assert updated.best_parameters == TRUTH
        assert {item.parameter for item in updated.parameter_uncertainty} == {"K", "Sy"}
        assert all(item.sigma > 0.0 for item in updated.parameter_uncertainty)
        assert "parameter_uncertainty" in updated.to_dict()

    def test_a_report_with_no_answer_is_returned_untouched(self, wired) -> None:
        empty = replace(self._report(), best_parameters=None)
        assert (
            attach_a_linearized_width(
                empty,
                cfg=self._cfg(),
                trial_ctx=bare_trial_ctx(),
                space=self._space(),
                perturbation=0.01,
            )
            is empty
        )


def test_the_word_an_operator_will_type_gets_an_answer() -> None:
    """'posterior' is the obvious name; a bare enum error sends them hunting a bug.

    It is a position rather than an omission, so the position is what the message
    carries: a posterior needs a likelihood, a likelihood needs residuals with an
    error model, and an efficiency score is an aggregate stripped of its units.
    """

    with pytest.raises(ValueError, match="needs a likelihood"):
        CalibUncertaintyDecl.model_validate({"method": "posterior"})


def test_the_refusal_names_the_two_that_are_offered() -> None:
    try:
        CalibUncertaintyDecl.model_validate({"method": "posterior"})
    except ValueError as exc:
        message = str(exc)
    assert "linearized" in message
    assert "multistart" in message


# From test_a_linearized_width_reads_the_residuals_of_the_reference.py
# The residuals of a linearized width belong to the reference point.
#
# The runner captures the simulated vector of the last model run and reads its
# residuals once the Jacobian is built. That last run used to be the last
# perturbed trial, a point 1 % away from the calibrated answer.


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


def test_the_derivatives_do_not_depend_on_the_order_of_the_runs() -> None:
    simulate_all, _ = _capturing()

    jacobian = forward_difference_jacobian(("K", "Sy"), REFERENCE, simulate_all, relative_step=1e-6)

    expected = np.array([[4.0, 0.0], [0.5, 2.0], [0.0, np.exp(0.5)]])
    assert jacobian == pytest.approx(expected, rel=1e-4, abs=1e-5)
