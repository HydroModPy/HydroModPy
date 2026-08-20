"""Unit tests for the impounded-level calibration metrics.

Covers the efficiencies added to calibrate a reservoir stage - ``nse_seasonal``
(efficiency against the seasonal cycle instead of the flat mean), ``nse_delta``
and ``kge_delta`` (efficiency on the increments) - the ``reservoir`` composite
that pairs the first two, and the calibration seams that expose them.

Expected values are derived, not fitted. The seasonal benchmark is a
least-squares fit of the mean plus the first two harmonics, so a residual built
on the THIRD harmonic is orthogonal to that design over a whole number of
cycles: the benchmark is exactly the harmonic part, the denominator is exactly
the residual energy, and the score follows in closed form.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics.scalar import score
from hydromodpy.calibration.optim.objective import (
    HIGHER_IS_BETTER,
    METRICS,
    RESERVOIR_INCREMENT_STEP,
    ConfigBlockObjective,
    ObservationSet,
    ScalarObjective,
    SimulationOutput,
)
from hydromodpy.core.metrics import kge_delta, nse, nse_delta, nse_seasonal

SEASON = 365
"""Cycle length in samples assumed by ``nse_seasonal`` for a daily series."""

TWO_SEASONS = 2 * SEASON
"""Shortest series ``nse_seasonal`` accepts."""

RESIDUAL_AMPLITUDE = 0.4
"""Amplitude of the third harmonic left outside the fitted seasonal benchmark."""


def _seasonal_pair(
    n: int, period: int, *, amplitude: float = 0.5, start: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(benchmark, observed)`` with ``observed`` = benchmark + 3rd harmonic.

    ``start`` shifts the phase to check that the fit recovers it from the data.
    """
    theta = 2.0 * np.pi * (np.arange(n, dtype=float) + float(start)) / float(period)
    benchmark = 100.0 + 5.0 * np.cos(theta) + 2.0 * np.sin(2.0 * theta)
    return benchmark, benchmark + amplitude * np.cos(3.0 * theta)


def _residual_energy(n: int, amplitude: float) -> float:
    """Energy of ``amplitude * cos(3 theta)`` over ``n`` samples of whole cycles."""
    return amplitude**2 * n / 2.0


def _daily_reservoir(offset: float) -> tuple[np.ndarray, np.ndarray]:
    """Two years of daily stage and the same stage shifted by a constant ``offset``."""
    _, observed = _seasonal_pair(TWO_SEASONS, SEASON, amplitude=RESIDUAL_AMPLITUDE)
    return observed + offset, observed


# ---------------------------------------------------------------------------
# nse_delta / kge_delta: efficiency on the increments
# ---------------------------------------------------------------------------


