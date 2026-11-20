"""Criteria that score a simulated series against observations, and the metrics they use.

Covers the series criteria (nse, kge, nse_seasonal, nse_delta, reservoir), the network
distance criterion, the objective-block refusals and the match between the cost of a
search and the score of its run. Costs are dimensionless unless stated, stages are in m.
"""

from __future__ import annotations

import datetime
from typing import get_args

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl
from hydromodpy.calibration.config_terms import MetricKind
from hydromodpy.calibration.criteria.base import CriterionResult
from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    HydrographicNetworkDistance,
    distance_gap,
    distance_mean,
    distance_pair,
    distance_pairs,
)
from hydromodpy.calibration.criteria.registry import criterion_for
from hydromodpy.calibration.criteria.series import (
    HIGHER_IS_BETTER,
    METRICS,
    RESERVOIR_INCREMENT_DAYS,
    SeriesCriterion,
    _positions,
)
from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer
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


def test_efficiencies_come_from_metric_table() -> None:
    assert {"nse", "nse_log", "kge"} <= set(EFFICIENCIES)
    assert {"rmse", "mae"} <= set(POOLABLE)


@pytest.mark.parametrize("metric", EFFICIENCIES)
def test_efficiency_over_two_outputs_refused(metric: str) -> None:
    with pytest.raises(ValidationError) as caught:
        CalibObjectiveBlockDecl.model_validate(_block(metric, ["upstream", "downstream"]))

    message = str(caught.value)
    assert "stations" in message
    assert "upstream" in message and "downstream" in message
    assert "one block per output" in message


def test_refusal_reaches_calibration_file() -> None:
    blocks = [_block("nse", ["upstream", "downstream"])]

    with pytest.raises(ValidationError, match="one block per output"):
        CalibrationConfig.model_validate(_config(blocks))


def test_every_metric_has_a_direction() -> None:
    # A metric the engine cannot orient would be minimized the wrong way.
    assert HIGHER_IS_BETTER <= set(METRICS)


@pytest.mark.parametrize("metric", ["nse_delta", "nse_seasonal", "reservoir"])
def test_metric_is_higher_is_better(metric: str) -> None:
    assert metric in METRICS
    assert metric in HIGHER_IS_BETTER


def test_every_metric_is_documented() -> None:
    extra = CalibObjectiveBlockDecl.model_fields["metric"].json_schema_extra
    assert isinstance(extra, dict)
    value_docs = extra["value_docs"]
    assert isinstance(value_docs, dict)
    assert set(value_docs) == set(get_args(MetricKind))


# The floor is 1 % of the median positive observation, never below 1e-9, and 0.01 without data.
LOG_FLOORS = [
    pytest.param([0.0, 2.0, 4.0, np.nan, 100.0], 0.04, id="median of positives"),
    pytest.param([0.0, 1e-12], 1e-9, id="absolute minimum"),
    pytest.param([0.0, 0.0], 0.01, id="no positive"),
    pytest.param([], 0.01, id="empty"),
]


@pytest.mark.parametrize(("observed", "floor"), LOG_FLOORS)
def test_log_floor(observed, floor) -> None:
    assert log_floor(observed) == pytest.approx(floor, rel=1e-12)


def test_log_nse_default_floor() -> None:
    sim = np.array([1.0, 2.0, 3.0, np.nan, 5.0])
    obs = np.array([1.2, 1.9, 3.3, 900.0, 4.6])

    explicit = log_nse(sim, obs, eps=log_floor(obs[np.isfinite(sim)]))

    assert log_nse(sim, obs) == pytest.approx(explicit)


SEASON = 365
TWO_SEASONS = 2 * SEASON
RESIDUAL_AMPLITUDE = 0.4


