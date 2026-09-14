"""Put a finely sampled series onto the stress periods a coarse index stands for.

A stress period is a duration, not an instant. A daily forcing carried onto a
monthly or yearly index has to be AVERAGED over each period; sampling the value
nearest the period stamp reports one day as if it were the whole period, and the
error is as large as the variability of the forcing.

Measured on the Nancon: a one-year steady period was handed the 1.36 mm of
1 January instead of the 0.33 mm the year averaged, and the reported catchment
discharge came out 67 per cent above what the run's own water balance allowed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = ("period_mean_on_index",)


def period_mean_on_index(values: Any, index: Any) -> pd.Series:
    """Return ``values`` averaged over the periods ``index`` stands for.

    Each stamp of ``index`` is read as the label of a period reaching halfway to
    its neighbours, and the first and last periods extend by half their own
    spacing. A period holding no sample comes back as ``NaN``: a forcing that
    does not cover the run is a gap the caller has to see, not a zero to add.

    A single stamp carries no spacing, so no period can be read from the index
    alone; the mean of the whole series is returned, which is the right answer
    when the series is the run's own forcing window and the run has one period.

    Parameters
    ----------
    values
        Datetime-indexed series, finer than ``index`` or as fine.
    index
        Stress-period labels, in the order the run wrote them.
    """
    series = pd.Series(values).dropna()
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)
    series = series.sort_index()

    target = pd.DatetimeIndex(pd.to_datetime(index))
    if target.tz is not None:
        target = target.tz_convert("UTC").tz_localize(None)
    if series.index.tz is not None:
        series.index = series.index.tz_convert("UTC").tz_localize(None)

    if series.empty or len(target) == 0:
        return pd.Series(np.nan, index=target, dtype=float)

    if len(target) == 1:
        return pd.Series(float(series.mean()), index=target, dtype=float)

    order = np.argsort(target.values)
    ordered = target[order]
    midpoints = ordered[:-1] + (ordered[1:] - ordered[:-1]) / 2
    first_half = (ordered[1] - ordered[0]) / 2
    last_half = (ordered[-1] - ordered[-2]) / 2
    edges = pd.DatetimeIndex([ordered[0] - first_half, *list(midpoints), ordered[-1] + last_half])

    bins = pd.cut(series.index, bins=edges, labels=ordered, right=False)
    averaged = series.groupby(bins, observed=False).mean()
    averaged.index = pd.DatetimeIndex(averaged.index)
    return averaged.reindex(target).astype(float)