class TestIncrementEfficiency:
    def test_perfect_fit_is_one(self) -> None:
        obs = np.array([0.0, 1.0, 3.0, 6.0, 10.0])
        assert nse_delta(obs, obs) == pytest.approx(1.0)

    def test_a_constant_offset_still_scores_one(self) -> None:
        """The increments are blind to the absolute stage, as the docstring warns."""
        obs = np.array([0.0, 1.0, 3.0, 6.0, 10.0])
        assert nse_delta(obs + 10.0, obs) == pytest.approx(1.0)
        assert nse(obs + 10.0, obs) < 0.0

    def test_known_value_step_one(self) -> None:
        obs = np.array([0.0, 1.0, 3.0, 6.0])
        sim = np.array([0.0, 2.0, 3.0, 5.0])
        # d_obs = [1, 2, 3], mean 2 -> denominator 1 + 0 + 1 = 2
        # d_sim = [2, 1, 2], residuals [1, -1, -1] -> numerator 3
        assert nse_delta(sim, obs) == pytest.approx(1.0 - 3.0 / 2.0)

    def test_known_value_step_two(self) -> None:
        obs = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
        sim = np.array([0.0, 1.0, 4.0, 6.0, 10.0, 16.0])
        # d_obs = [3, 5, 7, 9], mean 6 -> denominator 9 + 1 + 1 + 9 = 20
        # d_sim = [4, 5, 6, 10], residuals [1, 0, -1, 1] -> numerator 3
        assert nse_delta(sim, obs, step=2) == pytest.approx(1.0 - 3.0 / 20.0)

    def test_a_longer_step_forgives_a_phase_shift(self) -> None:
        """The rationale for ``RESERVOIR_INCREMENT_STEP``: 3 days must not flip signs."""
        days = np.arange(TWO_SEASONS, dtype=float)
        stage = (
            100.0
            + 5.0 * np.cos(2.0 * np.pi * days / SEASON)
            + 0.5 * np.sin(2.0 * np.pi * days / 10.0)
        )
        lagged = np.concatenate([stage[:3], stage[:-3]])

        assert nse_delta(lagged, stage, step=1) < 0.0
        assert nse_delta(lagged, stage, step=RESERVOIR_INCREMENT_STEP) > 0.9

    def test_step_below_one_is_coerced_to_one(self) -> None:
        obs = np.array([0.0, 1.0, 3.0, 6.0])
        sim = np.array([0.0, 2.0, 3.0, 5.0])
        assert nse_delta(sim, obs, step=0) == pytest.approx(nse_delta(sim, obs, step=1))

    def test_constant_increments_return_nan(self) -> None:
        """A linear ramp has zero increment variance: no benchmark, no score."""
        ramp = np.arange(10, dtype=float) * 2.0
        assert np.isnan(nse_delta(ramp, ramp))

    def test_series_shorter_than_the_step_window_returns_nan(self) -> None:
        obs = np.array([0.0, 1.0, 3.0])
        sim = np.array([0.0, 2.0, 3.0])
        assert np.isnan(nse_delta(sim, obs, step=2))
        assert np.isnan(nse_delta(sim[:2], obs[:2], step=1))

    def test_all_nan_returns_nan(self) -> None:
        nans = np.full(6, np.nan)
        assert np.isnan(nse_delta(nans, nans))
        assert np.isnan(nse_delta(np.zeros(6), nans))

    def test_empty_series_returns_nan(self) -> None:
        assert np.isnan(nse_delta(np.empty(0), np.empty(0)))

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            nse_delta(np.zeros(4), np.zeros(5))

    def test_kge_delta_perfect_fit_decomposition(self) -> None:
        obs = np.array([0.0, 1.0, 3.0, 6.0, 10.0])
        out = kge_delta(obs, obs)
        assert out == {"kge": 1.0, "r": 1.0, "alpha": 1.0, "beta": 1.0}

    def test_kge_delta_is_nan_when_the_increments_sum_to_zero(self) -> None:
        """Why KGE is not offered on increments: beta is a ratio of near-zero means."""
        obs = np.array([0.0, 1.0, 0.0])
        assert np.isnan(kge_delta(obs, obs)["kge"])

    def test_kge_delta_too_short_returns_all_nan(self) -> None:
        out = kge_delta(np.array([0.0, 1.0]), np.array([0.0, 2.0]))
        assert all(np.isnan(value) for value in out.values())


# ---------------------------------------------------------------------------
# nse_seasonal: efficiency against the seasonal cycle
# ---------------------------------------------------------------------------


