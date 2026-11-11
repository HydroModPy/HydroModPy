"""Tests of `criteria.series`."""

from __future__ import annotations

import datetime
from typing import get_args

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibrationConfig,
    MetricKind,
    OutputSupport,
)
from hydromodpy.calibration.criteria import (
    NETWORK_ESTIMATORS,
    HydrographicNetworkDistance,
    available_criteria,
    criterion_for,
)
from hydromodpy.calibration.criteria import SeriesCriterion as SeriesCriterion__criterion_contract
from hydromodpy.calibration.criteria.base import CriterionResult
from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    distance_gap,
    distance_mean,
    distance_pair,
    distance_pairs,
)
from hydromodpy.calibration.criteria.series import (
    HIGHER_IS_BETTER,
    METRICS,
    RESERVOIR_INCREMENT_DAYS,
    SeriesCriterion,
    _positions,
)
from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer, sampling_step_days
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.optim.objective import ConfigBlockObjective, SimulationOutput
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.scoring import metrics as core
from hydromodpy.core.scoring.metric_table import METRIC_SENSE, METRIC_SPECS
from hydromodpy.core.scoring.metrics import (
    clip_negatives,
    kge,
    kge_delta,
    log_floor,
    log_nse,
    nse,
    nse_delta,
    nse_seasonal,
)
from hydromodpy.results.derive.time_alignment import align_observed_simulated
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.record.checks import Validity
from hydromodpy.results.score import score_timeseries
from tests._helpers.tolerances import tol
from tests.unit.calibration._factories import _score

# From test_an_efficiency_over_several_outputs_is_refused.py
# An efficiency is one number per station, and the costs are averaged.
#
# A block over several outputs concatenates them and computes one metric on the
# pool. For an error (rmse, mae) the pool is a fair summary. For an efficiency
# (nse, kge, ...) it is not: the observed variance of the pool is dominated by the
# differences between stations, so a station that is badly simulated hides behind
# the spread between the others. A probe gave a pooled cost of 0.006 against 0.82
# once averaged per station.
#
# A metric that rises with the fit therefore takes one output per block. Writing
# one block per output, each with its weight, averages the costs per station.


EFFICIENCIES = sorted(name for name in METRICS if METRIC_SENSE.get(name) == "max")
POOLABLE = sorted(name for name in METRICS if METRIC_SENSE.get(name) == "min")


def _config(blocks: list[dict[str, object]]) -> dict[str, object]:
    series = {"variable": "discharge", "support": "boundary", "observed_values": [1.0, 2.0, 3.0]}
    return {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "upstream": {**series, "boundary_id": "up"},
            "downstream": {**series, "boundary_id": "down"},
        },
        "objective_blocks": blocks,
    }


def _block(metric: str, outputs: list[str], **extra: object) -> dict[str, object]:
    return {"name": "stations", "metric": metric, "uses_outputs": outputs, **extra}


def test_the_efficiencies_are_found_in_the_metric_table() -> None:
    assert {"nse", "nse_log", "kge"} <= set(EFFICIENCIES)
    assert {"rmse", "mae"} <= set(POOLABLE)


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_an_efficiency_over_two_outputs_is_refused(metric: str) -> None:
    with pytest.raises(ValidationError) as caught:
        CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream", "downstream"]))

    message = str(caught.value)
    assert "stations" in message
    assert "upstream" in message and "downstream" in message
    assert "one block per output" in message


def test_the_refusal_reaches_a_whole_calibration_file() -> None:
    blocks = [_block("nse", ["upstream", "downstream"])]

    with pytest.raises(ValidationError, match="one block per output"):
        CalibrationConfig.model_validate(_config(blocks))


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_one_block_per_output_is_accepted_with_its_weight(metric: str) -> None:
    blocks = [
        {"name": "up", "metric": metric, "uses_outputs": ["upstream"], "weight": 2.0},
        {"name": "down", "metric": metric, "uses_outputs": ["downstream"], "weight": 1.0},
    ]

    config = CalibrationConfig.model_validate(_config(blocks))

    assert [b.weight for b in config.objective_blocks] == [2.0, 1.0]


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_an_efficiency_over_one_output_is_accepted(metric: str) -> None:
    decl = CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream"]))

    assert decl.uses_outputs == ["upstream"]


@pytest.mark.parametrize("metric", POOLABLE)
def test_an_error_over_several_outputs_stays_pooled(metric: str) -> None:
    decl = CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream", "downstream"]))

    assert decl.uses_outputs == ["upstream", "downstream"]


# From test_metric_kind_matches_the_registry.py
# Every metric the engine can compute must be selectable from a TOML.
#
# ``MetricKind`` is cut from the table of ``core.scoring.metric_table``, and
# ``tests/unit/core/scoring/test_metric_table.py`` holds it equal to the keys of
# ``METRICS``. The tests below hold the direction and the documentation.


