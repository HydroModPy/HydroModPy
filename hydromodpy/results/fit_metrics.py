"""Goodness of fit of a run against the observations stored beside it, under the metric rule.

Why
---
The score of a run used to be computed on whatever overlap the simulated and
observed series happened to share, spin-up included, and the run that held it
did not say which days counted. Here every score follows the rule of the run
(:class:`~hydromodpy.results.metric_rule.MetricRule`): only the periods inside
``[metrics] window`` count, the headline NSE is read at ``[metrics] station``
(default ``[site] gauge``), and each row records its window, its sample count
and the rule version. Without a window nothing is scored.

What is paired
--------------
An observed variable is stored with the ``_obs`` suffix (``discharge_obs`` at
gauge ``J0014010``). It meets the simulated variable of the same name at the
same station, or, when the simulated variable sits at one station only (the
catchment discharge), at that station.

Which periods count
-------------------
A simulated stamp is the END of its stress period. The observations are put
on those periods by
:func:`~hydromodpy.results.derive.time_alignment.align_observed_simulated`,
with the time method of the variable. A period averaged over its length (a
discharge) counts when it lies entirely inside the window; a state read at
its stamp (a head, a lake stage) counts when its stamp falls inside it. The
rule is :func:`~hydromodpy.core.time.period_aggregation.periods_in_window`,
which a calibration session reads its own window by too. The
periods are those of the simulated series, so a gap in the observations never
moves the start of the period after it. A pair with fewer than
:data:`MIN_PAIRED_PERIODS` periods in the window (a steady run) is not scored.

Who calls it
------------
The workflow, after extraction and before the seal, passes the result to the
:class:`~hydromodpy.results.record.RunRecord`: ``rows`` go to ``metrics`` and
``score`` to ``score``. Nothing here opens the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq

from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import period_edges, periods_in_window
from hydromodpy.core.time.time_method import TimeMethod
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
    time_method_for,
)
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import METRIC_NAMES, MetricRule, MetricScore, score_run
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME

logger = get_logger(__name__)

OBSERVED_SUFFIX: Final[str] = "_obs"
"""Suffix the ingestion appends to an observed variable (``discharge_obs``)."""

TIMESERIES_TABLE: Final[str] = "timeseries"
"""Stem of the run table that holds the simulated and observed series."""

HEADLINE_VARIABLE: Final[str] = "discharge"
"""Variable the headline NSE is read on when the rule station observes several."""

HEADLINE_METRIC: Final[str] = "nse"
"""Metric the headline score of a run is."""

MIN_PAIRED_PERIODS: Final[int] = 2
"""Fewest paired periods in the window a pair is scored on; a steady run has one."""

_COLUMNS: Final[tuple[str, ...]] = ("station_id", "variable", "time", "value")


@dataclass(frozen=True, slots=True)
class RunScores:
    """The scores of one run under its rule.

    ``rows`` holds one entry per paired series and metric, empty without a
    window. ``score`` is the NSE at the rule station: its value is ``None``
    without a window, without a station, or when that station observes nothing
    the run simulates.
    """

    rows: tuple[MetricRow, ...]
    score: MetricScore


def fit_metrics(run_dir: str | Path, *, rule: MetricRule, period_start: Any = None) -> RunScores:
    """Score the series stored in ``tables.parquet/timeseries.parquet`` of *run_dir*.

    *period_start* is the start of the first simulated period; without it the
    first period is inferred from the spacing of the stamps. A run without the
    table has no series to score.
    """
    path = Path(run_dir) / TABLES_DIRNAME / f"{TIMESERIES_TABLE}{PARQUET_FILE_SUFFIX}"
    if not path.is_file():
        return score_timeseries(pd.DataFrame(columns=list(_COLUMNS)), rule=rule)
    table = pq.read_table(path)
    frame = table.to_pandas()
    if "component" in frame.columns:
        # A component is a part of a series; the series itself has none.
        frame = frame[frame["component"].isna()]
    return score_timeseries(frame[list(_COLUMNS)], rule=rule, period_start=period_start)


def score_timeseries(
    timeseries: pd.DataFrame, *, rule: MetricRule, period_start: Any = None
) -> RunScores:
    """Score every simulated series of *timeseries* against its observed twin.

    *timeseries* has the columns ``station_id``, ``variable``, ``time`` and
    ``value``, simulated and observed rows together.
    """
    pairs = _pairs(timeseries)
    rows: list[MetricRow] = []
    at_station: dict[str, MetricScore] = {}
    for station, variable, simulated, observed in pairs:
        scores = _score_pair(simulated, observed, rule, station, variable, period_start)
        nse = next(item for item in scores if item.metric == HEADLINE_METRIC)
        if rule.window is not None and nse.nse_n > 0:
            rows.extend(_row(item) for item in scores)
        if rule.station is not None and station == rule.station:
            at_station[variable] = nse
    return RunScores(rows=tuple(rows), score=_headline(at_station, rule))


def _pairs(timeseries: pd.DataFrame) -> list[tuple[str, str, pd.Series, pd.Series]]:
    """Return ``(station, variable, simulated, observed)`` for every observed series."""
    if timeseries.empty:
        return []
    frame = timeseries.assign(
        station_id=timeseries["station_id"].astype(str),
        variable=timeseries["variable"].astype(str),
    )
    observed_names = sorted(
        name for name in frame["variable"].unique() if name.endswith(OBSERVED_SUFFIX)
    )
    pairs: list[tuple[str, str, pd.Series, pd.Series]] = []
    for observed_name in observed_names:
        variable = observed_name[: -len(OBSERVED_SUFFIX)]
        simulated_rows = frame[frame["variable"] == variable]
        sim_stations = sorted(simulated_rows["station_id"].unique())
        observed_rows = frame[frame["variable"] == observed_name]
        for station in sorted(observed_rows["station_id"].unique()):
            if station in sim_stations:
                sim_station = station
            elif len(sim_stations) == 1:
                sim_station = sim_stations[0]
            else:
                logger.debug(
                    "Not scoring %s at %s: the run simulates it at %d station(s), none of them %s.",
                    variable,
                    station,
                    len(sim_stations),
                    station,
                )
                continue
            simulated = _series(simulated_rows[simulated_rows["station_id"] == sim_station])
            observed = _series(observed_rows[observed_rows["station_id"] == station])
            pairs.append((station, variable, simulated, observed))
    return pairs


def _series(rows: pd.DataFrame) -> pd.Series:
    """One series, indexed by its UTC stamps."""
    index = pd.DatetimeIndex(pd.to_datetime(rows["time"], utc=True))
    return pd.Series(rows["value"].to_numpy(dtype=float), index=index).sort_index()


def _score_pair(
    simulated: pd.Series,
    observed: pd.Series,
    rule: MetricRule,
    station: str,
    variable: str,
    period_start: Any,
) -> list[MetricScore]:
    """Score one pair on every metric, on the periods the rule counts.

    Fewer than :data:`MIN_PAIRED_PERIODS` periods in the window score nothing:
    every metric is ``None`` with zero samples.
    """
    method = time_method_for(variable)
    paired = align_observed_simulated(observed, simulated, method=method, start=period_start)
    dated = _dated_in_window(paired, simulated, rule, method, period_start)
    scores = score_run(
        dated["sim"], dated["obs"], rule, METRIC_NAMES, station=station, variable=variable
    )
    if min(item.nse_n for item in scores) >= MIN_PAIRED_PERIODS:
        return scores
    nothing = dated.iloc[0:0]
    return score_run(
        nothing["sim"], nothing["obs"], rule, METRIC_NAMES, station=station, variable=variable
    )


def _dated_in_window(
    paired: pd.DataFrame,
    simulated: pd.Series,
    rule: MetricRule,
    method: TimeMethod,
    period_start: Any,
) -> pd.DataFrame:
    """Keep the pairs the window holds and date each by the instant the rule reads it at.

    Which pairs count is :func:`~hydromodpy.core.time.period_aggregation.periods_in_window`,
    the rule a calibration session reads its window by too. A mean over a
    period is then dated by the start of the period, a point by its stamp. The
    periods are cut on every stamp of *simulated*, not on the paired ones, so
    a gap in the observations leaves the next period where it is.
    """
    empty = pd.DataFrame(
        {"sim": pd.Series(dtype=float), "obs": pd.Series(dtype=float)},
        index=pd.DatetimeIndex([]),
    )
    if paired.empty:
        return empty
    stamps = pd.DatetimeIndex(paired.index)
    if rule.window is None:
        return paired.set_axis(stamps)
    grid = pd.DatetimeIndex(normalize_datetime_series(simulated).dropna().index)
    inside = periods_in_window(
        stamps,
        method=method,
        start=rule.window.start,
        end=rule.window.end,
        grid=grid,
        period_start=period_start,
    )
    if method != "mean":
        return paired.set_axis(stamps)[inside]
    starts = _period_starts(simulated, period_start)
    if starts is None:
        return empty
    return paired.set_axis(pd.DatetimeIndex(starts.reindex(stamps)))[inside]


def _period_starts(simulated: pd.Series, period_start: Any) -> pd.Series | None:
    """Start of every simulated period, indexed by its end stamp.

    ``None`` when the series has one stamp and no *period_start*: a steady
    value has no period to place.
    """
    stamps = pd.DatetimeIndex(normalize_datetime_series(simulated).dropna().index).as_unit("ns")
    try:
        edges = period_edges(stamps, start=period_start)
    except ValueError:
        return None
    return pd.Series(edges[:-1], index=edges[1:])


def _row(item: MetricScore) -> MetricRow:
    """The manifest row of one score."""
    return MetricRow(
        station=item.station,
        variable=item.variable,
        metric=item.metric,
        value=item.value,
        nse_window_start=item.nse_window_start,
        nse_window_end=item.nse_window_end,
        nse_n=item.nse_n,
        metric_rule_version=item.metric_rule_version,
    )


def _headline(at_station: dict[str, MetricScore], rule: MetricRule) -> MetricScore:
    """Return the NSE at the rule station, or an empty score that says why there is none."""
    if len(at_station) == 1:
        return next(iter(at_station.values()))
    if HEADLINE_VARIABLE in at_station:
        return at_station[HEADLINE_VARIABLE]
    if at_station:
        logger.warning(
            "No headline NSE: station %s observes %s and none of them is %s.",
            rule.station,
            ", ".join(sorted(at_station)),
            HEADLINE_VARIABLE,
        )
    window = rule.window
    return MetricScore(
        metric="nse",
        value=None,
        station=rule.station,
        nse_window_start=None if window is None else window.start,
        nse_window_end=None if window is None else window.end,
        nse_n=0,
        metric_rule_version=rule.version,
    )


__all__ = [
    "HEADLINE_METRIC",
    "HEADLINE_VARIABLE",
    "MIN_PAIRED_PERIODS",
    "OBSERVED_SUFFIX",
    "TIMESERIES_TABLE",
    "RunScores",
    "fit_metrics",
    "score_timeseries",
]