class TestSeasonalEfficiency:
    def test_perfect_fit_is_one(self) -> None:
        _, observed = _seasonal_pair(24, 12)
        assert nse_seasonal(observed, observed, period=12) == pytest.approx(1.0)

    def test_predicting_the_seasonal_cycle_scores_zero(self) -> None:
        """The seasonal benchmark is to this metric what the mean is to NSE."""
        benchmark, observed = _seasonal_pair(24, 12)
        assert nse_seasonal(benchmark, observed, period=12) == pytest.approx(0.0)

    def test_known_value_for_a_constant_error(self) -> None:
        n, period, amplitude, error = 24, 12, 0.5, 0.1
        _, observed = _seasonal_pair(n, period, amplitude=amplitude)
        denominator = _residual_energy(n, amplitude)  # 0.25 * 12 = 3.0
        numerator = n * error**2  # 24 * 0.01 = 0.24
        assert denominator == pytest.approx(3.0)
        assert nse_seasonal(observed + error, observed, period=period) == pytest.approx(
            1.0 - numerator / denominator
        )
        assert nse_seasonal(observed + error, observed, period=period) == pytest.approx(0.92)

    def test_score_is_unchanged_by_where_the_series_is_cut(self) -> None:
        """A harmonic fit recovers the phase, so dropping a partial warm-up is safe."""
        _, from_day_zero = _seasonal_pair(24, 12)
        _, from_day_five = _seasonal_pair(24, 12, start=5)
        assert nse_seasonal(from_day_five + 0.1, from_day_five, period=12) == pytest.approx(
            nse_seasonal(from_day_zero + 0.1, from_day_zero, period=12)
        )

    def test_it_is_harsher_than_nse_on_a_seasonal_signal(self) -> None:
        """A model that only reproduces climatology scores ~1 on NSE and 0 here."""
        benchmark, observed = _seasonal_pair(24, 12)
        # Observed energy: 25 * 12 (1st) + 4 * 12 (2nd) + 0.25 * 12 (3rd) = 351.
        assert nse(benchmark, observed) == pytest.approx(1.0 - 3.0 / 351.0)
        assert nse_seasonal(benchmark, observed, period=12) == pytest.approx(0.0)

    def test_fewer_than_two_cycles_returns_nan(self) -> None:
        _, observed = _seasonal_pair(23, 12)
        assert np.isnan(nse_seasonal(observed, observed, period=12))

    def test_constant_observations_return_nan(self) -> None:
        flat = np.full(TWO_SEASONS, 100.0)
        assert np.isnan(nse_seasonal(flat + 0.1, flat))

    def test_all_nan_returns_nan(self) -> None:
        nans = np.full(TWO_SEASONS, np.nan)
        assert np.isnan(nse_seasonal(nans, nans))

    def test_empty_series_returns_nan(self) -> None:
        assert np.isnan(nse_seasonal(np.empty(0), np.empty(0)))

    def test_nans_shorten_the_series_below_two_cycles(self) -> None:
        """Alignment drops pairs first, so a gappy chronicle can fall under the floor."""
        _, observed = _seasonal_pair(TWO_SEASONS, SEASON)
        gappy = observed.copy()
        gappy[:1] = np.nan
        assert np.isnan(nse_seasonal(gappy, observed))

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            nse_seasonal(np.zeros(TWO_SEASONS), np.zeros(TWO_SEASONS + 1))


# ---------------------------------------------------------------------------
# reservoir: the equally weighted composite
# ---------------------------------------------------------------------------