def test_every_metric_declares_its_direction() -> None:
    """A metric the engine cannot orient would be minimized the wrong way."""
    assert HIGHER_IS_BETTER <= set(METRICS)


def test_every_selectable_metric_is_documented() -> None:
    """The generated reference page explains each value it offers."""

    extra = CalibObjectiveBlockDecl.model_fields["metric"].json_schema_extra
    assert isinstance(extra, dict)
    value_docs = extra["value_docs"]
    assert isinstance(value_docs, dict)
    assert set(value_docs) == set(get_args(MetricKind))


# From test_one_epsilon_rule_serves_every_nse_log.py
# One rule gives the epsilon of nse_log, and the figures and prototypes call it.
#
# The rule (the larger of 1e-9 and one percent of the median positive
# observation) was written three times. ``log_floor`` is the one copy.


def test_the_floor_is_one_percent_of_the_median_positive_observation() -> None:
    assert log_floor([0.0, 2.0, 4.0, np.nan, 100.0]) == pytest.approx(0.04)


def test_the_floor_never_drops_below_the_absolute_minimum() -> None:
    assert log_floor([0.0, 1e-12]) == 1e-9
    assert log_floor([0.0, 0.0]) == pytest.approx(0.01)
    assert log_floor([]) == pytest.approx(0.01)


def test_log_nse_defaults_to_the_floor_of_the_scored_pairs() -> None:
    sim = np.array([1.0, 2.0, 3.0, np.nan, 5.0])
    obs = np.array([1.2, 1.9, 3.3, 900.0, 4.6])

    explicit = log_nse(sim, obs, eps=log_floor(obs[np.isfinite(sim)]))

    assert log_nse(sim, obs) == pytest.approx(explicit)


# From test_reservoir_metrics.py
# Unit tests for the impounded-level calibration metrics.
#
# Covers the efficiencies added to calibrate a reservoir stage - ``nse_seasonal``
# (efficiency against the seasonal cycle instead of the flat mean), ``nse_delta``
# and ``kge_delta`` (efficiency on the increments) - the ``reservoir`` composite
# that pairs the first two, and the calibration seams that expose them.
#
# Expected values are derived, not fitted. The seasonal benchmark is a
# least-squares fit of the mean plus the first two harmonics, so a residual built
# on the THIRD harmonic is orthogonal to that design over a whole number of
# cycles: the benchmark is exactly the harmonic part, the denominator is exactly
# the residual energy, and the score follows in closed form.


SEASON = 365

TWO_SEASONS = 2 * SEASON

RESIDUAL_AMPLITUDE = 0.4


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
        """The rationale for ``RESERVOIR_INCREMENT_DAYS``: 3 days must not flip signs."""
        days = np.arange(TWO_SEASONS, dtype=float)
        stage = (
            100.0
            + 5.0 * np.cos(2.0 * np.pi * days / SEASON)
            + 0.5 * np.sin(2.0 * np.pi * days / 10.0)
        )
        lagged = np.concatenate([stage[:3], stage[:-3]])

        assert nse_delta(lagged, stage, step=1) < 0.0
        assert nse_delta(lagged, stage, step=int(RESERVOIR_INCREMENT_DAYS)) > 0.9

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
        increments = nse_delta(simulated, observed, step=int(RESERVOIR_INCREMENT_DAYS))
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
        assert RESERVOIR_INCREMENT_DAYS == 10.0
        days = np.arange(TWO_SEASONS, dtype=float)
        observed = (
            100.0
            + 5.0 * np.cos(2.0 * np.pi * days / SEASON)
            + 0.5 * np.sin(2.0 * np.pi * days / 10.0)
        )
        simulated = np.concatenate([observed[:3], observed[:-3]])

        seasonal = nse_seasonal(simulated, observed)
        declared = 0.5 * seasonal + 0.5 * nse_delta(
            simulated, observed, step=int(RESERVOIR_INCREMENT_DAYS)
        )
        daily = 0.5 * seasonal + 0.5 * nse_delta(simulated, observed, step=1)
        assert METRICS["reservoir"](simulated, observed) == pytest.approx(declared)
        assert declared - daily > 1.0

    def test_a_series_shorter_than_two_seasons_returns_nan(self) -> None:
        _, observed = _daily_reservoir(0.0)
        assert np.isnan(METRICS["reservoir"](observed[:100], observed[:100]))

    def test_constant_increments_return_nan(self) -> None:
        ramp = np.arange(TWO_SEASONS, dtype=float) * 2.0
        assert np.isnan(nse_delta(ramp, ramp, step=int(RESERVOIR_INCREMENT_DAYS)))
        assert np.isnan(METRICS["reservoir"](ramp, ramp))

    def test_all_nan_returns_nan(self) -> None:
        nans = np.full(TWO_SEASONS, np.nan)
        assert np.isnan(METRICS["reservoir"](nans, nans))


