"""Two things a calibration run knows and used to keep to itself.

A stream-network stage that moves K identifies the ratio K/R, never K alone.
The report publishes that ratio with the other derived values of the paper's
Table 1, and only for that search: the criterion can drive any parameter.

And a value that closed on a search bound is the best point of a search that
was forbidden to look further, not a value the trials converged onto. That
used to be an informational line, indistinguishable from an ordinary interval.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.tolerance import ParameterInterval
from hydromodpy.calibration.runners.cli_runner import (
    _log_parameter_interval,
    _network_ratios_extra,
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


def _space(*, path: str = "flow.param.K.field.value", mode: str = "replace", units=None):
    return ParameterSpace(
        [CalibParameter(name="K", lower=1e-7, upper=1e-3, path=path, mode=mode, units=units)]
    )


def _ratios(components, *, best=None, space=None, outputs=("network",), trial_ctx=None):
    return _network_ratios_extra(
        network_outputs=outputs,
        components=components,
        best_parameters={"K": 5.0e-4} if best is None else best,
        space=_space() if space is None else space,
        trial_ctx=trial_ctx,
    )


class TestPaperRatios:
    def test_every_ratio_of_table_1_for_a_conductivity_search(self) -> None:
        extra = _ratios(
            {
                "network.R_mean_m_s": 2.0e-8,
                "network.d_sat_m": 12.0,
                "network.d_sat_over_d": 0.4,
            }
        )

        k_over_r = 5.0e-4 / 2.0e-8
        assert extra["k_over_r"] == k_over_r
        assert extra["k_optim_m_s"] == 5.0e-4
        assert extra["d_sat_m"] == 12.0
        assert extra["t_over_r_m"] == k_over_r * 12.0
        assert extra["t_optim_m2_s"] == 5.0e-4 * 12.0
        assert extra["d_sat_over_d"] == 0.4
        assert "t_over_r" in extra["k_over_r_note"]
        assert "full" not in extra["k_over_r_note"]

    def test_reads_the_recharge_under_the_output_name(self) -> None:
        # The trial publishes every network diagnostic as <output>.<key>. The
        # bare key is what the report used to read, and it found nothing.
        assert _ratios({"R_mean_m_s": 2.0e-8}) == {}
        assert _ratios({"network.R_mean_m_s": 2.0e-8})["k_over_r"] == 5.0e-4 / 2.0e-8

    def test_without_a_saturated_thickness_only_k_over_r(self) -> None:
        extra = _ratios({"network.R_mean_m_s": 2.0e-8})

        assert set(extra) == {"k_over_r", "k_optim_m_s", "k_over_r_note"}

    def test_a_nearly_full_aquifer_is_said(self) -> None:
        extra = _ratios(
            {
                "network.R_mean_m_s": 2.0e-8,
                "network.d_sat_m": 27.0,
                "network.d_sat_over_d": 0.9,
            }
        )

        assert "90% full" in extra["k_over_r_note"]

    def test_the_conductivity_is_read_in_its_declared_unit(self) -> None:
        extra = _ratios({"network.R_mean_m_s": 2.0e-8}, space=_space(units="m/d"))

        assert extra["k_optim_m_s"] == pytest.approx(5.0e-4 / 86400.0)

    def test_the_field_unit_is_the_one_the_model_reads(self) -> None:
        field = SimpleNamespace(unit="m/d")
        trial_ctx = SimpleNamespace(
            base_cfg=SimpleNamespace(
                flow=SimpleNamespace(param={"K": SimpleNamespace(field=field)})
            )
        )

        extra = _ratios(
            {"network.R_mean_m_s": 2.0e-8}, space=_space(units="m/s"), trial_ctx=trial_ctx
        )

        assert extra["k_optim_m_s"] == pytest.approx(5.0e-4 / 86400.0)

    def test_the_note_names_the_output_it_read(self) -> None:
        extra = _ratios(
            {"a_net.R_mean_m_s": 2.0e-8, "b_net.R_mean_m_s": 9.0e-8},
            outputs=("b_net", "a_net"),
        )

        assert extra["k_over_r"] == 5.0e-4 / 2.0e-8
        assert "'a_net'" in extra["k_over_r_note"]

    def test_a_dry_catchment_is_a_value_not_a_gap(self) -> None:
        extra = _ratios({"network.R_mean_m_s": 2.0e-8, "network.d_sat_m": 0.0})

        assert extra["d_sat_m"] == 0.0
        assert extra["t_optim_m2_s"] == 0.0

    def test_a_unit_that_is_not_a_conductivity_warns_after_the_run(self, caplog) -> None:
        # The session is already saved when the report is assembled, so a
        # wrong unit costs the ratios and never the run.
        with caplog.at_level(logging.WARNING):
            extra = _ratios({"network.R_mean_m_s": 2.0e-8}, space=_space(units="-"))

        assert extra == {}
        assert "No K/R in the report" in caplog.text

    def test_absent_for_another_parameter(self) -> None:
        # The criterion drives any parameter. A thickness divided by R is not K/R.
        space = _space(path="domain.depth_model.thickness")

        assert _ratios({"network.R_mean_m_s": 2.0e-8}, space=space) == {}

    def test_absent_for_a_multiplier(self) -> None:
        assert _ratios({"network.R_mean_m_s": 2.0e-8}, space=_space(mode="scale")) == {}

    def test_absent_without_a_network_output(self) -> None:
        assert _ratios({"network.R_mean_m_s": 2.0e-8}, outputs=()) == {}

    def test_absent_without_r_mean_m_s(self) -> None:
        assert _ratios({"network.alpha_obs_closure": 0.9}) == {}

    def test_absent_with_no_best_parameters(self) -> None:
        extra = _network_ratios_extra(
            network_outputs=("network",),
            components={"network.R_mean_m_s": 2.0e-8},
            best_parameters=None,
            space=_space(),
        )

        assert extra == {}

    def test_absent_for_more_than_one_calibrated_parameter(self) -> None:
        extra = _ratios({"network.R_mean_m_s": 2.0e-8}, best={"K": 5.0e-4, "Sy": 0.1})

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
