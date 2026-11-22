"""The baseflow index of a simulated and an observed daily discharge, on the same days.

The witnesses say what the index reads and what it is blind to: the same series
scores zero, so does a series twice as large, a constant stream is all baseflow, and
a slower reservoir behind the same input raises the index step by step.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.scoring.baseflow import baseflow_indices, wallingford
from hydromodpy.core.scoring.metrics import bfi_error, bfi_gap

DAYS = np.arange(1460, dtype=float)
STORMS = 2.0 + 1.5 * np.cos(2 * np.pi * DAYS / 365) + 12.0 * 0.6 ** (DAYS % 60)


def slower(q: np.ndarray, tau_days: float) -> np.ndarray:
    """``q`` through a linear reservoir of time constant ``tau_days``."""
    out = np.empty_like(q)
    out[0] = q[0]
    a = np.exp(-1.0 / tau_days)
    for i in range(1, q.size):
        out[i] = a * out[i - 1] + (1.0 - a) * q[i]
    return out


def test_the_same_series_and_a_series_twice_as_large_score_zero():
    assert bfi_gap(STORMS, STORMS) == 0.0
    assert bfi_gap(2.0 * STORMS, STORMS) == pytest.approx(0.0)


def test_a_constant_stream_is_all_baseflow():
    simulated, observed = baseflow_indices(np.full(DAYS.size, 3.0), STORMS)

    assert simulated == pytest.approx(1.0)
    assert bfi_gap(np.full(DAYS.size, 3.0), STORMS) == pytest.approx(1.0 - observed)


def test_a_slower_reservoir_raises_the_index_step_by_step():
    gaps = [bfi_gap(slower(STORMS, tau), STORMS) for tau in (5.0, 10.0, 30.0)]

    assert 0.0 < gaps[0] < gaps[1] < gaps[2]
    assert bfi_error(slower(STORMS, 30.0), STORMS) == pytest.approx(gaps[2])


def test_a_monthly_series_has_no_index():
    monthly = DAYS[::30]
    assert np.isnan(bfi_gap(STORMS[::30], STORMS[::30], times_days=monthly))


def test_a_gap_cuts_the_record_and_a_nan_drops_its_day_on_both_sides():
    days = np.concatenate([DAYS[:500], DAYS[600:]])
    flow = np.concatenate([STORMS[:500], STORMS[600:]])
    holed = flow.copy()
    holed[50] = np.nan

    whole = baseflow_indices(flow, flow, times_days=days)
    with_nan = baseflow_indices(flow, holed, times_days=days)

    assert whole[0] == pytest.approx(whole[1])
    assert with_nan[0] == pytest.approx(with_nan[1])


def test_the_filter_stays_under_the_discharge():
    baseflow = wallingford(STORMS)
    held = np.isfinite(baseflow)

    assert held.sum() > 0.9 * STORMS.size
    assert np.all(baseflow[held] <= STORMS[held] + 1e-12)