# ---------------------------------------------------------------------------
# Calibration seams: registry, variable + objective, objective blocks
# ---------------------------------------------------------------------------
def _lake_cost(observed: np.ndarray, simulated: np.ndarray, index: pd.DatetimeIndex) -> float:
    """Score a lake stage on ``reservoir`` as ``variable = "lake_level"`` does."""
    scorer = StationBlockScorer(
        "lake_level",
        "reservoir",
        [ObservedSeries("lac0", "lake_level", pd.Series(observed, index))],
    )
    cost, _ = scorer.score({"lac0": ObservableResult("lac0", simulated, "m", index)})
    return cost


class TestCalibrationWiring:
    @pytest.mark.parametrize("metric", ["nse_delta", "nse_seasonal", "reservoir"])
    def test_metrics_are_registered_as_higher_is_better(self, metric: str) -> None:
        assert metric in METRICS
        assert metric in HIGHER_IS_BETTER

    def test_a_block_turns_the_score_into_a_cost(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        block = ConfigBlockObjective(
            name="lake",
            metric="reservoir",
            uses_outputs=["lac0"],
            observed_by_output={"lac0": observed},
        )
        value = block.evaluate({"lac0": simulated})
        assert value.total == pytest.approx(1.0 - 0.75)
        assert value.components["lake.raw_cost"] == pytest.approx(0.25)

    def test_a_lake_level_route_returns_the_flipped_cost(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        index = pd.date_range("2001-01-01", periods=TWO_SEASONS, freq="D")
        # A reservoir stage is the state AT its stamp, so the stage simulated
        # at an instant pairs with the reading taken at that same instant, as
        # the lake_level route scores it. A period mean would pair it with the
        # reading of the day before.
        cost = _lake_cost(observed, simulated, index)
        # The dated series reads a year of 365.25 days, as the block route
        # does; the fixture cycles on 365 samples, hence the tolerance.
        assert cost == pytest.approx(0.25, abs=1e-2)

    def test_a_chronicle_too_short_to_score_costs_infinity(self) -> None:
        simulated, observed = _daily_reservoir(0.2)
        index = pd.date_range("2001-01-01", periods=100, freq="D")
        assert _lake_cost(observed[:100], simulated[:100], index) == float("inf")

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


class TestTheSeasonalCycleIsCountedInDays:
    """A monthly series holds a year in twelve samples, not 365."""

    @staticmethod
    def _monthly(years: int) -> tuple[np.ndarray, np.ndarray]:
        months = np.arange(12 * years, dtype=float)
        obs = 10.0 + 3.0 * np.cos(2.0 * np.pi * months / 12.0) + 0.5 * np.sin(months)
        sim = obs + 0.2 * np.cos(3.0 * months)
        return sim, obs

    @pytest.mark.parametrize("metric", ["nse_seasonal", "reservoir"])
    def test_a_monthly_series_scores_a_number(self, metric: str) -> None:
        sim, obs = self._monthly(4)
        criterion = SeriesCriterion(metric, METRICS[metric])

        undated = criterion.score(sim, obs)
        dated = criterion.score(sim, obs, sample_days=30.44)

        assert np.isnan(undated.diagnostics["score"])
        assert np.isfinite(dated.diagnostics["score"])

    @pytest.mark.parametrize(
        ("times_days", "sample_days", "expected"),
        [
            (None, None, None),
            ([5.0, 35.0, 65.0, 125.0], None, [0.0, 1.0, 2.0, 4.0]),
            ([5.0, 35.0, 65.0], 15.0, [0.0, 2.0, 4.0]),
            ([5.0, 5.0], None, None),
            ([], 1.0, []),
        ],
        ids=["no-dates", "median-spacing", "given-step", "no-spacing", "empty"],
    )
    def test_dates_become_positions_in_steps_of_the_series(
        self, times_days, sample_days, expected
    ) -> None:
        positions = _positions(times_days, sample_days)

        if expected is None:
            assert positions is None
        else:
            np.testing.assert_allclose(positions, expected)

    def test_a_daily_step_keeps_the_daily_score(self) -> None:
        days = np.arange(3 * SEASON, dtype=float)
        obs = 5.0 + np.cos(2.0 * np.pi * days / SEASON) + 0.1 * np.sin(days / 7.0)
        sim = obs + 0.05 * np.sin(days / 3.0)
        criterion = SeriesCriterion("nse_seasonal", METRICS["nse_seasonal"])

        assert criterion.score(sim, obs, sample_days=1.0).cost == pytest.approx(
            criterion.score(sim, obs).cost, abs=1e-3
        )

    def test_the_block_reads_the_step_the_trial_dated(self) -> None:
        sim, obs = self._monthly(4)
        block = ConfigBlockObjective(
            name="level",
            metric="nse_seasonal",
            uses_outputs=["stage"],
            observed_by_output={"stage": obs},
        )
        trial = SimulationOutput(
            sim_id="",
            stations=(),
            times=np.empty(0),
            values={"stage": sim},
            metadata={"sample_days": {"stage": 30.44}},
        )

        assert np.isfinite(block.evaluate(trial).total)
        assert not np.isfinite(block.evaluate({"stage": sim}).total)


# From test_the_criterion_contract.py
# A criterion declares what it needs and returns what it found.
#
# An objective was a function ``f(sim, obs) -> float``. That fits a series and
# nothing else, so a criterion comparing two geometries disguised itself as one:
# a two-element vector standing in for a series, a vector of zeros standing in for
# observations it does not have, and a free-text component name standing in for
# "this one publishes a signed residual". Five artifacts held one shape open.
#
# The gate that matters is the last class here: every cost must come out of the
# contract bit for bit identical to the cost the inline path produced, or the
# refactor changed what is optimized.


# Long enough that the seasonal kernels return a number rather than NaN: they
# read a cycle out of the samples themselves.
_N = 96
_SIM = 5.0 + 3.0 * np.sin(np.arange(_N) * 2.0 * np.pi / 12.0) + 0.05 * np.arange(_N)
_OBS = 5.0 + 3.0 * np.sin((np.arange(_N) + 0.4) * 2.0 * np.pi / 12.0) + 0.04 * np.arange(_N)


def _same_number(left: float, right: float) -> bool:
    """Equality that also holds for a kernel whose cost is legitimately NaN."""
    if np.isnan(left) and np.isnan(right):
        return True
    return left == right


class TestTheRegistry:
    def test_every_kernel_is_reachable_by_name(self) -> None:
        assert set(available_criteria()) == set(METRICS)

    def test_an_unknown_name_is_refused_with_the_list(self) -> None:
        with pytest.raises(ValueError, match="Registered"):
            criterion_for("nse_squared")

    def test_a_series_kernel_yields_a_series_criterion(self) -> None:
        assert isinstance(criterion_for("nse"), SeriesCriterion__criterion_contract)

    def test_a_network_estimator_yields_the_network_criterion(self) -> None:
        assert isinstance(criterion_for("distance_gap"), HydrographicNetworkDistance)


class TestWhatASeriesCriterionDeclares:
    def test_it_fits_observations_and_carries_a_time_axis(self) -> None:
        needs = criterion_for("nse").requirements()

        assert needs.needs_observations is True
        assert needs.has_time_axis is True

    def test_no_series_criterion_publishes_a_signed_residual(self) -> None:
        for name in METRICS:
            if name in {"distance_gap", "distance_mean"}:
                continue
            assert criterion_for(name).requirements().signed is False, name

    def test_an_efficiency_score_says_its_cost_has_no_unit(self) -> None:
        needs = criterion_for("kge").requirements()

        assert needs.cost_is_dimensionless is True
        assert needs.cost_unit is None

    def test_a_residual_metric_says_its_cost_carries_one(self) -> None:
        needs = criterion_for("rmse").requirements()

        assert needs.cost_is_dimensionless is False
        assert needs.cost_unit is not None

    def test_scoring_without_observations_is_refused(self) -> None:
        with pytest.raises(ValueError, match="observations"):
            criterion_for("rmse").score(_SIM)

    def test_a_length_mismatch_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="rmse"):
            criterion_for("rmse").score(_SIM, _OBS[:3])

    def test_a_log_metric_reports_what_it_clipped(self) -> None:
        result = criterion_for("nse_log").score(np.array([-1.0, 2.0, 3.0]), _OBS[:3])

        assert result.diagnostics["n_clipped"] == 1.0


class TestWhatTheHydrographicNetworkDistanceDeclares:
    def test_it_needs_no_observations_and_has_no_time_axis(self) -> None:
        needs = criterion_for("distance_gap").requirements()

        assert needs.needs_observations is False
        assert needs.has_time_axis is False

    def test_the_gap_publishes_the_signed_residual_its_cost_is_built_from(self) -> None:
        needs = criterion_for("distance_gap").requirements()
        result = criterion_for("distance_gap").score([120.0, 100.0])

        assert needs.signed is True
        assert result.cost == pytest.approx(20.0)
        assert result.signed_residual == pytest.approx(20.0)

    def test_the_sign_survives_a_reversal(self) -> None:
        result = criterion_for("distance_gap").score([100.0, 120.0])

        assert result.cost == pytest.approx(20.0)
        assert result.signed_residual == pytest.approx(-20.0)

    def test_the_mean_publishes_none_because_its_cost_is_not_that_residual(self) -> None:
        needs = criterion_for("distance_mean").requirements()
        result = criterion_for("distance_mean").score([120.0, 100.0])

        assert needs.signed is False
        assert result.signed_residual is None
        assert result.cost == pytest.approx(110.0)

    def test_its_cost_is_in_metres(self) -> None:
        assert criterion_for("distance_gap").requirements().cost_unit == "m"

    def test_it_reports_the_pair_it_read(self) -> None:
        diagnostics = criterion_for("distance_gap").score([120.0, 100.0]).diagnostics

        assert diagnostics["D_so"] == pytest.approx(120.0)
        assert diagnostics["D_os"] == pytest.approx(100.0)

    def test_a_series_is_not_a_pair(self) -> None:
        with pytest.raises(ValueError, match="pair"):
            criterion_for("distance_gap").score([1.0, 2.0, 3.0])


class TestTheCostsAreUnchanged:
    """The gate: the contract must not move a single cost."""

    @staticmethod
    def _inline_cost(name: str) -> float:
        """Reproduce exactly what the objective did before the contract."""

        sim, obs = _SIM, _OBS
        if METRIC_SPECS[name].clips_negatives:
            sim, obs, _ = clip_negatives(sim, obs)
        raw = float(METRICS[name](sim, obs))
        return (1.0 - raw) if name in HIGHER_IS_BETTER else raw

    @pytest.mark.parametrize("name", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
    def test_a_series_cost_is_identical_to_the_bit(self, name: str) -> None:
        through_contract = criterion_for(name).score(_SIM, _OBS).cost

        assert _same_number(through_contract, self._inline_cost(name))

    @pytest.mark.parametrize("name", ["distance_gap", "distance_mean"])
    def test_a_network_cost_is_identical_to_the_bit(self, name: str) -> None:
        pair = np.array([137.5, 91.25])

        assert _same_number(criterion_for(name).score(pair).cost, float(METRICS[name](pair)))


class TestWhatSupportACriterionReads:
    """The criterion names the supports it scores, and nothing else holds a list.

    The pairing used to be a tuple of metric names written inside a
    configuration validator. Declared on the criterion, it is checked in both
    directions from one answer, and these gates keep that answer honest against
    the vocabulary a file actually writes.
    """

    def test_a_series_criterion_reads_every_support_but_the_network(self) -> None:
        assert set(criterion_for("nse").requirements().reads_supports) == {
            "point",
            "boundary",
            "cell",
            "lake",
        }

    def test_the_network_criterion_reads_the_network_and_nothing_else(self) -> None:
        for name in NETWORK_ESTIMATORS:
            assert criterion_for(name).requirements().reads_supports == ("network",)

    def test_the_two_vocabularies_partition_what_a_file_may_declare(self) -> None:
        # A support no criterion reads could be declared and never scored; a
        # support two families both claim would make the pairing meaningless.
        declared = set(get_args(OutputSupport))
        series = set(criterion_for("rmse").requirements().reads_supports)
        network = set(criterion_for("distance_gap").requirements().reads_supports)

        assert series | network == declared
        assert series & network == set()

    def test_every_registered_criterion_names_a_support_that_exists(self) -> None:
        declared = set(get_args(OutputSupport))
        for name in available_criteria():
            supports = criterion_for(name).requirements().reads_supports
            assert supports, name
            assert set(supports) <= declared, name


# From test_the_seasonal_kernels_read_the_dates.py
# ``nse_seasonal`` and the increment scores read the dates, not the position.
#
# The pairing drops the dates where the record has no value. The kernels took
# the position in the vector for the time, so past a gap the harmonics were
# fitted out of phase and an increment spanned the gap as one step. Four years
# of daily stage with 120 days missing: ``nse_seasonal`` went from 0.31 to 0.98,
# ``nse_delta`` from 0.48 to 0.95.


YEAR = 365.25
DAYS = np.arange(4 * 365, dtype=float)
KEPT = (DAYS < 400) | (DAYS >= 520)


def _stage() -> tuple[np.ndarray, np.ndarray]:
    obs = (
        10.0
        + 3.0 * np.cos(2.0 * np.pi * DAYS / YEAR)
        + np.sin(4.0 * np.pi * DAYS / YEAR)
        + 0.5 * np.sin(DAYS / 9.0)
    )
    sim = obs + 0.3 * np.sin(DAYS / 5.0) + 0.2
    return sim, obs


def test_a_gap_keeps_the_seasonal_score_of_the_whole_record() -> None:
    sim, obs = _stage()
    whole = nse_seasonal(sim, obs, period=YEAR)

    gapped = nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])

    assert gapped == pytest.approx(whole, abs=0.02)


