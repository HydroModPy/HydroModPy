"""A first-order covariance, confronted where first-order is exact.

The reason a linearized covariance was withheld until it could be checked is that
a plausible-looking width is worse than none: nobody can tell by reading it whether
the arithmetic was right. On a linear model FOSM is not an approximation, so the
answer has a closed form and the implementation can be held against it rather than
against a feeling.

The model here is y = A p, so the Jacobian IS A, and with independent residuals of
variance s2 the covariance is exactly s2 * inv(A' A). Every assertion below compares
to that expression, computed separately.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.optim.fosm import (
    ParameterUncertainty,
    forward_difference_jacobian,
    linearized_covariance,
    uncertainty_from_covariance,
)

A = np.array(
    [
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 2.0],
        [2.0, 1.0],
        [1.0, 3.0],
    ]
)
NAMES = ("K", "Sy")
TRUTH = {"K": 2.0, "Sy": 0.5}


def _simulate(parameters):
    p = np.array([parameters["K"], parameters["Sy"]], dtype=float)
    return A @ p


class TestTheJacobian:
    def test_a_linear_model_reproduces_its_own_matrix(self) -> None:
        # Forward differences are exact on a linear model, to machine precision.
        J = forward_difference_jacobian(NAMES, TRUTH, _simulate)
        assert J == pytest.approx(A, abs=1e-9)

    def test_the_step_scales_with_the_value(self) -> None:
        seen: list[float] = []

        def _record(parameters):
            seen.append(parameters["K"])
            return _simulate({"K": parameters["K"], "Sy": 0.5})

        forward_difference_jacobian(("K",), {"K": 100.0}, _record, relative_step=0.01)
        # One reference run and one perturbed run, the latter a per cent away.
        assert seen == [pytest.approx(100.0), pytest.approx(101.0)]

    def test_a_parameter_sitting_at_zero_still_gets_a_step(self) -> None:
        # Zero has no scale of its own to take a fraction of.
        seen: list[float] = []

        def _record(parameters):
            seen.append(parameters["K"])
            return _simulate({"K": parameters["K"], "Sy": 0.0})

        forward_difference_jacobian(("K",), {"K": 0.0}, _record, relative_step=0.01)
        assert seen[1] == pytest.approx(0.01)

    def test_a_run_that_returns_a_different_number_of_values_is_refused(self) -> None:
        calls = {"n": 0}

        def _ragged(parameters):
            calls["n"] += 1
            return np.zeros(5 if calls["n"] == 1 else 4)

        with pytest.raises(ValueError, match="same observations in the same order"):
            forward_difference_jacobian(("K",), {"K": 1.0}, _ragged)


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

    def test_the_value_is_untouched(self) -> None:
        # The whole constraint: a width is reported beside the number, never instead.
        assert {item.parameter: item.value for item in self._uncertainty()} == TRUTH

    def test_a_parameter_is_perfectly_correlated_with_itself(self) -> None:
        for item in self._uncertainty():
            assert item.correlations[item.parameter] == pytest.approx(1.0)

    def test_the_tradeoff_names_the_other_parameter(self) -> None:
        k = next(item for item in self._uncertainty() if item.parameter == "K")
        tradeoff = k.strongest_tradeoff()
        assert tradeoff is not None
        assert tradeoff[0] == "Sy"
        assert abs(tradeoff[1]) <= 1.0

    def test_a_relative_width_is_none_at_a_value_of_zero(self) -> None:
        item = ParameterUncertainty(parameter="K", value=0.0, sigma=1.0, correlations={})
        assert item.relative_sigma is None
        assert item.to_dict()["relative_sigma"] is None


# -- the pass that attaches it to a report ------------------------------------


class TestThePassOverAReport:
    """The runner pass, driven over the same linear model, with no solver."""

    @pytest.fixture
    def wired(self, monkeypatch):
        from hydromodpy.calibration.metrics import composite as _composite
        from hydromodpy.calibration.runners import trial as _trial

        state: dict[str, object] = {"runs": 0}
        captured: dict[str, object] = {}

        def _capture(_outputs, *, ctx=None, scoring_window=None, min_samples=1):
            del ctx, scoring_window, min_samples

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
            return SimpleNamespace(status="completed", metrics={}, error=None)

        monkeypatch.setattr(_composite, "build_paired_vector_capture", _capture)
        monkeypatch.setattr(_trial, "run_trial_light", _run_trial_light)
        return state, captured

    def _report(self):
        from hydromodpy.calibration.report import CalibrationReport

        return CalibrationReport(
            session_id="s",
            method="scipy_nelder_mead",
            n_iterations=1,
            best_objective=0.5,
            best_sim_id=None,
            duration_s=1.0,
            save_runs="none",
            promoted=0,
            best_parameters=dict(TRUTH),
        )

    def _cfg(self):
        return SimpleNamespace(
            outputs={"gauge": SimpleNamespace(observes="NANCON")},
            objective=None,
            variable=None,
            scoring_window=None,
            aggregate=SimpleNamespace(min_samples=1),
            reject_water_budget_above=None,
        )

    def _space(self):
        return SimpleNamespace(names=("K", "Sy"))

    def test_one_run_per_parameter_plus_the_reference(self, wired) -> None:
        from hydromodpy.calibration.runners.cli_runner import attach_a_linearized_width

        state, _captured = wired
        attach_a_linearized_width(
            self._report(),
            cfg=self._cfg(),
            trial_ctx=SimpleNamespace(ctx=None),
            space=self._space(),
            perturbation=0.01,
        )
        assert state["runs"] == 3

    def test_the_width_reaches_the_report_and_the_values_do_not_move(self, wired) -> None:
        from hydromodpy.calibration.runners.cli_runner import attach_a_linearized_width

        updated = attach_a_linearized_width(
            self._report(),
            cfg=self._cfg(),
            trial_ctx=SimpleNamespace(ctx=None),
            space=self._space(),
            perturbation=0.01,
        )
        assert updated.best_parameters == TRUTH
        assert {item.parameter for item in updated.parameter_uncertainty} == {"K", "Sy"}
        assert all(item.sigma > 0.0 for item in updated.parameter_uncertainty)
        assert "parameter_uncertainty" in updated.to_dict()

    def test_a_report_with_no_answer_is_returned_untouched(self, wired) -> None:
        from dataclasses import replace

        from hydromodpy.calibration.runners.cli_runner import attach_a_linearized_width

        empty = replace(self._report(), best_parameters=None)
        assert (
            attach_a_linearized_width(
                empty,
                cfg=self._cfg(),
                trial_ctx=SimpleNamespace(ctx=None),
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
    from hydromodpy.calibration.config import CalibUncertaintyDecl

    with pytest.raises(ValueError, match="needs a likelihood"):
        CalibUncertaintyDecl.model_validate({"method": "posterior"})


def test_the_refusal_names_the_two_that_are_offered() -> None:
    from hydromodpy.calibration.config import CalibUncertaintyDecl

    try:
        CalibUncertaintyDecl.model_validate({"method": "posterior"})
    except ValueError as exc:
        message = str(exc)
    assert "linearized" in message
    assert "multistart" in message
