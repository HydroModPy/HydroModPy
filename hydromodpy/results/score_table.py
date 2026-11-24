"""Score the stored series of a run on any window, month mask and metric, after the fact.

A run keeps its simulated and observed series in ``tables.parquet/timeseries.parquet``.
Scoring them again needs no model run: the pairing is the one of the seal
(:func:`~hydromodpy.results.score.pair`), so a simulated stamp closes its period and
a mean counts when its period lies inside the window. Here a table says what was
paired, one row per station, variable, metric and window, whatever the window is.
What a sealed run writes is not touched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import SIMULATED
from hydromodpy.core.scoring.metric_table import (
    CONSECUTIVE_METRIC_NAMES,
    METRIC_SPECS,
    NETWORK_METRIC_NAMES,
    SERIES_METRIC_NAMES,
)
from hydromodpy.core.time.period_aggregation import check_months
from hydromodpy.results.derive.time_alignment import time_method_for
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.score import pair, score, series_pairs

logger = get_logger(__name__)

SCORE_COLUMNS: Final[tuple[str, ...]] = (
    "station",
    "variable",
    "metric",
    "window_name",
    "window_start",
    "window_end",
    "months",
    "value",
    "n_samples",
    "n_sim_nan",
)
"""The columns of one run's score table, in order."""

WindowsArg = Mapping[str, tuple[Any, Any]] | Sequence[DateWindow] | None

NetworkWindowArg = tuple[Any, Any] | Mapping[str, tuple[Any, Any]] | None
"""A ``(start, end)`` pair, a mapping ``name -> (start, end)``, or None: the windows of the network score."""


def check_metrics(metrics: Sequence[str] | None, months: Sequence[int] | None) -> tuple[str, ...]:
    """Return the metrics to compute, refusing by name those a series cannot give.

    ``None`` means every metric a series pair can give. A network metric is
    refused because it reads a stream network, not a series. A metric that needs
    consecutive days is refused on a series cut by months, and left out when no
    metric was named.
    """
    if metrics is None:
        if months is None:
            return SERIES_METRIC_NAMES
        left = tuple(name for name in SERIES_METRIC_NAMES if name not in CONSECUTIVE_METRIC_NAMES)
        logger.info(
            "Metrics left out on months %s, they need consecutive days: %s.",
            list(months),
            ", ".join(sorted(CONSECUTIVE_METRIC_NAMES)),
        )
        return left
    names = tuple(metrics)
    for name in names:
        if name in NETWORK_METRIC_NAMES:
            raise ValueError(
                f"{name!r} scores a stream network, not a series, so it is not computed "
                "here. Score it with score_network."
            )
        if name not in METRIC_SPECS:
            raise ValueError(f"unknown metric {name!r}; known: {', '.join(SERIES_METRIC_NAMES)}")
        if months is not None and name in CONSECUTIVE_METRIC_NAMES:
            raise ValueError(
                f"{name!r} filters the series day by day and needs consecutive days, "
                f"so it is refused on months {list(months)}. Score it on whole windows."
            )
    return names


def _day(value: Any) -> date | None:
    """Return *value* as a day, ``None`` when it is open."""
    if value is None:
        return None
    return pd.Timestamp(value).date()


def close_window(start: Any, end: Any, first: Any, last: Any) -> tuple[Any, Any]:
    """Close an open window bound: an open start is *first*, an open end is *last*.

    *first* and *last* come from the simulated rows only. This is the one place
    where the rule is written, for ``Run.score`` and the network score.
    """
    return (first if start is None else start, last if end is None else end)


def resolve_windows(
    windows: WindowsArg, timeseries: pd.DataFrame, period_start: Any = None
) -> list[tuple[str, DateWindow]]:
    """Return the named, closed windows to score, an open bound read from the series.

    A mapping gives ``name -> (start, end)``, ISO strings or dates, either bound
    ``None``. A list of :class:`DateWindow` is named ``start/end``. An open start
    is the start of the first period (``period_start``, else the first stamp), an
    open end the last stamp of the run.
    """
    if not windows:
        raise ValueError("windows is empty: name at least one window, or pass None.")
    simulated = timeseries[timeseries["source"] == SIMULATED] if len(timeseries) else timeseries
    stamps = pd.to_datetime(simulated["time"], utc=True)
    first = None if stamps.empty else stamps.min().date()
    last = None if stamps.empty else stamps.max().date()
    if first is not None and period_start is not None:
        first = min(first, pd.Timestamp(period_start).date())
    items = (
        list(windows.items())
        if isinstance(windows, Mapping)
        else [(f"{window.start}/{window.end}", window) for window in windows]
    )
    resolved: list[tuple[str, DateWindow]] = []
    for name, bounds in items:
        if isinstance(bounds, DateWindow):
            resolved.append((str(name), bounds))
            continue
        start, end = (_day(bound) for bound in bounds)
        start, end = close_window(start, end, first, last)
        if start is None or end is None:
            raise ValueError(f"window {name!r} is open and the run holds no series to close it.")
        resolved.append((str(name), DateWindow(start=start, end=end)))
    return resolved


def score_table(
    timeseries: pd.DataFrame,
    windows: list[tuple[str, DateWindow]],
    *,
    metrics: tuple[str, ...],
    months: Sequence[int] | None = None,
    station: str | None = None,
    period_start: Any = None,
) -> pd.DataFrame:
    """Score the series of *timeseries* on each window, in the long form of ``SCORE_COLUMNS``.

    *timeseries* is the table :func:`~hydromodpy.results.score.read_timeseries`
    reads. Every observed series that meets a simulated one is scored, or only the
    one at *station*. A value is empty where it cannot be computed, for example
    ``nse_seasonal`` on less than two cycles or a baseflow index on a monthly step.
    """
    wanted = None if months is None else check_months(months)
    label = None if wanted is None else ",".join(str(month) for month in wanted)
    frame = timeseries
    if station is not None and not frame.empty:
        frame = frame[frame["station_id"].astype(str) == str(station)]
    pairs, _ = series_pairs(frame)
    rows: list[dict[str, Any]] = []
    for name, window in windows:
        rule = MetricRule(window=window, window_name=name)
        for where, variable, simulated, observed in pairs:
            paired = pair(
                simulated,
                observed,
                method=time_method_for(variable),
                window=window,
                period_start=period_start,
                months=wanted,
            )
            scores = score(paired, rule, metrics, station=where, variable=variable)
            rows.extend(
                {
                    "station": item.station,
                    "variable": item.variable,
                    "metric": item.metric,
                    "window_name": name,
                    "window_start": window.start,
                    "window_end": window.end,
                    "months": label,
                    "value": item.value,
                    "n_samples": item.n_samples,
                    "n_sim_nan": paired.n_simulated_nan,
                }
                for item in scores
            )
    return pd.DataFrame(rows, columns=list(SCORE_COLUMNS))


__all__ = [
    "SCORE_COLUMNS",
    "check_metrics",
    "close_window",
    "resolve_windows",
    "score_table",
]
