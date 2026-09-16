"""Two things a calibration run knows and used to keep to itself.

A stream-network stage calibrates the ratio K/R, never K alone, and the
documentation tells the modeller to divide by ``R_mean_m_s`` before reading
the value as a conductivity. The report used to publish no ratio at all.

And a value that closed on a search bound is the best point of a search that
was forbidden to look further, not a value the trials converged onto. That
used to be an informational line, indistinguishable from an ordinary interval.
"""

from __future__ import annotations

import logging

from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.tolerance import ParameterInterval
from hydromodpy.calibration.runners.cli_runner import (
    _log_parameter_interval,
    _network_k_over_r_extra,
)


def _interval(*, reaches_lower: bool = False, reaches_upper: bool = False) -> ParameterInterval:
    return ParameterInterval(
        name="Sy",
        best=5.0e-3,
        lower=5.0e-3,
        upper=8.0e-3,
        tolerance=0.05,
        mode="relative",
        threshold=0.1,
        n_within=3,
        n_trials=20,
        reaches_lower_bound=reaches_lower,
        reaches_upper_bound=reaches_upper,
    )


def _result(objective_value: float = 0.123) -> EvaluationResult:
    return EvaluationResult(trial_id=0, sim_id=None, objective_value=objective_value)


class TestKOverR:
    def test_present_for_a_network_run(self) -> None:
        extra = _network_k_over_r_extra(
            has_network_output=True,
            components={"R_mean_m_s": 2.0e-8, "alpha_obs_closure": 0.9},
            best_parameters={"K": 5.0e-4},
        )

        assert extra["k_over_r"] == 5.0e-4 / 2.0e-8
        assert "not a conductivity" in extra["k_over_r_note"]

    def test_absent_without_a_network_output(self) -> None:
        extra = _network_k_over_r_extra(
            has_network_output=False,
            components={"R_mean_m_s": 2.0e-8},
            best_parameters={"K": 5.0e-4},
        )

        assert extra == {}

    def test_absent_without_r_mean_m_s(self) -> None:
        extra = _network_k_over_r_extra(
            has_network_output=True,
            components={"alpha_obs_closure": 0.9},
            best_parameters={"K": 5.0e-4},
        )

        assert extra == {}

    def test_absent_with_no_best_parameters(self) -> None:
        extra = _network_k_over_r_extra(
            has_network_output=True,
            components={"R_mean_m_s": 2.0e-8},
            best_parameters=None,
        )

        assert extra == {}

    def test_absent_for_more_than_one_calibrated_parameter(self) -> None:
        extra = _network_k_over_r_extra(
            has_network_output=True,
            components={"R_mean_m_s": 2.0e-8},
            best_parameters={"K": 5.0e-4, "Sy": 0.1},
        )

        assert extra == {}


class TestBoundWarning:
    def test_warns_on_a_bound(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            _log_parameter_interval(_interval(reaches_lower=True), _result(0.42))

        assert caplog.records
        assert caplog.records[0].levelno == logging.WARNING
        assert "lower search bound" in caplog.text
        assert "0.42" in caplog.text

    def test_upper_bound_is_named_too(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            _log_parameter_interval(_interval(reaches_upper=True), _result())

        assert "upper search bound" in caplog.text

    def test_stays_informational_inside_the_interval(self, caplog) -> None:
        with caplog.at_level(logging.INFO):
            _log_parameter_interval(_interval(), _result())

        assert caplog.records
        assert caplog.records[0].levelno == logging.INFO
        assert "search bound" not in caplog.text