def test_a_nan_left_in_place_is_a_gap() -> None:
    sim, obs = _stage()
    holed = obs.copy()
    holed[~KEPT] = np.nan

    assert nse_seasonal(sim, holed, period=YEAR) == pytest.approx(
        nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])
    )


def test_an_increment_never_spans_a_gap() -> None:
    sim, obs = _stage()
    before, after = DAYS[KEPT] < 400, DAYS[KEPT] >= 520
    s, o = sim[KEPT], obs[KEPT]
    d_sim = np.concatenate([np.diff(s[before]), np.diff(s[after])])
    d_obs = np.concatenate([np.diff(o[before]), np.diff(o[after])])
    expected = 1.0 - np.sum((d_sim - d_obs) ** 2) / np.sum((d_obs - d_obs.mean()) ** 2)

    assert nse_delta(s, o, times=DAYS[KEPT]) == pytest.approx(expected)
    assert kge_delta(s, o, times=DAYS[KEPT])["kge"] == pytest.approx(kge(d_sim, d_obs)["kge"])


def test_a_regular_series_scores_as_before() -> None:
    sim, obs = _stage()

    assert nse_seasonal(sim, obs, period=YEAR, times=DAYS) == nse_seasonal(sim, obs, period=YEAR)
    assert nse_delta(sim, obs, step=10, times=DAYS) == nse_delta(sim, obs, step=10)


