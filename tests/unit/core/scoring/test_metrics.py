"""Scores of a simulated series against an observed one, for calibration and comparison.

Series share one unit, RMSE, MAE and bias keep it, PBIAS is in percent. Known series against known scores (KGE, NSE, bias, PBIAS), the observed series with
no spread that scores NaN instead of a huge cost, and the algebra that must hold
for every series, checked by property. ``pbias`` reads like ``bias``: positive when
the model overestimates. Determinism of the properties: ``derandomize=True`` pins the
examples, matching the ``_deterministic_seeds`` fixture in ``tests/conftest.py``, and
``deadline=None`` removes the slow-runner failure mode.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from hydromodpy.core.scoring.metrics import (
    align,
    bias,
    clip_negatives,
    correlation,
    kge,
    kge_delta,
    log_nse,
    mae,
    nse,
    nse_delta,
    nse_seasonal,
    pbias,
    rmse,
)
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION

pytestmark = pytest.mark.unit


OBSERVED = np.array([1.0, 2.0, 3.0, 4.0])

# One row per score: the metric, the simulation, the observations and the value by hand.
SCORES = [
    pytest.param(rmse, [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], 0.0, id="rmse of a perfect fit"),
    pytest.param(rmse, [2.0, 3.0, 4.0], [1.0, 2.0, 3.0], 1.0, id="rmse of a shift by one"),
    pytest.param(bias, [1.5, 2.5, 3.5], [1.0, 2.0, 3.0], 0.5, id="bias is the signed mean error"),
    pytest.param(bias, OBSERVED * 1.1, OBSERVED, 0.25, id="bias of an overestimate is positive"),
    pytest.param(pbias, OBSERVED, OBSERVED, 0.0, id="pbias of a perfect fit"),
    pytest.param(pbias, OBSERVED * 1.1, OBSERVED, 10.0, id="pbias of an overestimate"),
    pytest.param(pbias, OBSERVED * 0.8, OBSERVED, -20.0, id="pbias of an underestimate"),
    # Summed error 11 - 10 = 1 over summed observations 10.
    pytest.param(pbias, [2.0, 2.0, 2.0, 5.0], OBSERVED, 10.0, id="pbias of a mixed error"),
    pytest.param(correlation, OBSERVED, OBSERVED, 1.0, id="correlation of a perfect fit"),
    pytest.param(correlation, -OBSERVED, OBSERVED, -1.0, id="anticorrelation"),
    pytest.param(nse, OBSERVED, OBSERVED, 1.0, id="nse of a perfect fit"),
    pytest.param(nse, [2.5] * 4, OBSERVED, 0.0, id="nse of the climatology"),
    pytest.param(
        log_nse, [1.0, 10.0, 100.0], [1.0, 10.0, 100.0], 1.0, id="log nse of a perfect fit"
    ),
]


@pytest.mark.parametrize(("metric", "sim", "obs", "expected"), SCORES)
def test_known_scores(metric, sim, obs, expected) -> None:
    assert metric(np.array(sim), np.array(obs)) == pytest.approx(expected)


# Observations that sum to zero, or that have no spread, leave the metric undefined.
UNDEFINED = [
    pytest.param(pbias, [1.1, -0.9, 2.1, -1.9], [1.0, -1.0, 2.0, -2.0], id="pbias, zero total"),
    pytest.param(nse, [3.1, 2.9, 3.0, 3.0, 3.1], np.full(5, 3.0), id="nse, constant obs"),
]


@pytest.mark.parametrize(("metric", "sim", "obs"), UNDEFINED)
def test_undefined_scores(metric, sim, obs) -> None:
    assert np.isnan(metric(np.array(sim), np.array(obs)))


def test_kge_perfect_fit():
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = kge(obs, obs)
    assert out["kge"] == pytest.approx(1.0)
    assert out["r"] == pytest.approx(1.0)
    assert out["alpha"] == pytest.approx(1.0)
    assert out["beta"] == pytest.approx(1.0)


def test_kge_doubled_series():
    """sim = 2 * obs gives r=1, alpha=2, beta=2."""
    obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = kge(2.0 * obs, obs)
    assert out["r"] == pytest.approx(1.0)
    assert out["alpha"] == pytest.approx(2.0)
    assert out["beta"] == pytest.approx(2.0)
    expected = 1.0 - np.sqrt(0.0 + 1.0 + 1.0)
    assert out["kge"] == pytest.approx(expected)


def test_kge_constant_obs_is_nan():
    out = kge(np.array([1.0, 2.0, 3.0]), np.array([5.0, 5.0, 5.0]))
    assert np.isnan(out["kge"])


def test_kge_no_overlap_is_nan():
    out = kge(np.array([np.nan, np.nan]), np.array([1.0, 2.0]))
    assert np.isnan(out["kge"])


@pytest.mark.parametrize(
    ("sim", "obs", "expected"),
    [
        # Two samples is enough. std(sim)=1, std(obs)=0.5, sums 4 and 3 (population std).
        ([1.0, 3.0], [1.0, 2.0], (1.0, 2.0, 4.0 / 3.0)),
        # cov 0.75, var(sim) 1.5, var(obs) 1.25, sums 12 and 10.
        ([2.0, 2.0, 3.0, 5.0], [1.0, 2.0, 4.0, 3.0], (0.75 / 1.875**0.5, (1.5 / 1.25) ** 0.5, 1.2)),
    ],
)
def test_kge_by_hand(sim, obs, expected) -> None:
    r, alpha, beta = expected
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = kge(np.array(sim), np.array(obs))
    score = 1.0 - ((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2) ** 0.5
    assert list(out) == ["kge", "r", "alpha", "beta"]
    assert list(out.values()) == pytest.approx([score, r, alpha, beta])


# Increments of obs at step 1 are 1,2,3,4,5 and of sim 2,1,4,3,6; at step 2 both are 3,5,7,9.
# With a gap in time the runs [0,1,2] and [3,4,5] are differenced apart: obs 1,2,4,5, sim 2,1,3,6.
_OBS = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
_SIM = np.array([0.0, 2.0, 3.0, 7.0, 10.0, 16.0])
_GAP = [0, 1, 2, 100, 101, 102]


@pytest.mark.parametrize(
    ("options", "d_sim", "d_obs"),
    [
        ({}, [2, 1, 4, 3, 6], [1, 2, 3, 4, 5]),
        ({"step": 2}, [3, 5, 7, 9], [3, 5, 7, 9]),
        ({"times": _GAP}, [2, 1, 3, 6], [1, 2, 4, 5]),
        ({"step": 2, "times": _GAP}, [3, 9], [3, 9]),
    ],
)
def test_kge_delta(options, d_sim, d_obs) -> None:
    assert kge_delta(_SIM, _OBS, **options) == pytest.approx(kge(np.array(d_sim), np.array(d_obs)))


def test_kge_delta_without_increments() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = kge_delta(_SIM[:2], _OBS[:2])
    assert list(out) == ["kge", "r", "alpha", "beta"]
    assert all(np.isnan(v) for v in out.values())


def test_nse_shape_mismatch_refused():
    with pytest.raises(ValueError):
        nse(np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]))


def test_log_nse_clips_negatives():
    sim, obs = np.array([-1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.5])
    assert log_nse(sim, obs) == pytest.approx(log_nse(np.array([0.0, 2.0, 3.0]), obs))


def _cycle(t: np.ndarray) -> np.ndarray:
    angle = 2.0 * np.pi * t / 365.0
    return 10.0 + 2.0 * np.cos(angle) + 0.5 * np.sin(2.0 * angle) + 0.3 * np.cos(2.0 * angle)


def test_nse_seasonal_by_hand() -> None:
    """The ripple sin(2 pi t / 73) is orthogonal to the harmonics over 730 samples.

    The benchmark is then the cycle alone, the denominator is the energy of the
    ripple (365) and a simulation off by half the ripple scores 1 - 0.25.
    """
    t = np.arange(730.0)
    ripple = np.sin(2.0 * np.pi * t / 73.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        score = nse_seasonal(_cycle(t) + 1.5 * ripple, _cycle(t) + ripple)
    assert score == pytest.approx(0.75)


def test_nse_seasonal_empty() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert np.isnan(nse_seasonal(np.array([]), np.array([])))


def test_rule_version() -> None:
    assert METRIC_RULE_VERSION == "2"


RNG = np.random.default_rng(0)


@pytest.mark.parametrize("value", [0.1, 0.3, 1.1, 101.7])
def test_constant_series_is_nan(value: float) -> None:
    obs = np.full(1000, value)
    assert float(np.sum((obs - obs.mean()) ** 2)) > 0.0

    assert np.isnan(nse(obs + RNG.normal(0.0, 0.01, obs.size), obs))
    assert np.isnan(log_nse(obs * 1.01, obs))


def test_regular_ramp_is_nan() -> None:
    obs = np.linspace(0.0, 1.0, 1001)
    sim = obs + RNG.normal(0.0, 0.01, obs.size)

    assert np.isnan(nse_delta(sim, obs))


def test_pure_cycle_is_nan() -> None:
    t = np.arange(3 * 365, dtype=float)
    obs = 10.0 + 2.0 * np.cos(2.0 * np.pi * t / 365.0) + 0.5 * np.sin(4.0 * np.pi * t / 365.0)

    assert np.isnan(nse_seasonal(obs * 1.01, obs))


@pytest.mark.parametrize(
    ("sim", "obs", "reason"),
    [
        ([1.0], [1.0], "fewer than 2"),
        ([1.0, 2.0, 3.0], [2.0, 2.0, 2.0], "constant"),
        ([1.0, 2.0, 3.0], [-1.0, 0.0, 1.0], "sum to zero"),
        ([1.0, 1.0, 1.0], [1.0, 2.0, 3.0], "simulation is constant"),
    ],
)
def test_kge_nan_reasons(sim: list[float], obs: list[float], reason: str) -> None:
    with pytest.warns(UserWarning, match=reason):
        assert np.isnan(kge(np.array(sim), np.array(obs))["kge"])


METRIC_PROPERTY = settings(derandomize=True, max_examples=100, deadline=None)

# Magnitude bound, deliberately narrow. Every metric here is a sum of squares
# over up to 64 samples, so |x| <= 1e4 keeps the accumulator under ~1e12: far
# from float64 overflow, and far from the regime where NSE's ``1 - A / B`` is
# dominated by cancellation rather than by the quantity being measured. An
# unbounded strategy would report inf-vs-inf comparisons, which say nothing
# about the metrics and would only teach us to mute the test.
_SAMPLE = st.floats(
    min_value=-1e4,
    max_value=1e4,
    allow_nan=False,
    allow_infinity=False,
)
# min_size=3: kge and correlation are documented to return NaN below two
# samples, and nse needs a non-degenerate spread. max_size=64 keeps the whole
# module inside the 60 s unit-tier timeout.
SERIES = st.lists(_SAMPLE, min_size=3, max_size=64)
PAIRED_SERIES = st.integers(min_value=3, max_value=64).flatmap(
    lambda size: st.tuples(
        st.lists(_SAMPLE, min_size=size, max_size=size),
        st.lists(_SAMPLE, min_size=size, max_size=size),
    )
)
# Scale factors stay well inside the magnitude bound so the scaled series does
# not leave the range the tolerances were chosen for.
SCALES = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)


def _informative(observed: np.ndarray) -> bool:
    """True when the observations carry enough spread to score against.

    Every efficiency here divides by the variance of the observations, and both
    ``nse`` and ``kge`` return NaN when it vanishes. Below this threshold the
    score is real but ill-conditioned, which is a statement about float64 and
    not about the metric.
    """
    return bool(np.std(observed) > 1e-3)


@given(observed=SERIES)
@METRIC_PROPERTY
def test_perfect_simulation(observed: list[float]) -> None:
    """sim == obs must land on the exact optimum of every metric.

    The fixed point is the one score in the range that has a closed form, so it
    is the one a reader trusts without checking. A metric that returns 0.999999
    for a perfect fit has a bug in its normalization, not a rounding problem.
    """
    obs = np.asarray(observed, dtype=float)
    assume(_informative(obs))
    assert nse(obs, obs) == 1.0
    assert rmse(obs, obs) == 0.0
    assert mae(obs, obs) == 0.0
    assert bias(obs, obs) == 0.0
    assert correlation(obs, obs) == pytest.approx(1.0, rel=1e-12)
    decomposition = kge(obs, obs)
    assert decomposition["kge"] == pytest.approx(1.0, rel=1e-12)
    assert decomposition["alpha"] == pytest.approx(1.0, rel=1e-12)


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_correlation_bounds(
    pair: tuple[list[float], list[float]],
) -> None:
    """Pearson r is bounded by construction; leaving the range means a bad normalization."""
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    value = correlation(simulated, observed)
    assume(not math.isnan(value))
    assert -1.0 <= value <= 1.0


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_rmse_at_least_mae(pair: tuple[list[float], list[float]]) -> None:
    """RMSE >= MAE always, by the power-mean inequality.

    The two are reported side by side, and their gap is read as a statement
    about how much of the error sits in a few large residuals. If the ordering
    can invert, one of them is not averaging what its name says.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    root_mean_square = rmse(simulated, observed)
    mean_absolute = mae(simulated, observed)
    assume(not math.isnan(root_mean_square))
    assert root_mean_square >= mean_absolute or root_mean_square == pytest.approx(
        mean_absolute, rel=1e-12
    )


