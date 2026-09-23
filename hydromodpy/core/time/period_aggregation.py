"""Put a finely sampled series onto the stress periods a coarse index stands for.

A stress period is a duration, not an instant. A daily forcing carried onto a
monthly or yearly index has to be AVERAGED over each period; sampling the value
nearest the period stamp reports one day as if it were the whole period, and the
error is as large as the variability of the forcing.

Measured on the Nancon: a one-year steady period was handed the 1.36 mm of
1 January instead of the 0.33 mm the year averaged, and the reported catchment
discharge came out 67 per cent above what the run's own water balance allowed.

The stamp convention is the one the solvers write. Every extractor stamps a
stress period at its END: the CF ``/time`` axis is the run start plus the
elapsed solver time, so January 2000 of a monthly run is stamped 2000-02-01 and
a steady run over 2000-2002 is stamped 2003-01-01. Period ``i`` is therefore the
half-open interval ``[stamp_(i-1), stamp_i)``. A sample is stamped at the START
of what it averages: a daily mean at its day, a monthly mean at its month start.

Reading a stamp as the centre of its period, as this module used to, compared
January with the mean of mid-December to mid-January. On the Nancon gauge
J001401001 (2000-2002, station mean 0.97 m3/s) that put the monthly mean
0.167 m3/s off on average, and a monthly chronicle a full month late.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.time_method import check_time_method

__all__ = (
    "first_period_step",
    "observation_step",
    "observed_on_periods",
    "period_edges",
    "period_end_stamps",
    "period_mean_on_index",
    "period_point_on_index",
    "period_value_on_index",
)

logger = get_logger(__name__)


def _naive(index: Any) -> pd.DatetimeIndex:
    """Return ``index`` as a tz-naive UTC nanosecond ``DatetimeIndex``."""
    out = pd.DatetimeIndex(pd.to_datetime(index))
    if out.tz is not None:
        out = out.tz_convert("UTC").tz_localize(None)
    return out.as_unit("ns")


def _naive_timestamp(value: Any) -> pd.Timestamp:
    """Return one timestamp, tz-naive in UTC."""
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _month_step(earlier: pd.Timestamp, later: pd.Timestamp) -> pd.DateOffset | None:
    """Return a whole number of months from ``earlier`` to ``later``, or None."""
    if earlier.day != later.day or earlier.time() != later.time():
        return None
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if months <= 0:
        return None
    return pd.DateOffset(months=months)


def first_period_step(stamps: Any) -> pd.DateOffset | pd.Timedelta | None:
    """Return the length of the first period an end-stamped index stands for.

    A regular calendar index answers with its own frequency (``pd.infer_freq``),
    so a month is a month and not 31 days. An index too short or too irregular
    for that answers with its first spacing, in whole months when both stamps
    fall on the same day of the month. A single stamp has no spacing and
    answers ``None``.
    """
    ordered = _naive(stamps).sort_values().unique()
    if len(ordered) < 2:
        return None
    if len(ordered) >= 3:
        freq = pd.infer_freq(ordered)
        if freq is not None:
            return pd.tseries.frequencies.to_offset(freq)
    months = _month_step(ordered[0], ordered[1])
    if months is not None:
        return months
    return pd.Timedelta(ordered[1] - ordered[0])


def period_edges(stamps: Any, *, start: Any = None) -> pd.DatetimeIndex:
    """Return the ``n + 1`` edges of the periods an end-stamped index stands for.

    Period ``i`` is ``[edges[i], edges[i + 1])`` and ``edges[i + 1]`` is the
    ``i``-th stamp in sorted order. The first edge is ``start`` when the caller
    knows it, which is the run window start. Otherwise it is the first stamp
    minus :func:`first_period_step`. A single stamp without a start has no
    first edge and raises ``ValueError``.
    """
    ordered = _naive(stamps).sort_values().unique()
    if len(ordered) == 0:
        raise ValueError("an empty index has no period.")
    if start is not None:
        first = _naive_timestamp(start)
    else:
        step = first_period_step(ordered)
        if step is None:
            raise ValueError("a single stamp carries no spacing: pass the start of its period.")
        first = ordered[0] - step
    if first >= ordered[0]:
        raise ValueError(
            f"the first period starts at {first}, not before its end stamp {ordered[0]}."
        )
    return pd.DatetimeIndex([first, *list(ordered)]).as_unit("ns")


def period_end_stamps(
    start: Any,
    end: Any,
    n_periods: int,
    *,
    step_unit: str | None = None,
) -> pd.DatetimeIndex:
    """Return the ``n_periods`` end stamps of a window ``[start, end)``.

    This is the fallback when the solver's ``/time`` axis is missing: the
    catalog keeps the window bounds and the number of periods, not the stamps.
    A ``month`` or ``year`` step rebuilds calendar periods when a whole number
    of them fills the window. So does an unknown step, since one month is the
    schema default. Any other case splits the window evenly, which is exact for
    hourly and daily steps.
    """
    first = _naive_timestamp(start)
    last = _naive_timestamp(end)
    n = int(n_periods)
    if n <= 0:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    if n == 1:
        return pd.DatetimeIndex([last]).as_unit("ns")
    unit = (step_unit or "").strip().lower()
    if unit in {"", "month", "year"}:
        total_months = (last.year - first.year) * 12 + (last.month - first.month)
        fits = first + pd.DateOffset(months=total_months) == last
        if fits and total_months > 0 and total_months % n == 0:
            months = total_months // n
            ends = [first + pd.DateOffset(months=months * (i + 1)) for i in range(n)]
            return pd.DatetimeIndex(ends).as_unit("ns")
    return pd.date_range(first, last, periods=n + 1)[1:].as_unit("ns")


def period_mean_on_index(values: Any, index: Any, *, start: Any = None) -> pd.Series:
    """Return ``values`` averaged over the periods ``index`` stands for.

    Each stamp of ``index`` is the END of its period, so period ``i`` holds the
    samples stamped in ``[stamp_(i-1), stamp_i)``. The first period starts at
    ``start`` when the caller knows it, else one inferred step before the first
    stamp (see :func:`period_edges`). A period holding no sample comes back as
    ``NaN``: a forcing that does not cover the run is a gap the caller has to
    see, not a zero to add.

    A single stamp without ``start`` carries no spacing, so no period can be
    read from the index alone; the mean of the whole series is returned, which
    is the right answer when the series is the run's own forcing window and the
    run has one period.

    Parameters
    ----------
    values
        Datetime-indexed series, finer than ``index`` or as fine, each sample
        stamped at the start of what it averages.
    index
        Stress-period end stamps, in the order the run wrote them.
    start
        Start of the first period, the run window start. Optional.
    """
    labels = pd.DatetimeIndex(pd.to_datetime(index))
    series = pd.Series(values).dropna()
    series.index = _naive(series.index)
    series = series.sort_index()
    target = _naive(labels)

    if series.empty or len(target) == 0:
        return pd.Series(np.nan, index=labels, dtype=float)

    if start is None and len(target.unique()) == 1:
        return pd.Series(float(series.mean()), index=labels, dtype=float)

    edges = period_edges(target, start=start)
    position = edges.searchsorted(series.index, side="right") - 1
    inside = (position >= 0) & (position < len(edges) - 1)
    averaged = series[inside].groupby(position[inside]).mean()
    per_period = pd.Series(np.nan, index=edges[1:], dtype=float)
    per_period.iloc[averaged.index.to_numpy()] = averaged.to_numpy(dtype=float)
    return pd.Series(per_period.reindex(target).to_numpy(dtype=float), index=labels)


def observation_step(stamps: Any) -> pd.DateOffset | pd.Timedelta | None:
    """Return the interval one observation of a chronicle stands for.

    A regular chronicle answers with its calendar frequency, so a monthly mean
    stamped at its month start reaches the next month start. A chronicle with
    gaps answers with its median spacing, in whole months when every stamp
    falls on the same day of the month. A single sample answers ``None``.
    """
    ordered = _naive(stamps).sort_values().unique()
    if len(ordered) < 2:
        return None
    if len(ordered) >= 3:
        freq = pd.infer_freq(ordered)
        if freq is not None:
            return pd.tseries.frequencies.to_offset(freq)
    same_day = (ordered.day == ordered[0].day).all() and (ordered.time == ordered[0].time()).all()
    if same_day:
        # Truncate a fractional median on purpose: a shorter reach leaves a
        # period NaN instead of holding an observation past its own interval.
        median_months = int(np.median(np.diff(ordered.year * 12 + ordered.month)))
        if median_months > 0:
            return pd.DateOffset(months=median_months)
    return pd.Timedelta(pd.Series(ordered).diff().dropna().median())


def period_value_on_index(
    values: Any,
    index: Any,
    *,
    start: Any = None,
    reach: pd.DateOffset | pd.Timedelta | None = None,
) -> pd.Series:
    """Return an observation chronicle on the periods ``index`` stands for.

    Each stamp of ``index`` is the END of its period and each observation is
    stamped at the START of what it averages. For every period ``[s, e)``:

    - the period takes the mean of the observations stamped in ``[s, e)``
      (:func:`period_mean_on_index`);
    - a period holding no observation takes the last observation stamped at
      or before ``s``, when the interval that observation stands for covers
      the whole period, ``e <= stamp + reach``. That is a chronicle coarser
      than the run: a monthly mean on a daily run.

    ``reach`` is the interval of one observation, by default the step of the
    chronicle (:func:`observation_step`), so a gap in the chronicle stays
    ``NaN``.

    A single stamp is a steady period, and its window is ``[start, stamp)``.
    Every calibration path knows ``start`` from the run's time grid and passes
    it. Without it the period cannot be read from one stamp, and the mean of
    the whole chronicle is returned, as :func:`period_mean_on_index` does,
    logged at debug level. That holds only when the chronicle reaches the
    stamp, first observation before it and last one's interval reaching it: a
    1990 record is not the mean of a 2020 steady run, and stays ``NaN``.

    A FORCING is not an observation chronicle: a period it misses is a gap,
    not the previous value, so forcings go through :func:`period_mean_on_index`.
    This is the ``"mean"`` rule of :mod:`hydromodpy.core.time.time_method`; a
    state at the stamp goes through :func:`period_point_on_index`.
    """
    labels = pd.DatetimeIndex(pd.to_datetime(index))
    series = pd.Series(values).dropna()
    series.index = _naive(series.index)
    series = series.sort_index()
    target = _naive(labels)
    if series.empty or len(target) == 0:
        return pd.Series(np.nan, index=labels, dtype=float)

    step = reach if reach is not None else observation_step(series.index)
    stamps = target.sort_values().unique()
    if start is None and len(stamps) == 1:
        last_reach = series.index[-1] + step if step is not None else series.index[-1]
        if not series.index[0] < stamps[0] <= last_reach:
            return pd.Series(np.nan, index=labels, dtype=float)
        logger.debug(
            "One period stamped %s and no start: it takes the mean of the whole "
            "chronicle, %s to %s.",
            stamps[0],
            series.index[0],
            series.index[-1],
        )
        return pd.Series(float(series.mean()), index=labels, dtype=float)

    edges = period_edges(stamps, start=start)
    per_period = period_mean_on_index(series, stamps, start=start)
    empty = np.flatnonzero(per_period.isna().to_numpy())
    if step is not None and empty.size:
        held = series.index.searchsorted(edges[:-1][empty], side="right") - 1
        found = held >= 0
        held_at = series.index[held[found]]
        covered = np.asarray(edges[1:][empty][found] <= held_at + step)
        per_period.iloc[empty[found][covered]] = series.to_numpy(dtype=float)[held[found][covered]]
    return pd.Series(per_period.reindex(target).to_numpy(dtype=float), index=labels)


def _median_spacing(index: pd.DatetimeIndex) -> pd.Timedelta | None:
    """Return the median spacing of a sorted index, or None below two stamps."""
    if len(index) < 2:
        return None
    return pd.Timedelta(np.median(np.diff(index.asi8)), unit="ns")


def _centred_window_means(series: pd.Series, stamps: pd.DatetimeIndex) -> np.ndarray:
    """Return the mean of ``series`` on a window centred on each sorted stamp.

    A window reaches halfway to each neighbouring stamp, and the first and last
    windows reach half their own spacing outward. Bounds are ``[lo, hi)``. A
    window holding no sample is ``NaN``.
    """
    halves = (stamps[1:] - stamps[:-1]) / 2
    midpoints = stamps[:-1] + halves
    edges = pd.DatetimeIndex(
        [stamps[0] - halves[0], *list(midpoints), stamps[-1] + halves[-1]]
    ).as_unit("ns")
    position = edges.searchsorted(series.index, side="right") - 1
    inside = (position >= 0) & (position < len(stamps))
    means = np.full(len(stamps), np.nan)
    averaged = series[inside].groupby(position[inside]).mean()
    means[averaged.index.to_numpy()] = averaged.to_numpy(dtype=float)
    return means


def _nearest_within(
    series: pd.Series,
    stamps: pd.DatetimeIndex,
    tolerance: pd.Timedelta | pd.DateOffset,
) -> np.ndarray:
    """Return the sample nearest each stamp, ``NaN`` beyond ``tolerance``.

    A tie between the sample before and the sample after goes to the earlier
    one. The bound is inclusive on both sides.
    """
    times = series.index
    values = series.to_numpy(dtype=float)
    after = times.searchsorted(stamps, side="left")
    before = after - 1
    out = np.full(len(stamps), np.nan)
    for i, stamp in enumerate(stamps):
        candidates: list[tuple[pd.Timedelta, int, bool]] = []
        if before[i] >= 0:
            candidates.append((stamp - times[before[i]], int(before[i]), True))
        if after[i] < len(times):
            candidates.append((times[after[i]] - stamp, int(after[i]), False))
        if not candidates:
            continue
        _, chosen, earlier = min(candidates, key=lambda item: (item[0], not item[2]))
        at = times[chosen]
        reached = at >= stamp - tolerance if earlier else at <= stamp + tolerance
        if reached:
            out[i] = values[chosen]
    return out


def period_point_on_index(
    values: Any,
    index: Any,
    *,
    tolerance: pd.Timedelta | pd.DateOffset | None = None,
) -> pd.Series:
    """Return an observation chronicle at the instants ``index`` stamps.

    A state is the value AT the stamp: a MODFLOW head or a lake stage at the
    end of its period. Averaging the chronicle over ``[s, e)`` would compare it
    with a value half a period earlier, so a state is read around the stamp:

    - a chronicle finer than the run, on median spacings, takes the mean of the
      samples in a window centred on the stamp, reaching halfway to each
      neighbouring stamp. A window holding no sample is ``NaN``;
    - a chronicle as coarse as the run or coarser takes the sample nearest the
      stamp within ``tolerance``, by default the median spacing of the stamps,
      else of the chronicle. A tie goes to the earlier sample.

    This is the ``"point"`` rule of :mod:`hydromodpy.core.time.time_method`,
    the rule every series followed before the period-mean rule was written.
    The nearest sample is found by position, not by ``pandas.merge_asof``,
    which refused to join millisecond Parquet stamps with nanosecond ones.
    """
    labels = pd.DatetimeIndex(pd.to_datetime(index))
    series = pd.Series(values).dropna()
    series.index = _naive(series.index)
    series = series.sort_index()
    target = _naive(labels)
    if series.empty or len(target) == 0:
        return pd.Series(np.nan, index=labels, dtype=float)

    stamps = target.sort_values().unique()
    run_step = _median_spacing(stamps)
    chronicle_step = _median_spacing(series.index)
    if run_step is not None and chronicle_step is not None and run_step > chronicle_step:
        found = _centred_window_means(series, stamps)
    else:
        reach = tolerance
        if reach is None:
            reach = run_step if run_step is not None else chronicle_step
        if reach is None:
            reach = pd.Timedelta(0)
        found = _nearest_within(series, stamps, reach)
    per_stamp = pd.Series(found, index=stamps, dtype=float)
    return pd.Series(per_stamp.reindex(target).to_numpy(dtype=float), index=labels)


def observed_on_periods(
    values: Any,
    index: Any,
    *,
    method: str,
    start: Any = None,
    tolerance: pd.Timedelta | pd.DateOffset | None = None,
) -> pd.Series:
    """Put an observation chronicle on end-stamped periods, by time method.

    ``"mean"`` averages each period ``[s, e)`` (:func:`period_value_on_index`,
    ``tolerance`` is the interval one observation stands for). ``"point"``
    reads the state at each stamp (:func:`period_point_on_index`,
    ``tolerance`` bounds the nearest sample, and ``start`` is not used).
    """
    if check_time_method(method) == "point":
        return period_point_on_index(values, index, tolerance=tolerance)
    return period_value_on_index(values, index, start=start, reach=tolerance)