@pytest.mark.parametrize("metric", ["nse_seasonal", "nse_delta", "reservoir"])
def test_the_criterion_reads_the_dates(metric: str) -> None:
    sim, obs = _stage()
    criterion = SeriesCriterion(metric, METRICS[metric])
    holed = obs.copy()
    holed[~KEPT] = np.nan

    dated = criterion.score(sim[KEPT], obs[KEPT], sample_days=1.0, times_days=DAYS[KEPT])

    assert dated.cost == pytest.approx(criterion.score(sim, holed, sample_days=1.0).cost)


def test_variable_and_objective_read_the_gap_the_pairing_left() -> None:
    sim, obs = _stage()
    stamps = pd.date_range("2001-01-01", periods=DAYS.size, freq="D")
    record = pd.Series(np.where(KEPT, obs, np.nan), index=stamps)

    simulated = pd.Series(sim, index=stamps)

    cost, _ = _score(record, simulated, "nse_seasonal", variable="head")

    paired = align_observed_simulated(record, simulated, method="point")
    days = paired.index.asi8 / 86_400e9
    assert days.size < DAYS.size - 100
    expected = 1.0 - nse_seasonal(paired["sim"], paired["obs"], period=YEAR, times=days)
    assert cost == pytest.approx(expected)


def test_the_block_route_reads_the_paired_dates() -> None:
    sim, obs = _stage()
    block = ConfigBlockObjective(
        name="level",
        metric="nse_seasonal",
        uses_outputs=["stage"],
        observed_by_output={"stage": obs[KEPT]},
    )
    trial = SimulationOutput(
        sim_id="",
        stations=(),
        times=np.empty(0),
        values={"stage": sim[KEPT]},
        metadata={"sample_days": {"stage": 1.0}, "sample_times": {"stage": DAYS[KEPT]}},
    )

    expected = 1.0 - nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])
    assert block.evaluate(trial).components["level.raw_cost"] == pytest.approx(expected)