class TestReservoirComposite:
    def test_perfect_fit_is_one(self) -> None:
        _, observed = _daily_reservoir(0.0)
        assert METRICS["reservoir"](observed, observed) == pytest.approx(1.0)

    def test_known_value_splits_the_two_halves_evenly(self) -> None:
        offset = 0.2
        simulated, observed = _daily_reservoir(offset)
        denominator = _residual_energy(TWO_SEASONS, RESIDUAL_AMPLITUDE)  # 0.16 * 365
        numerator = TWO_SEASONS * offset**2  # 730 * 0.04
        assert denominator == pytest.approx(58.4)
        assert numerator == pytest.approx(29.2)

        seasonal = nse_seasonal(simulated, observed)
        increments = nse_delta(simulated, observed, step=RESERVOIR_INCREMENT_STEP)
        # A constant offset leaves every increment untouched, so only the
        # seasonal half is degraded: 1 - 29.2 / 58.4 = 0.5.
        assert seasonal == pytest.approx(0.5)
        assert increments == pytest.approx(1.0)
        assert METRICS["reservoir"](simulated, observed) == pytest.approx(0.75)
        assert METRICS["reservoir"](simulated, observed) == pytest.approx(
            0.5 * seasonal + 0.5 * increments
        )

    def test_it_differences_over_the_declared_step(self) -> None:
        """Scoring day-to-day increments instead would drop the composite by > 1."""
        assert RESERVOIR_INCREMENT_STEP == 10
        days = np.arange(TWO_SEASONS, dtype=float)
        observed = (
            100.0
            + 5.0 * np.cos(2.0 * np.pi * days / SEASON)
            + 0.5 * np.sin(2.0 * np.pi * days / 10.0)
        )
        simulated = np.concatenate([observed[:3], observed[:-3]])

        seasonal = nse_seasonal(simulated, observed)
        declared = 0.5 * seasonal + 0.5 * nse_delta(
            simulated, observed, step=RESERVOIR_INCREMENT_STEP
        )
        daily = 0.5 * seasonal + 0.5 * nse_delta(simulated, observed, step=1)
        assert METRICS["reservoir"](simulated, observed) == pytest.approx(declared)
        assert declared - daily > 1.0

    def test_a_series_shorter_than_two_seasons_returns_nan(self) -> None:
        _, observed = _daily_reservoir(0.0)
        assert np.isnan(METRICS["reservoir"](observed[:100], observed[:100]))

    def test_constant_increments_return_nan(self) -> None:
        ramp = np.arange(TWO_SEASONS, dtype=float) * 2.0
        assert np.isnan(nse_delta(ramp, ramp, step=RESERVOIR_INCREMENT_STEP))
        assert np.isnan(METRICS["reservoir"](ramp, ramp))

    def test_all_nan_returns_nan(self) -> None:
        nans = np.full(TWO_SEASONS, np.nan)
        assert np.isnan(METRICS["reservoir"](nans, nans))


# ---------------------------------------------------------------------------
# Calibration seams: registry, scalar score, objective blocks
# ---------------------------------------------------------------------------


class TestCalibrationWiring:
    @pytest.mark.parametrize("metric", ["nse_delta", "nse_seasonal", "reservoir"])
    def test_metrics_are_registered_as_higher_is_better(self, metric: str) -> None:
        assert metric in METRICS
        assert metric in HIGHER_IS_BETTER

    def test_scalar_objective_turns_the_score_into_a_cost(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        times = np.arange(TWO_SEASONS, dtype=float)
        objective = ScalarObjective(
            ObservationSet(
                stations=("lac0",),
                times=times,
                values={"lac0": observed},
                variable="lake_level",
            ),
            metric="reservoir",
        )
        value = objective.evaluate(
            SimulationOutput(
                sim_id="sim-test",
                stations=("lac0",),
                times=times,
                values={"lac0": simulated},
            )
        )
        assert value.total == pytest.approx(1.0 - 0.75)
        assert value.components["cost:reservoir@lac0"] == pytest.approx(0.25)

    def test_score_helper_returns_the_flipped_cost(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        index = pd.date_range("2001-01-01", periods=TWO_SEASONS, freq="D")
        cost = score(
            pd.Series(observed, index=index), pd.Series(simulated, index=index), "reservoir"
        )
        assert cost == pytest.approx(0.25)

    def test_score_helper_rejects_a_chronicle_too_short_to_score(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        index = pd.date_range("2001-01-01", periods=100, freq="D")
        with pytest.raises(ValueError, match="non-finite"):
            score(
                pd.Series(observed[:100], index=index),
                pd.Series(simulated[:100], index=index),
                "reservoir",
            )

    def test_objective_block_costs_infinity_when_the_metric_is_undefined(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        block = ConfigBlockObjective(
            name="lake",
            metric="reservoir",
            uses_outputs=["lake"],
            observed_by_output={"lake": observed[:100].tolist()},
        )
        value = block.evaluate({"lake": simulated[:100].tolist()})
        assert value.total == float("inf")
        assert value.components["lake.raw_cost"] == float("inf")

    def test_objective_block_scores_a_full_chronicle(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        block = ConfigBlockObjective(
            name="lake",
            metric="reservoir",
            uses_outputs=["lake"],
            observed_by_output={"lake": observed.tolist()},
        )
        assert block.evaluate({"lake": simulated.tolist()}).total == pytest.approx(0.25)
