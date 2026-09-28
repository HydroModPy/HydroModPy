"""The mean recharge the stream-network criterion divides by.

The criterion thresholds seepage at a fraction of the recharge and calibrates
``K/R``, so ``R`` has one definition for the trials that score a run and for
the figures that redraw it: the unweighted mean, over the run's periods and
cells, of the rate the recharge forcing gives each period.

A period's rate is its own. A solver writes the record mean into a steady
spin-up period in place of that period's rate, and a mean read from what it
wrote is another statistic: on the monthly Nancon, 8.656e-9 m/s where the
forcing gives 9.075e-9, and the steady phase that seeds the run reads 9.075e-9.
So the trials read the rates the built model holds, the redraw rebuilds them
from the forcing the run stores, and both average them here.

It lives in ``core`` because the calibration and the results layers both need
it and neither may import the other.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.time.period_aggregation import period_mean_on_index

__all__ = ("criterion_mean_recharge", "forcing_period_rates")


def forcing_period_rates(samples: pd.Series, edges: Any) -> np.ndarray:
    """Return the rate a recharge series gives each period ``[s, e)``.

    The rule the solver forcing is built by: the mean of the samples in the
    period, else the last sample before its end. A negative rate is clipped at
    zero, as the recharge package receives it: the deficit goes to EVT.
    ``edges`` are the ``n + 1`` period edges; the result keeps the unit of
    ``samples``.
    """
    bounds = pd.DatetimeIndex(pd.to_datetime(edges))
    if len(bounds) < 2:
        raise ValueError(f"a run needs at least two period edges, got {len(bounds)}.")
    series = pd.Series(samples, dtype="float64").dropna()
    series.index = pd.DatetimeIndex(series.index)
    series = series.sort_index()
    rates = period_mean_on_index(series, bounds[1:], start=bounds[0]).to_numpy(dtype=float)
    for index in np.flatnonzero(~np.isfinite(rates)):
        before = series[series.index < bounds[index + 1]]
        if len(before):
            rates[index] = float(before.iloc[-1])
    return np.maximum(rates, 0.0)


def criterion_mean_recharge(values: Any) -> float:
    """Return the unweighted mean of the finite recharge rates, over periods and cells.

    ``values`` is one array or a sequence of per-period arrays; a uniform
    period may be one number.
    """
    parts = values if isinstance(values, list | tuple) else [values]
    flat = [np.asarray(part, dtype=float).reshape(-1) for part in parts]
    rates = np.concatenate(flat) if flat else np.empty(0)
    finite = rates[np.isfinite(rates)]
    if finite.size == 0:
        raise ValueError("the recharge holds no finite rate.")
    return float(np.mean(finite))