# From test_the_session_cost_is_the_score_of_its_run.py
# The cost a calibration minimizes is the score its promoted run is ranked on.
#
# The same series, the same declared window: the calibration scores it while it
# searches, and the run promoted from it is scored again by
# :mod:`hydromodpy.results.score` once sealed. Nothing tied the two: the
# promotion tests use a stand-in, and the run scorer was imported by its own
# tests only.
#
# They used to disagree (N1 of the audit of 2026-10-20). The session kept the
# pairs whose END stamp fell in ``[start, end]``; the run keeps the periods
# lying wholly in the window. On a monthly run and a 2001-2002 window the
# session scored December 2000 to November 2002, the run January 2001 to
# December 2002, 24 periods each. Both now read the window through
# :func:`~hydromodpy.core.time.period_aggregation.periods_in_window`
# (decision m01), and the cost is ``1 - NSE`` of the run to
# :data:`SAME_PAIRS`.


GAUGE = "NANCON"
FIRST_PERIOD = pd.Timestamp("2000-01-01")

# Each stamp closes the month before it, as a monthly run stamps its periods.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
WINDOW = (datetime.date(2001, 1, 1), datetime.date(2002, 12, 31))

SAME_PAIRS = tol("session_cost_against_run_score__gap_of_1_cost_to_the_run_nse")


def _series() -> tuple[pd.Series, pd.Series]:
    """A monthly simulated discharge and the daily record it is judged against."""
    days = pd.date_range(FIRST_PERIOD, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    observed = pd.Series(
        1.0 + 0.6 * np.cos(2.0 * np.pi * t / 365.25) + 0.2 * np.sin(t / 17.0), index=days
    )
    monthly = observed.resample("MS").mean()
    simulated = pd.Series(
        monthly.to_numpy() * 1.15 + 0.1 * np.cos(np.arange(monthly.size)), index=STAMPS
    )
    return observed, simulated


def _run_score() -> tuple[float, int]:
    observed, simulated = _series()
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "station_id": GAUGE,
                    "variable": "discharge",
                    "source": "simulated",
                    "time": simulated.index,
                    "value": simulated.to_numpy(),
                }
            ),
            pd.DataFrame(
                {
                    "station_id": GAUGE,
                    "variable": "discharge",
                    "source": "observed",
                    "time": observed.index,
                    "value": observed.to_numpy(),
                }
            ),
        ],
        ignore_index=True,
    )
    rule = MetricRule(station=GAUGE, window=DateWindow(start=WINDOW[0], end=WINDOW[1]))
    scores = score_timeseries(frame, rule=rule, period_start=FIRST_PERIOD)
    return float(scores.score.value), int(scores.score.n_samples)