def _seasonal_pair(
    n: int, period: int, *, amplitude: float = 0.5, start: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Return (benchmark, observed), observed = benchmark + a 3rd harmonic of given amplitude."""
    theta = 2.0 * np.pi * (np.arange(n, dtype=float) + float(start)) / float(period)
    benchmark = 100.0 + 5.0 * np.cos(theta) + 2.0 * np.sin(2.0 * theta)
    return benchmark, benchmark + amplitude * np.cos(3.0 * theta)


def _daily_reservoir(offset: float) -> tuple[np.ndarray, np.ndarray]:
    """Two years of daily stage (m) and the same stage shifted by a constant offset."""
    _, observed = _seasonal_pair(TWO_SEASONS, SEASON, amplitude=RESIDUAL_AMPLITUDE)
    return observed + offset, observed


# Increments of the record [0, 1, 3, 6, 10] are 1, 2, 3, 4.
STAGE = np.array([0.0, 1.0, 3.0, 6.0, 10.0])
# d_obs = [1, 2, 3], mean 2, denominator 2. d_sim = [2, 1, 2], numerator 3.
STEP_ONE_OBS = np.array([0.0, 1.0, 3.0, 6.0])
STEP_ONE_SIM = np.array([0.0, 2.0, 3.0, 5.0])
# d_obs = [3, 5, 7, 9], mean 6, denominator 20. d_sim = [4, 5, 6, 10], numerator 3.
STEP_TWO_OBS = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
STEP_TWO_SIM = np.array([0.0, 1.0, 4.0, 6.0, 10.0, 16.0])

DELTA_VALUES = [
    pytest.param(STAGE, STAGE, 1, 1.0, id="perfect fit"),
    pytest.param(STAGE + 10.0, STAGE, 1, 1.0, id="constant offset"),
    pytest.param(STEP_ONE_SIM, STEP_ONE_OBS, 1, 1.0 - 3.0 / 2.0, id="step one"),
    pytest.param(STEP_ONE_SIM, STEP_ONE_OBS, 0, 1.0 - 3.0 / 2.0, id="step below one"),
    pytest.param(STEP_TWO_SIM, STEP_TWO_OBS, 2, 1.0 - 3.0 / 20.0, id="step two"),
]


@pytest.mark.parametrize(("sim", "obs", "step", "expected"), DELTA_VALUES)
def test_nse_delta_values(sim, obs, step, expected) -> None:
    assert nse_delta(sim, obs, step=step) == pytest.approx(expected)


def test_nse_delta_blind_to_offset() -> None:
    # The increments ignore the absolute stage, while NSE does not.
    assert nse(STAGE + 10.0, STAGE) < 0.0


RAMP = np.arange(10, dtype=float) * 2.0  # a linear ramp has no increment variance
NANS = np.full(6, np.nan)
DELTA_UNDEFINED = [
    pytest.param(RAMP, RAMP, 1, id="constant increments"),
    pytest.param(
        np.arange(TWO_SEASONS) * 2.0,
        np.arange(TWO_SEASONS) * 2.0,
        int(RESERVOIR_INCREMENT_DAYS),
        id="ramp over reservoir step",
    ),
    pytest.param([0.0, 2.0, 3.0], [0.0, 1.0, 3.0], 2, id="shorter than the step window"),
    pytest.param([0.0, 2.0], [0.0, 1.0], 1, id="two samples"),
    pytest.param(NANS, NANS, 1, id="all nan"),
    pytest.param(np.zeros(6), NANS, 1, id="observations all nan"),
    pytest.param(np.empty(0), np.empty(0), 1, id="empty"),
]


@pytest.mark.parametrize(("sim", "obs", "step"), DELTA_UNDEFINED)
def test_nse_delta_undefined(sim, obs, step) -> None:
    assert np.isnan(nse_delta(np.asarray(sim), np.asarray(obs), step=step))


def test_kge_delta_nan_for_zero_sum() -> None:
    # KGE is not offered on increments: beta is a ratio of near-zero means.
    obs = np.array([0.0, 1.0, 0.0])
    assert np.isnan(kge_delta(obs, obs)["kge"])


def test_kge_delta_too_short() -> None:
    out = kge_delta(np.array([0.0, 1.0]), np.array([0.0, 2.0]))
    assert all(np.isnan(value) for value in out.values())


def test_shape_mismatch_refused() -> None:
    with pytest.raises(ValueError):
        nse_delta(np.zeros(4), np.zeros(5))
    with pytest.raises(ValueError):
        nse_seasonal(np.zeros(TWO_SEASONS), np.zeros(TWO_SEASONS + 1))


# Observed energy of the 3rd harmonic over 24 monthly samples: 0.25 * 12 = 3.0.
# A constant error of 0.1 costs 24 * 0.01 = 0.24, so the score is 1 - 0.24 / 3.0.
BENCHMARK_24, OBSERVED_24 = _seasonal_pair(24, 12)
SEASONAL_VALUES = [
    pytest.param(OBSERVED_24, OBSERVED_24, 1.0, id="perfect fit"),
    pytest.param(BENCHMARK_24, OBSERVED_24, 0.0, id="seasonal cycle only"),
    pytest.param(OBSERVED_24 + 0.1, OBSERVED_24, 0.92, id="constant error"),
]


@pytest.mark.parametrize(("sim", "obs", "expected"), SEASONAL_VALUES)
def test_nse_seasonal_values(sim, obs, expected) -> None:
    assert nse_seasonal(sim, obs, period=12) == pytest.approx(expected)


def test_seasonal_score_ignores_cut_point() -> None:
    # A harmonic fit recovers the phase, so dropping a partial warm-up is safe.
    _, from_day_five = _seasonal_pair(24, 12, start=5)
    assert nse_seasonal(from_day_five + 0.1, from_day_five, period=12) == pytest.approx(
        nse_seasonal(OBSERVED_24 + 0.1, OBSERVED_24, period=12)
    )


def test_seasonal_harsher_than_nse() -> None:
    # Observed energy: 25 * 12 (1st) + 4 * 12 (2nd) + 0.25 * 12 (3rd) = 351.
    assert nse(BENCHMARK_24, OBSERVED_24) == pytest.approx(1.0 - 3.0 / 351.0)
    assert nse_seasonal(BENCHMARK_24, OBSERVED_24, period=12) == pytest.approx(0.0)


SEASONAL_UNDEFINED = [
    pytest.param(_seasonal_pair(23, 12)[1], _seasonal_pair(23, 12)[1], 12, id="under two cycles"),
    pytest.param(np.full(TWO_SEASONS, 100.1), np.full(TWO_SEASONS, 100.0), SEASON, id="flat"),
    pytest.param(np.full(TWO_SEASONS, np.nan), np.full(TWO_SEASONS, np.nan), SEASON, id="all nan"),
    pytest.param(np.empty(0), np.empty(0), SEASON, id="empty"),
]


@pytest.mark.parametrize(("sim", "obs", "period"), SEASONAL_UNDEFINED)
def test_nse_seasonal_undefined(sim, obs, period) -> None:
    assert np.isnan(nse_seasonal(sim, obs, period=period))


def test_reservoir_perfect_fit() -> None:
    _, observed = _daily_reservoir(0.0)
    assert METRICS["reservoir"](observed, observed) == pytest.approx(1.0)


def test_reservoir_halves_split_evenly() -> None:
    simulated, observed = _daily_reservoir(0.2)
    # Residual energy: 0.4**2 / 2 * 730 = 58.4. Offset error: 730 * 0.2**2 = 29.2.
    # An offset leaves every increment untouched, so only the seasonal half drops.
    seasonal = nse_seasonal(simulated, observed)
    increments = nse_delta(simulated, observed, step=int(RESERVOIR_INCREMENT_DAYS))
    assert seasonal == pytest.approx(1.0 - 29.2 / 58.4)
    assert increments == pytest.approx(1.0)
    assert METRICS["reservoir"](simulated, observed) == pytest.approx(0.75)
    assert METRICS["reservoir"](simulated, observed) == pytest.approx(
        0.5 * seasonal + 0.5 * increments
    )


def test_reservoir_differences_over_declared_step() -> None:
    # Scoring day-to-day increments instead would drop the composite by more than 1.
    assert RESERVOIR_INCREMENT_DAYS == 10.0
    days = np.arange(TWO_SEASONS, dtype=float)
    observed = (
        100.0 + 5.0 * np.cos(2.0 * np.pi * days / SEASON) + 0.5 * np.sin(2.0 * np.pi * days / 10.0)
    )
    simulated = np.concatenate([observed[:3], observed[:-3]])

    seasonal = nse_seasonal(simulated, observed)
    declared = 0.5 * seasonal + 0.5 * nse_delta(
        simulated, observed, step=int(RESERVOIR_INCREMENT_DAYS)
    )
    daily = 0.5 * seasonal + 0.5 * nse_delta(simulated, observed, step=1)
    assert METRICS["reservoir"](simulated, observed) == pytest.approx(declared)
    assert declared - daily > 1.0


RESERVOIR_UNDEFINED = [
    pytest.param(_daily_reservoir(0.0)[1][:100], id="under two seasons"),
    pytest.param(np.arange(TWO_SEASONS, dtype=float) * 2.0, id="constant increments"),
    pytest.param(np.full(TWO_SEASONS, np.nan), id="all nan"),
]


@pytest.mark.parametrize("series", RESERVOIR_UNDEFINED)
def test_reservoir_undefined(series) -> None:
    assert np.isnan(METRICS["reservoir"](series, series))


def _lake_cost(observed: np.ndarray, simulated: np.ndarray, index: pd.DatetimeIndex) -> float:
    """Score a lake stage on ``reservoir`` as ``variable = "lake_level"`` does."""
    scorer = StationBlockScorer(
        "lake_level",
        "reservoir",
        [ObservedSeries("lac0", "lake_level", pd.Series(observed, index))],
    )
    cost, _ = scorer.score({"lac0": ObservableResult("lac0", simulated, "m", index)})
    return cost


def test_block_turns_score_into_cost() -> None:
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


def test_lake_level_route_flips_cost() -> None:
    simulated, observed = _daily_reservoir(0.2)
    index = pd.date_range("2001-01-01", periods=TWO_SEASONS, freq="D")
    # A stage is the state AT its stamp, so it pairs with the reading of that same instant.
    cost = _lake_cost(observed, simulated, index)
    # The dated series reads a year of 365.25 days and the fixture cycles on 365 samples.
    assert cost == pytest.approx(0.25, abs=1e-2)


def test_short_chronicle_costs_infinity() -> None:
    simulated, observed = _daily_reservoir(0.2)
    index = pd.date_range("2001-01-01", periods=100, freq="D")
    assert _lake_cost(observed[:100], simulated[:100], index) == float("inf")


def test_block_scores_full_chronicle() -> None:
    simulated, observed = _daily_reservoir(0.2)
    block = ConfigBlockObjective(
        name="lake",
        metric="reservoir",
        uses_outputs=["lake"],
        observed_by_output={"lake": observed.tolist()},
    )
    assert block.evaluate({"lake": simulated.tolist()}).total == pytest.approx(0.25)


# Stamps 5, 35, 65, 125 d: median spacing 30 d, so positions 0, 1, 2, 4.
POSITIONS = [
    pytest.param([5.0, 35.0, 65.0, 125.0], None, [0.0, 1.0, 2.0, 4.0], id="median spacing"),
    pytest.param([5.0, 35.0, 65.0], 15.0, [0.0, 2.0, 4.0], id="given step"),
    pytest.param([], 1.0, [], id="empty"),
]


@pytest.mark.parametrize(("times_days", "sample_days", "expected"), POSITIONS)
def test_dates_to_positions(times_days, sample_days, expected) -> None:
    np.testing.assert_allclose(_positions(times_days, sample_days), expected)


@pytest.mark.parametrize(
    ("times_days", "sample_days"),
    [pytest.param(None, None, id="no dates"), pytest.param([5.0, 5.0], None, id="no spacing")],
)
def test_no_positions(times_days, sample_days) -> None:
    assert _positions(times_days, sample_days) is None


def _daily_record(n_years: int = 3) -> tuple[pd.DatetimeIndex, pd.Series, pd.Series]:
    """Daily stamps, an observed stage (m) and a simulation 0.05 m around it."""
    stamps = pd.date_range("2001-01-01", periods=n_years * 365, freq="D")
    days = np.arange(stamps.size, dtype=float)
    obs = pd.Series(
        5.0 + np.cos(2.0 * np.pi * days / 365.25) + 0.1 * np.sin(days / 7.0), index=stamps
    )
    return stamps, obs, obs + 0.05 * np.sin(days / 3.0)


def test_daily_step_keeps_daily_score() -> None:
    _, obs, sim = _daily_record()
    criterion = SeriesCriterion("nse_seasonal", METRICS["nse_seasonal"])

    daily = criterion.score(sim.to_numpy(), obs.to_numpy(), sample_days=1.0).cost

    assert daily == pytest.approx(criterion.score(sim.to_numpy(), obs.to_numpy()).cost, abs=1e-3)


# Long enough that the seasonal kernels return a number rather than NaN.
_N = 96
_SIM = 5.0 + 3.0 * np.sin(np.arange(_N) * 2.0 * np.pi / 12.0) + 0.05 * np.arange(_N)
_OBS = 5.0 + 3.0 * np.sin((np.arange(_N) + 0.4) * 2.0 * np.pi / 12.0) + 0.04 * np.arange(_N)

CRITERION_REFUSALS = [
    pytest.param("nse_squared", (), "Registered", id="unknown name"),
    pytest.param("rmse", (_SIM,), "observations", id="no observations"),
    pytest.param("rmse", (_SIM, _OBS[:3]), "rmse", id="length mismatch"),
    pytest.param("distance_gap", ([1.0, 2.0, 3.0],), "pair", id="series is not a pair"),
]


@pytest.mark.parametrize(("name", "args", "message"), CRITERION_REFUSALS)
def test_criterion_refusals(name, args, message) -> None:
    with pytest.raises(ValueError, match=message):
        criterion_for(name).score(*args)


def test_estimator_refused_with_known_ones() -> None:
    with pytest.raises(ValueError, match="'distance_gap' .*'distance_mean'"):
        HydrographicNetworkDistance("distance_median")


def test_series_criteria_publish_no_residual() -> None:
    for name in METRICS:
        if name in {"distance_gap", "distance_mean"}:
            continue
        assert criterion_for(name).requirements().signed is False, name


def test_efficiency_cost_has_no_unit() -> None:
    needs = criterion_for("kge").requirements()

    assert needs.cost_is_dimensionless is True
    assert needs.cost_unit is None


# Values are (D_so, D_os) pairs, each pair optionally weighted by 0.25 and 0.75.
DISTANCE_GAP = [
    pytest.param([120.0, 100.0], 20.0, 20.0, id="one pair"),
    pytest.param([100.0, 120.0], 20.0, -20.0, id="reversed pair"),
    pytest.param([130.0, 100.0], 30.0, 30.0, id="gap of 30"),
    # 0.25 * |140 - 100| + 0.75 * |80 - 100|, no single residual to publish.
    pytest.param([35.0, 25.0, 60.0, 75.0], 25.0, None, id="two weighted pairs"),
]


@pytest.mark.parametrize(("values", "cost", "residual"), DISTANCE_GAP)
def test_distance_gap_cost(values, cost, residual) -> None:
    result = criterion_for("distance_gap").score(values)

    assert result.cost == pytest.approx(cost)
    if residual is None:
        assert result.signed_residual is None
    else:
        assert result.signed_residual == pytest.approx(residual)


def test_distance_gap_diagnostics() -> None:
    pair = criterion_for("distance_gap").score([120.0, 100.0]).diagnostics
    assert pair["D_so"] == pytest.approx(120.0)
    assert pair["D_os"] == pytest.approx(100.0)

    single = criterion_for("distance_gap").score([130.0, 100.0]).diagnostics
    assert single["J_signed"] == pytest.approx(30.0)

    weighted = criterion_for("distance_gap").score([35.0, 25.0, 60.0, 75.0]).diagnostics
    assert weighted["weighted_J_signed_1"] == pytest.approx(-15.0)


# The mean publishes no residual, because its cost is not a gap.
DISTANCE_MEAN = [
    pytest.param([120.0, 100.0], 110.0, id="one pair"),
    pytest.param([35.0, 25.0, 60.0, 75.0], 30.0 + 67.5, id="two weighted pairs"),
]


@pytest.mark.parametrize(("values", "cost"), DISTANCE_MEAN)
def test_distance_mean_cost(values, cost) -> None:
    result = criterion_for("distance_mean").score(values)

    assert result.cost == pytest.approx(cost)
    assert result.signed_residual is None
    assert distance_mean(values) == pytest.approx(cost)


def test_distance_signed_requirement() -> None:
    assert criterion_for("distance_gap").requirements().signed is True
    assert criterion_for("distance_mean").requirements().signed is False


def test_negative_distance_makes_mean_undefined() -> None:
    assert np.isnan(distance_mean([-1.0, 5.0]))


def test_distance_kernels_match_criterion() -> None:
    values = [35.0, 25.0, 60.0, 75.0]
    assert distance_gap(values) == pytest.approx(criterion_for("distance_gap").score(values).cost)
    assert distance_pairs(values) == [(35.0, 25.0), (60.0, 75.0)]


def test_distance_pair_refuses_other_sizes() -> None:
    assert distance_pair(np.array([[35.0], [25.0]])) == (35.0, 25.0)
    with pytest.raises(ValueError, match="got 4 value"):
        distance_pair([1.0, 2.0, 3.0, 4.0])


def _inline_cost(name: str) -> float:
    """Cost as the objective computed it before the criterion contract."""
    sim, obs = _SIM, _OBS
    if METRIC_SPECS[name].clips_negatives:
        sim, obs, _ = clip_negatives(sim, obs)
    raw = float(METRICS[name](sim, obs))
    return (1.0 - raw) if name in HIGHER_IS_BETTER else raw


@pytest.mark.parametrize("name", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
def test_series_cost_is_bit_identical(name: str) -> None:
    through_contract = criterion_for(name).score(_SIM, _OBS).cost
    inline = _inline_cost(name)

    # A kernel whose cost is legitimately NaN counts as equal.
    assert (np.isnan(through_contract) and np.isnan(inline)) or through_contract == inline


YEAR = 365.25
DAYS = np.arange(4 * 365, dtype=float)
KEPT = (DAYS < 400) | (DAYS >= 520)  # a gap of 120 days in the record


def _stage() -> tuple[np.ndarray, np.ndarray]:
    obs = (
        10.0
        + 3.0 * np.cos(2.0 * np.pi * DAYS / YEAR)
        + np.sin(4.0 * np.pi * DAYS / YEAR)
        + 0.5 * np.sin(DAYS / 9.0)
    )
    sim = obs + 0.3 * np.sin(DAYS / 5.0) + 0.2
    return sim, obs


def test_gap_keeps_seasonal_score() -> None:
    sim, obs = _stage()
    whole = nse_seasonal(sim, obs, period=YEAR)

    gapped = nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])

    assert gapped == pytest.approx(whole, abs=0.02)


def test_nan_in_place_is_a_gap() -> None:
    sim, obs = _stage()
    holed = obs.copy()
    holed[~KEPT] = np.nan

    assert nse_seasonal(sim, holed, period=YEAR) == pytest.approx(
        nse_seasonal(sim[KEPT], obs[KEPT], period=YEAR, times=DAYS[KEPT])
    )


def test_increment_never_spans_a_gap() -> None:
    sim, obs = _stage()
    before, after = DAYS[KEPT] < 400, DAYS[KEPT] >= 520
    s, o = sim[KEPT], obs[KEPT]
    d_sim = np.concatenate([np.diff(s[before]), np.diff(s[after])])
    d_obs = np.concatenate([np.diff(o[before]), np.diff(o[after])])
    expected = 1.0 - np.sum((d_sim - d_obs) ** 2) / np.sum((d_obs - d_obs.mean()) ** 2)

    assert nse_delta(s, o, times=DAYS[KEPT]) == pytest.approx(expected)
    assert kge_delta(s, o, times=DAYS[KEPT])["kge"] == pytest.approx(kge(d_sim, d_obs)["kge"])


@pytest.mark.parametrize("metric", ["nse_seasonal", "nse_delta", "reservoir"])
def test_criterion_reads_dates(metric: str) -> None:
    sim, obs = _stage()
    criterion = SeriesCriterion(metric, METRICS[metric])
    holed = obs.copy()
    holed[~KEPT] = np.nan

    dated = criterion.score(sim[KEPT], obs[KEPT], sample_days=1.0, times_days=DAYS[KEPT])

    assert dated.cost == pytest.approx(criterion.score(sim, holed, sample_days=1.0).cost)


def test_gap_reaches_variable_route() -> None:
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


def test_block_route_reads_paired_dates() -> None:
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


def test_variable_route_matches_run_score() -> None:
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


def test_block_route_matches_run_score() -> None:
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


MONTH_ENDS = pd.date_range("2001-01-31", periods=36, freq="ME")
STEP_DAYS = float(np.median(np.diff(MONTH_ENDS.asi8) / 86_400e9))


def _cost(observed: pd.Series, simulated: pd.Series, metric: str) -> float:
    scorer = StationBlockScorer("head", metric, [ObservedSeries("PZ", "head", observed)])
    cost, _ = scorer.score(
        {"PZ": ObservableResult("PZ", simulated.to_numpy(), "m", simulated.index)}
    )
    return cost


def _monthly() -> tuple[pd.Series, pd.Series]:
    months = np.arange(MONTH_ENDS.size, dtype=float)
    obs = 10.0 + 3.0 * np.cos(2.0 * np.pi * months / 12.0) + 0.5 * np.sin(months)
    sim = obs + 0.2 * np.cos(3.0 * months)
    return pd.Series(obs, index=MONTH_ENDS), pd.Series(sim, index=MONTH_ENDS)


@pytest.mark.parametrize("metric", ["nse_seasonal", "reservoir"])
def test_monthly_series_matches_block_route(metric: str) -> None:
    observed, simulated = _monthly()

    cost = _cost(observed, simulated, metric)

    block = SeriesCriterion(metric, METRICS[metric]).score(
        simulated.to_numpy(),
        observed.to_numpy(),
        sample_days=STEP_DAYS,
        times_days=MONTH_ENDS.asi8 / 86_400e9,
    )
    assert np.isfinite(cost)
    assert cost == pytest.approx(block.cost)


def test_daily_series_keeps_daily_score() -> None:
    _, obs, sim = _daily_record()

    cost = _cost(obs, sim, "nse_seasonal")

    undated = SeriesCriterion("nse_seasonal", METRICS["nse_seasonal"]).score(
        sim.to_numpy(), obs.to_numpy()
    )
    assert cost == pytest.approx(undated.cost, abs=1e-3)


def test_kge_is_the_2009_form() -> None:
    obs = np.array([5.0, 3.0, 2.0, 1.2, 0.8, 0.5, 0.3, 0.2, 0.15, 0.1])
    sim = obs * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])

    parts = core.kge(sim, obs)

    assert parts["beta"] == pytest.approx(sim.sum() / obs.sum())
    assert parts["alpha"] == pytest.approx(sim.std() / obs.std())
    cv_ratio = (sim.std() / sim.mean()) / (obs.std() / obs.mean())
    assert parts["alpha"] != pytest.approx(cv_ratio)


def test_kge_formula_note_names_versions() -> None:
    formula = METRIC_FORMULAS["kge"]

    assert "2009" in formula.note
    assert "2012" in formula.note


CONFIRMED = [
    pytest.param((), False, id="no check"),
    pytest.param((Validity("a", True, None, "ok", fatal=True),), False, id="fatal but passed"),
    pytest.param((Validity("a", False, None, "coarse"),), False, id="failed but not fatal"),
    pytest.param(
        (Validity("a", True, None, "ok"), Validity("b", False, 1.0, "fiction", fatal=True)),
        True,
        id="failed and fatal",
    ),
]


@pytest.mark.parametrize(("validity", "fatal"), CONFIRMED)
def test_fatal_invalidity(validity, fatal) -> None:
    assert CriterionResult(cost=1.0, validity=validity).is_fatally_invalid is fatal
