"""The three things phase 2 of the method needs before it can be declared.

``nse_log`` as a registered metric, a scoring window written in dates rather
than in samples, and a per-block burn-in that a block can actually switch off.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    CalibrationConfig,
    CalibScoringWindow,
    scoring_window_bounds,
)
from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.optim.objective import (
    HIGHER_IS_BETTER,
    METRICS,
    build_objective_from_config,
    clip_negatives_for_log_metric,
)
from hydromodpy.core.metrics import log_nse


class TestNseLogRegistration:
    def test_nse_log_is_registered_and_higher_is_better(self) -> None:
        assert METRICS["nse_log"] is log_nse
        assert "nse_log" in HIGHER_IS_BETTER

    def test_a_block_can_declare_it(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [1.0, 2.0, 3.0, 4.0],
                    }
                },
                "objective_blocks": [{"name": "b", "metric": "nse_log", "uses_outputs": ["q"]}],
            }
        )
        assert cfg.objective_blocks[0].metric == "nse_log"

    def test_a_perfect_simulation_costs_zero(self) -> None:
        # nse_log is higher-is-better, so the cost is 1 - value and a perfect
        # match must land on zero, not on one.
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [1.0, 2.0, 3.0, 4.0],
                    }
                },
                "objective_blocks": [{"name": "b", "metric": "nse_log", "uses_outputs": ["q"]}],
            }
        )
        objective = build_objective_from_config(cfg)
        assert objective.evaluate({"q": [1.0, 2.0, 3.0, 4.0]}).total == pytest.approx(0.0)


class TestNegativeDischargeClipping:
    def test_clipping_counts_both_sides(self) -> None:
        sim, obs, n_clipped = clip_negatives_for_log_metric(
            np.array([-1.0, 2.0]), np.array([1.0, -3.0])
        )
        assert n_clipped == 2
        assert sim.tolist() == [0.0, 2.0]
        assert obs.tolist() == [1.0, 0.0]

    def test_a_clean_series_is_returned_untouched(self) -> None:
        sim, obs, n_clipped = clip_negatives_for_log_metric(
            np.array([1.0, 2.0]), np.array([1.0, 3.0])
        )
        assert n_clipped == 0
        assert sim.tolist() == [1.0, 2.0]

    def test_the_block_reports_how_many_were_clipped(self) -> None:
        # A reconstructed discharge below a dam with releases can be negative;
        # log_nse would otherwise raise, and clipping in silence would hide a
        # sign error that looks exactly the same.
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [1.0, 2.0, 3.0, 4.0],
                    }
                },
                "objective_blocks": [{"name": "b", "metric": "nse_log", "uses_outputs": ["q"]}],
            }
        )
        value = build_objective_from_config(cfg).evaluate({"q": [-1.0, 2.0, 3.0, 4.0]})
        assert value.components["b.n_clipped"] == 1.0
        assert np.isfinite(value.total)

    def test_score_clips_before_the_log(self, caplog) -> None:
        index = pd.date_range("2020-01-01", periods=4, freq="D")
        observed = pd.Series([1.0, 2.0, 3.0, 4.0], index=index)
        simulated = pd.Series([-1.0, 2.0, 3.0, 4.0], index=index)
        cost = score(observed, simulated, "nse_log")
        assert np.isfinite(cost)
        assert "clipped to zero" in caplog.text


class TestScoringWindow:
    def test_bounds_parse_to_timestamps(self) -> None:
        window = CalibScoringWindow(start="2012-01-01", end="2015-12-31")
        start, end = scoring_window_bounds(window)
        assert (start, end) == (pd.Timestamp("2012-01-01"), pd.Timestamp("2015-12-31"))
        assert scoring_window_bounds(None) is None

    def test_an_open_bound_stays_open(self) -> None:
        start, end = scoring_window_bounds(CalibScoringWindow(start="2012-01-01"))
        assert start == pd.Timestamp("2012-01-01")
        assert end is None

    def test_a_reversed_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is after end"):
            CalibScoringWindow(start="2015-01-01", end="2012-01-01")

    def test_a_date_that_is_not_a_date_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is not a date"):
            CalibScoringWindow(start="not-a-date")

    def test_score_drops_the_samples_outside_the_window(self) -> None:
        index = pd.date_range("2020-01-01", periods=4, freq="D")
        observed = pd.Series([1.0, 1.0, 1.0, 1.0], index=index)
        # The first two days are badly simulated, the last two are perfect.
        simulated = pd.Series([9.0, 9.0, 1.0, 1.0], index=index)
        window = (pd.Timestamp("2020-01-03"), None)

        full = score(observed, simulated, "rmse")
        scored = score(observed, simulated, "rmse", scoring_window=window)

        assert scored == pytest.approx(0.0)
        assert full > scored

    def test_an_empty_window_is_an_error_not_an_empty_score(self) -> None:
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        series = pd.Series([1.0, 2.0, 3.0], index=index)
        with pytest.raises(ValueError, match="leaves no aligned sample"):
            score(
                series,
                series,
                "rmse",
                scoring_window=(pd.Timestamp("2030-01-01"), None),
            )

    def test_dates_and_sample_counts_cannot_both_be_declared(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            CalibrationConfig.model_validate(
                {
                    "method": "grid",
                    "warmup_periods": 5,
                    "scoring_window": {"start": "2012-01-01"},
                }
            )


class TestBlockWarmup:
    def _config(self, block: dict) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "warmup_periods": 2,
                "outputs": {
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [9.0, 9.0, 1.0, 1.0],
                    }
                },
                "objective_blocks": [{"uses_outputs": ["q"], **block}],
            }
        )

    def test_a_block_inherits_the_calibration_wide_burn_in(self) -> None:
        objective = build_objective_from_config(self._config({"name": "b", "metric": "rmse"}))
        # The first two samples are dropped, so the perfect tail scores zero.
        assert objective.evaluate({"q": [0.0, 0.0, 1.0, 1.0]}).total == pytest.approx(0.0)

    def test_a_block_can_switch_the_burn_in_off_with_zero(self) -> None:
        # Reading warmup with `or` made 0 fall back to the default, so a block
        # could declare 0 and still drop samples.
        objective = build_objective_from_config(
            self._config({"name": "b", "metric": "rmse", "warmup": 0})
        )
        assert objective.evaluate({"q": [0.0, 0.0, 1.0, 1.0]}).total > 0.0

    def test_a_block_can_raise_its_own_burn_in(self) -> None:
        objective = build_objective_from_config(
            self._config({"name": "b", "metric": "rmse", "warmup": 3})
        )
        assert objective.evaluate({"q": [0.0, 0.0, 0.0, 1.0]}).total == pytest.approx(0.0)