def _bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(WINDOW[0]), pd.Timestamp(WINDOW[1])


def test_the_run_scores_the_window_on_whole_periods() -> None:
    value, n = _run_score()

    assert np.isfinite(value)
    assert n == 24


def test_variable_and_objective_score_what_the_run_scores() -> None:
    observed, simulated = _series()
    scorer = StationBlockScorer(
        "discharge", "nse", [ObservedSeries(GAUGE, "discharge", observed)], window=_bounds()
    )

    cost, _ = scorer.score(
        {GAUGE: ObservableResult(GAUGE, simulated.to_numpy(), "m3/s", STAMPS)},
        boundaries=[FIRST_PERIOD, *STAMPS],
    )

    value, _ = _run_score()
    assert 1.0 - cost == pytest.approx(value, abs=SAME_PAIRS)


def test_the_block_route_scores_what_the_run_scores() -> None:
    observed, simulated = _series()
    paired = pair_outputs_with_observations(
        observed={"hydrograph": observed},
        simulated={"hydrograph": simulated},
        window=_bounds(),
        time_methods={"hydrograph": "mean"},
        period_starts={"hydrograph": FIRST_PERIOD},
    )

    result = SeriesCriterion("nse", METRICS["nse"]).score(
        paired.simulated["hydrograph"], paired.observed["hydrograph"]
    )

    value, n = _run_score()
    assert paired.n_paired["hydrograph"] == n
    assert 1.0 - result.cost == pytest.approx(value, abs=SAME_PAIRS)


# From test_variable_and_objective_read_the_sampling_step.py
# ``variable`` + ``objective`` hands the sampling step to the seasonal kernels.
#
# ``nse_seasonal`` and ``reservoir`` count one year and ten days in samples of
# the series. The block route reads the step from the trial's dates. The
# one-line form used to pass none, so a monthly series was taken as daily: NaN
# on three years, and a refused trial. It is now scored by implicit blocks, and
# reads the step as any block does.


STAMPS__variable_objective = pd.date_range("2001-01-31", periods=36, freq="ME")
STEP_DAYS = float(np.median(np.diff(STAMPS__variable_objective.asi8) / 86_400e9))


def _cost(observed: pd.Series, simulated: pd.Series, metric: str) -> float:
    scorer = StationBlockScorer("head", metric, [ObservedSeries("PZ", "head", observed)])
    cost, _ = scorer.score(
        {"PZ": ObservableResult("PZ", simulated.to_numpy(), "m", simulated.index)}
    )
    return cost


def _monthly() -> tuple[pd.Series, pd.Series]:
    months = np.arange(STAMPS__variable_objective.size, dtype=float)
    obs = 10.0 + 3.0 * np.cos(2.0 * np.pi * months / 12.0) + 0.5 * np.sin(months)
    sim = obs + 0.2 * np.cos(3.0 * months)
    return pd.Series(obs, index=STAMPS__variable_objective), pd.Series(
        sim, index=STAMPS__variable_objective
    )


@pytest.mark.parametrize("metric", ["nse_seasonal", "reservoir"])
def test_a_monthly_series_scores_as_on_the_block_route(metric: str) -> None:
    observed, simulated = _monthly()

    cost = _cost(observed, simulated, metric)

    block = SeriesCriterion(metric, METRICS[metric]).score(
        simulated.to_numpy(),
        observed.to_numpy(),
        sample_days=STEP_DAYS,
        times_days=STAMPS__variable_objective.asi8 / 86_400e9,
    )
    assert np.isfinite(cost)
    assert cost == pytest.approx(block.cost)


def test_a_daily_series_keeps_its_daily_score() -> None:
    stamps = pd.date_range("2001-01-01", periods=3 * 365, freq="D")
    days = np.arange(stamps.size, dtype=float)
    obs = pd.Series(
        5.0 + np.cos(2.0 * np.pi * days / 365.25) + 0.1 * np.sin(days / 7.0), index=stamps
    )
    sim = obs + 0.05 * np.sin(days / 3.0)

    cost = _cost(obs, sim, "nse_seasonal")

    undated = SeriesCriterion("nse_seasonal", METRICS["nse_seasonal"]).score(
        sim.to_numpy(), obs.to_numpy()
    )
    assert cost == pytest.approx(undated.cost, abs=1e-3)


def test_the_step_is_the_median_spacing_in_days() -> None:
    assert sampling_step_days(pd.date_range("2001-01-01", periods=5, freq="D")) == 1.0
    assert sampling_step_days(pd.DatetimeIndex(["2001-01-01"])) is None
    assert sampling_step_days(pd.RangeIndex(4)) is None


