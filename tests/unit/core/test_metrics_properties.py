"""Property-based tests for the hydrological efficiency metrics.

``hydromodpy.core.metrics`` is the scoreboard: calibration minimises these
numbers, comparison ranks runs by them, and a thesis figure reports them. The
example-based tests around the suite check a handful of known series against
known scores. What they cannot check is the algebra that must hold for every
series, and it is the algebra that goes wrong under a refactor: a
``ddof`` flipped from 0 to 1, a numerator and a denominator swapped, an
``align`` that stops dropping NaN pairs. Each of those keeps the hand-picked
cases green while moving every score in the study.

Determinism: ``derandomize=True`` pins the examples so this cannot become a
flaky gate, matching the ``_deterministic_seeds`` fixture in
``tests/conftest.py``. ``deadline=None`` removes the slow-runner failure mode.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from hydromodpy.core.metrics import (
    align,
    bias,
    correlation,
    kge,
    log_nse,
    mae,
    nse,
    pbias,
    rmse,
)

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
def test_a_perfect_simulation_scores_perfectly(observed: list[float]) -> None:
    """sim == obs must land on the exact optimum of every metric.

    The fixed point is the one score in the range that has a closed form, so it
    is the one a reader trusts without checking. A metric that returns 0.999999
    for a perfect fit has a bug in its normalisation, not a rounding problem.
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
def test_efficiencies_never_exceed_one(pair: tuple[list[float], list[float]]) -> None:
    """One is the ceiling of NSE and KGE, for any pair of series at all.

    Both are built as ``1 - <something non-negative>``, so a score above one is
    proof that the non-negative part is not what it claims to be. A calibration
    that can score above one has an objective function that no longer has its
    optimum where the model is right.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    assume(_informative(observed))
    assert nse(simulated, observed) <= 1.0
    score = kge(simulated, observed)["kge"]
    assert math.isnan(score) or score <= 1.0


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_correlation_stays_inside_minus_one_and_one(
    pair: tuple[list[float], list[float]],
) -> None:
    """Pearson r is bounded by construction; leaving the range means a bad normalisation."""
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    value = correlation(simulated, observed)
    assume(not math.isnan(value))
    assert -1.0 <= value <= 1.0


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_rmse_is_never_smaller_than_mae(pair: tuple[list[float], list[float]]) -> None:
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
def test_nse_ignores_a_shared_offset_and_a_shared_scale(
    pair: tuple[list[float], list[float]], offset: float, scale: float
) -> None:
    """NSE must not change when both series move together.

    Numerator and denominator carry the same units, so NSE is dimensionless:
    reporting a level in centimetres rather than metres, or against a different
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
def test_rmse_carries_the_unit_of_the_series(
    pair: tuple[list[float], list[float]], scale: float
) -> None:
    """RMSE is in the unit of the data, so it scales linearly with it.

    This is what lets an RMSE be quoted in metres next to a head. A metric that
    scaled with the square would still rank runs identically, which is why the
    error would survive the calibration tests and reach a figure caption.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    reference = rmse(simulated, observed)
    assume(reference > 1e-6)
    assert rmse(simulated * scale, observed * scale) == pytest.approx(scale * reference, rel=1e-9)


@given(pair=PAIRED_SERIES, extra=_SAMPLE)
@METRIC_PROPERTY
def test_a_gap_in_either_series_is_dropped_not_propagated(
    pair: tuple[list[float], list[float]], extra: float
) -> None:
    """Appending a NaN-paired sample must leave every score untouched.

    Real records have gaps, and ``align`` exists to drop them. If a NaN leaks
    through, the score is NaN and the calibration silently loses the run; if a
    gap is instead counted as a zero residual, the score is flattered. Both
    have happened to gauge series with missing days.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    assume(_informative(observed))
    padded_simulated = np.append(simulated, np.nan)
    padded_observed = np.append(observed, extra)
    assert rmse(padded_simulated, padded_observed) == rmse(simulated, observed)
    assert mae(padded_simulated, padded_observed) == mae(simulated, observed)
    assert nse(padded_simulated, padded_observed) == nse(simulated, observed)
    # The gap may equally sit on the observed side.
    assert rmse(np.append(simulated, extra), np.append(observed, np.nan)) == rmse(
        simulated, observed
    )


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_bias_and_percent_bias_report_opposite_signs(
    pair: tuple[list[float], list[float]],
) -> None:
    """PBIAS is positive when the model underestimates; BIAS is negative there.

    The two are defined with the difference the other way round, which is a
    standing trap when one of them is edited. Getting the sign wrong inverts
    how every calibration report reads.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    total_observed = float(np.sum(observed))
    assume(total_observed > 1.0)
    mean_error = bias(simulated, observed)
    assume(abs(mean_error) > 1e-6)
    percent = pbias(simulated, observed)
    assert math.copysign(1.0, percent) == -math.copysign(1.0, mean_error)


@given(pair=PAIRED_SERIES)
@METRIC_PROPERTY
def test_log_nse_refuses_a_negative_series(
    pair: tuple[list[float], list[float]],
) -> None:
    """A log efficiency on a series that goes negative must raise, not return NaN.

    ``log_nse`` is the low-flow metric, so it is pointed at discharge, and a
    negative discharge means the series is wrong upstream. Returning NaN would
    let the bad series through as an unscored run.
    """
    simulated, observed = (np.asarray(series, dtype=float) for series in pair)
    assume(bool(np.any(simulated < 0.0) or np.any(observed < 0.0)))
    with pytest.raises(ValueError):
        log_nse(simulated, observed)


@given(shorter=SERIES, longer=SERIES)
@METRIC_PROPERTY
def test_misaligned_series_are_rejected(shorter: list[float], longer: list[float]) -> None:
    """Two series of different length must raise rather than be silently truncated.

    Scoring a simulation against an observation record that was cut elsewhere is
    the mistake this guard exists for: NumPy would happily broadcast some of
    these shapes and return a number.
    """
    assume(len(shorter) != len(longer))
    with pytest.raises(ValueError):
        align(shorter, longer)