@given(pair=PAIRED_SERIES, offset=_SAMPLE, scale=SCALES)
@METRIC_PROPERTY
def test_nse_offset_and_scale(
    pair: tuple[list[float], list[float]], offset: float, scale: float
) -> None:
    """NSE must not change when both series move together.

    Numerator and denominator carry the same units, so NSE is dimensionless:
    reporting a level in centimeters rather than meters, or against a different
    datum, cannot change the score. A ``ddof`` or a mean that leaks into only
    one of the two sums breaks exactly this and nothing else.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    assume(_informative(observed))
    reference = nse(simulated, observed)
    assume(not math.isnan(reference))
    # A shared datum shift leaves both sums untouched.
    assert nse(simulated + offset, observed + offset) == pytest.approx(
        reference, rel=1e-9, abs=1e-9
    )
    # A shared unit change scales both sums by the same square.
    assert nse(simulated * scale, observed * scale) == pytest.approx(reference, rel=1e-9, abs=1e-9)


@given(pair=PAIRED_SERIES, scale=SCALES)
@METRIC_PROPERTY
def test_rmse_scales_with_the_unit(pair: tuple[list[float], list[float]], scale: float) -> None:
    """RMSE is in the unit of the data, so it scales linearly with it.

    This is what lets an RMSE be quoted in meters next to a head. A metric that
    scaled with the square would still rank runs identically, which is why the
    error would survive the calibration tests and reach a figure caption.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    reference = rmse(simulated, observed)
    assume(reference > 1e-6)
    assert rmse(simulated * scale, observed * scale) == pytest.approx(scale * reference, rel=1e-9)


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_bias_signs_agree(
    pair: tuple[list[float], list[float]],
) -> None:
    """PBIAS and BIAS are both positive when the model overestimates.

    The two used to be defined with the difference the other way round
    (decision m13 aligned them). Getting the sign wrong inverts how every
    calibration report reads.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    total_observed = float(np.sum(observed))
    assume(total_observed > 1.0)
    mean_error = bias(simulated, observed)
    assume(abs(mean_error) > 1e-6)
    percent = pbias(simulated, observed)
    assert math.copysign(1.0, percent) == math.copysign(1.0, mean_error)


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_log_nse_clips_by_property(
    pair: tuple[list[float], list[float]],
) -> None:
    """A log efficiency on a series that goes negative reads it clipped to zero.

    A discharge reconstructed below a dam can hold a few negative values. The
    run score and the calibration cost clip them alike (decision m12), and
    ``clip_negatives`` counts what was clipped.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    assume(bool(np.any(simulated < 0.0) or np.any(observed < 0.0)))
    clipped_sim, clipped_obs, n_clipped = clip_negatives(simulated, observed)
    assert n_clipped > 0
    expected = log_nse(clipped_sim, clipped_obs)
    got = log_nse(simulated, observed)
    assert (math.isnan(got) and math.isnan(expected)) or got == pytest.approx(expected)


@given(shorter=SERIES, longer=SERIES)
@METRIC_PROPERTY
def test_misaligned_series_refused(shorter: list[float], longer: list[float]) -> None:
    """Two series of different length must raise rather than be silently truncated.

    Scoring a simulation against an observation record that was cut elsewhere is
    the mistake this guard exists for: NumPy would happily broadcast some of
    these shapes and return a number.
    """
    assume(len(shorter) != len(longer))
    with pytest.raises(ValueError):
        align(shorter, longer)