# ---------------------------------------------------------------------------
# criteria_formulas
# Tests of `criteria.formulas`.
# ---------------------------------------------------------------------------

# From test_kge_is_written_as_the_2009_form.py
# The KGE of HydroModPy is the 2009 form, and every place that describes it says so.
#
# Every KGE here (``kge``, ``kge_r``, ``kge_alpha``, ``kge_beta``) uses
# ``beta = sum(s) / sum(o)`` and ``alpha = std(s) / std(o)`` (Gupta et al., 2009).
# The 2012 form (``alpha`` as a ratio of coefficients of variation) gives another
# number on the same series, 0.9207 against 0.8821 on the audit probe (N13 of the
# audit of 2026-10-20, decision m14), and nothing said which one was meant.


def test_the_kernel_is_the_2009_form() -> None:
    obs = np.array([5.0, 3.0, 2.0, 1.2, 0.8, 0.5, 0.3, 0.2, 0.15, 0.1])
    sim = obs * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])

    parts = core.kge(sim, obs)

    assert parts["beta"] == pytest.approx(sim.sum() / obs.sum())
    assert parts["alpha"] == pytest.approx(sim.std() / obs.std())
    cv_ratio = (sim.std() / sim.mean()) / (obs.std() / obs.mean())
    assert parts["alpha"] != pytest.approx(cv_ratio)


def test_the_formula_of_the_registry_says_kge_2009() -> None:
    formula = METRIC_FORMULAS["kge"]

    assert "2009" in formula.note
    assert "2012" in formula.note


# ---------------------------------------------------------------------------
# criteria_hydrographic_network_distance
# Tests of `criteria.hydrographic_network_distance`.
# ---------------------------------------------------------------------------

# From test_network_criterion_reads_one_pair_per_bound.py
# The network criterion reads one ``(D_so, D_os)`` pair per bound in the cost.


def test_one_pair_keeps_its_signed_residual() -> None:
    scored = criterion_for("distance_gap").score([130.0, 100.0])
    assert scored.cost == pytest.approx(30.0)
    assert scored.signed_residual == pytest.approx(30.0)
    assert scored.diagnostics["J_signed"] == pytest.approx(30.0)


def test_two_weighted_pairs_sum_their_gaps_and_carry_no_single_residual() -> None:
    # 0.25 * (D_so, D_os) = 0.25 * (140, 100) and 0.75 * (80, 100).
    values = [35.0, 25.0, 60.0, 75.0]
    scored = criterion_for("distance_gap").score(values)
    assert scored.cost == pytest.approx(0.25 * 40.0 + 0.75 * 20.0)
    assert scored.signed_residual is None
    assert scored.diagnostics["weighted_J_signed_1"] == pytest.approx(-15.0)


def test_the_mean_estimator_sums_the_weighted_doptim() -> None:
    assert distance_mean([35.0, 25.0, 60.0, 75.0]) == pytest.approx(30.0 + 67.5)
    assert criterion_for("distance_mean").score([35.0, 25.0, 60.0, 75.0]).signed_residual is None


def test_a_negative_distance_makes_the_mean_undefined() -> None:
    assert np.isnan(distance_mean([-1.0, 5.0]))


def test_the_kernels_agree_with_the_criterion() -> None:
    values = [35.0, 25.0, 60.0, 75.0]
    assert distance_gap(values) == pytest.approx(criterion_for("distance_gap").score(values).cost)
    assert distance_pairs(values) == [(35.0, 25.0), (60.0, 75.0)]


@pytest.mark.parametrize("values", [[], [1.0], [1.0, 2.0, 3.0]])
def test_a_vector_that_is_not_made_of_pairs_is_refused(values) -> None:
    with pytest.raises(ValueError, match="pairs"):
        distance_gap(values)


def test_distance_pair_reads_one_pair_and_refuses_any_other_size() -> None:
    assert distance_pair(np.array([[35.0], [25.0]])) == (35.0, 25.0)
    with pytest.raises(ValueError, match="got 4 value"):
        distance_pair([1.0, 2.0, 3.0, 4.0])


@pytest.mark.parametrize(
    ("validity", "fatal"),
    [
        ((), False),
        ((Validity("a", True, None, "ok", fatal=True),), False),
        ((Validity("a", False, None, "coarse"),), False),
        ((Validity("a", True, None, "ok"), Validity("b", False, 1.0, "fiction", fatal=True)), True),
    ],
    ids=["no-check", "fatal-but-passed", "failed-but-not-fatal", "failed-and-fatal"],
)
def test_a_result_is_fatally_invalid_only_by_a_failed_fatal_check(validity, fatal) -> None:
    assert CriterionResult(cost=1.0, validity=validity).is_fatally_invalid is fatal


def test_an_unknown_estimator_is_refused_with_the_two_it_knows() -> None:
    with pytest.raises(ValueError, match="'distance_gap' .*'distance_mean'"):
        HydrographicNetworkDistance("distance_median")
