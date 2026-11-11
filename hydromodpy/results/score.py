"""The one pairing of a simulated series with its observations, and the score of a run.

Why
---
A calibration trial and the run it promotes read the same observations on the
same days. They used to pair them in two places, with two copies of the same
steps, so nothing held the cost of the trial and the score of the run to one
another. Here :func:`pair` is the pairing of both: the calibration calls it on
the series of a trial (:mod:`hydromodpy.calibration.metrics.observed_pairing`),
the run calls it on the series it stored. On the same inputs both give the same
pairs, bit for bit.

What is paired
--------------
A simulated stamp is the END of its stress period. The observations are put on
those periods by
:func:`~hydromodpy.results.derive.time_alignment.align_observed_simulated`, with
the time method of the variable. A period averaged over its length (a
discharge) counts when it lies entirely inside the window, a state read at its
stamp (a head, a lake stage) counts when its stamp falls inside it. The rule is
:func:`~hydromodpy.core.time.period_aggregation.periods_in_window`. The periods
are those of the simulated series, so a gap in the observations never moves the
start of the period after it. A period of the window the record covers and the
simulated value leaves NaN (a dry cell) is dropped and counted.

How a run is scored
-------------------
An observed series is stored with ``source = observed``. It meets the simulated
series of the same variable at the same station, and no other, so a gauge is
never scored against the outlet. An observed gauge that meets no simulated
series is listed in :attr:`RunScores.unscored`, logged and sealed as the failed,
non-fatal check :data:`UNSCORED_OBSERVATIONS_CHECK`. :func:`score` dates a mean
by the start of its period and scores a pair only when the window holds at
least :data:`MIN_PAIRED_PERIODS` periods.

The run is scored on ``[metrics] window``, the headline rows. A run a session
promoted is also scored on each calibration period of its seal
(``calibrated_by.windows``), one row per period, on the days the case of the
run read. These rows read the station of ``[metrics]``, or every paired station
when it names none, and not the observations the search fitted: the seal does
not carry them yet. A search that fits a head or another gauge therefore gets
rows on the days it read but on the series of ``[metrics]``. Each row records
its window, its sample count and the rule version
(:class:`~hydromodpy.results.metric_rule.MetricRule`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import OBSERVED, SIMULATED
from hydromodpy.core.scoring import metrics as kernels
from hydromodpy.core.scoring.metric_table import METRIC_SPECS, RUN_METRIC_NAMES
from hydromodpy.core.time.period_aggregation import period_edges, periods_in_window
from hydromodpy.core.time.time_method import TimeMethod
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
    simulated_nan_stamps,
    time_method_for,
)
from hydromodpy.results.metric_rule import (
    CALIBRATION_ROLE,
    HEADLINE_WINDOW,
    DateWindow,
    MetricRule,
    MetricScore,
)
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.results.storage.parquet_io import read_checked_table

if TYPE_CHECKING:
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)

TIMESERIES_TABLE: Final[str] = "timeseries"
"""Stem of the run table that holds the simulated and observed series."""

HEADLINE_VARIABLE: Final[str] = "discharge"
"""Variable the headline NSE is read on when the rule station observes several."""

HEADLINE_METRIC: Final[str] = "nse"
"""Metric the headline score of a run is."""

MIN_PAIRED_PERIODS: Final[int] = 2
"""Fewest paired periods in the window a pair is scored on; a steady run has one."""

UNSCORED_OBSERVATIONS_CHECK: Final[str] = "observations_scored"
"""Name of the check a run fails, non-fatally, when an observed gauge meets no simulated series."""

_COLUMNS: Final[tuple[str, ...]] = ("station_id", "variable", "source", "time", "value")

_KERNELS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "nse": kernels.nse,
    "kge": lambda sim, obs: kernels.kge(sim, obs)["kge"],
    "rmse": kernels.rmse,
    "nse_log": kernels.log_nse,
    "mae": kernels.mae,
    "bias": kernels.bias,
    "pbias": kernels.pbias,
    "correlation": kernels.correlation,
    "kge_r": lambda sim, obs: kernels.kge(sim, obs)["r"],
    "kge_alpha": lambda sim, obs: kernels.kge(sim, obs)["alpha"],
    "kge_beta": lambda sim, obs: kernels.kge(sim, obs)["beta"],
}

HEADLINE_METRICS: Final[tuple[str, ...]] = ("nse", "kge", "rmse", "nse_log")
"""The metrics :func:`score` computes unless told otherwise."""


@dataclass(frozen=True, slots=True)
class Pairs:
    """Observed and simulated values of one series, on the periods a window holds.

    ``frame`` has the columns ``obs`` and ``sim``, indexed by the end stamps of
    the periods. ``n_simulated_nan`` counts the periods of the window the record
    covers and the simulated value leaves NaN. ``simulated`` and
    ``period_start`` are what the periods are cut on, kept to date a mean.
    """

    frame: pd.DataFrame
    method: TimeMethod
    n_simulated_nan: int
    simulated: pd.Series
    period_start: Any = None

    def dated(self) -> pd.DataFrame:
        """Return the pairs dated by the instant they are read at.

        A mean over a period is dated by the start of its period, a point by its
        stamp. Means are empty when their periods cannot be placed.
        """
        if self.method != "mean" or self.frame.empty:
            return self.frame
        starts = _period_starts(self.simulated, self.period_start)
        if starts is None:
            return self.frame.iloc[0:0]
        stamps = pd.DatetimeIndex(self.frame.index)
        return self.frame.set_axis(pd.DatetimeIndex(starts.reindex(stamps)))


def _bounds(window: DateWindow | tuple[Any, Any] | None) -> tuple[Any, Any] | None:
    """Return the two bounds of *window*, either of which may be open."""
    if window is None or isinstance(window, tuple):
        return window
    return window.start, window.end


def pair(
    simulated: pd.Series,
    observed: pd.Series,
    *,
    method: TimeMethod,
    window: DateWindow | tuple[Any, Any] | None,
    period_start: Any = None,
) -> Pairs:
    """Pair *observed* with *simulated* on the periods *window* holds.

    *window* is a :class:`DateWindow`, two bounds where ``None`` is open, or
    ``None`` to keep every period both series share. *period_start* is the start
    of the first simulated period; without it the first period is inferred from
    the spacing of the stamps.
    """
    bounds = _bounds(window)
    frame = align_observed_simulated(observed, simulated, method=method, start=period_start)
    dry = simulated_nan_stamps(observed, simulated, method=method, start=period_start)
    if bounds is not None and len(dry):
        dry = dry[
            periods_in_window(
                dry,
                method=method,
                start=bounds[0],
                end=bounds[1],
                grid=normalize_datetime_series(simulated).index,
                period_start=period_start,
            )
        ]
    if bounds is not None and not frame.empty:
        frame = frame.loc[
            periods_in_window(
                frame.index,
                method=method,
                start=bounds[0],
                end=bounds[1],
                grid=normalize_datetime_series(simulated).dropna().index,
                period_start=period_start,
            )
        ]
    return Pairs(
        frame=frame,
        method=method,
        n_simulated_nan=len(dry),
        simulated=simulated,
        period_start=period_start,
    )


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


def score_metric(
    simulated: pd.Series,
    observed: pd.Series,
    rule: MetricRule,
    metric: str,
    *,
    station: str | None = None,
    variable: str | None = None,
) -> MetricScore:
    """Score *simulated* against *observed* under *rule* on one metric.

    Both series are indexed by the instant they are read at. Only the days of
    ``rule.window`` count, and only the instants both series carry a finite
    value at. Without a window the score is ``None`` with zero samples: a run
    nobody declared a window for has no rank. *station* and *variable* name
    where the series were read; they are recorded, not checked.
    """
    kernel = _KERNELS.get(metric)
    if kernel is None:
        raise ValueError(f"unknown metric {metric!r}; known: {', '.join(RUN_METRIC_NAMES)}")
    clips = METRIC_SPECS[metric].clips_negatives
    window = rule.window
    n = 0
    value: float | None = None
    n_clipped = 0 if clips else None
    if window is not None:
        sim = _within(simulated, window)
        obs = _within(observed, window)
        paired = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1, join="inner").dropna()
        n = int(len(paired))
        if n > 0:
            sim_values, obs_values = paired["sim"].to_numpy(), paired["obs"].to_numpy()
            if clips:
                n_clipped = kernels.clip_negatives(sim_values, obs_values)[2]
            raw = float(kernel(sim_values, obs_values))
            value = None if math.isnan(raw) else raw
    return MetricScore(
        metric=metric,
        value=value,
        station=station,
        variable=variable,
        window_name=rule.window_name,
        window_role=rule.window_role,
        window_start=None if window is None else window.start,
        window_end=None if window is None else window.end,
        n_samples=n,
        n_clipped=n_clipped,
        metric_rule_version=rule.version,
    )


def score(
    pairs: Pairs,
    rule: MetricRule,
    metrics: Sequence[str] = HEADLINE_METRICS,
    *,
    station: str | None = None,
    variable: str | None = None,
) -> list[MetricScore]:
    """Score one pair on every metric of *metrics*, in their order.

    Each score follows :func:`score_metric` on the dated pairs. Fewer than
    :data:`MIN_PAIRED_PERIODS` periods in the window score nothing: every metric
    is ``None`` with zero samples.
    """
    dated = pairs.dated()
    scores = [
        score_metric(dated["sim"], dated["obs"], rule, metric, station=station, variable=variable)
        for metric in metrics
    ]
    if not scores or min(item.n_samples for item in scores) >= MIN_PAIRED_PERIODS:
        return scores
    nothing = dated.iloc[0:0]
    return [
        score_metric(
            nothing["sim"], nothing["obs"], rule, metric, station=station, variable=variable
        )
        for metric in metrics
    ]


def _within(series: pd.Series, window: DateWindow) -> pd.Series:
    """Return the entries of *series* dated inside *window*, both days included."""
    index = series.index
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError(f"a scored series is indexed by time, not by {type(index).__name__}")
    start = pd.Timestamp(datetime.combine(window.start, time.min))
    end_exclusive = pd.Timestamp(datetime.combine(window.end + timedelta(days=1), time.min))
    if index.tz is not None:
        start = start.tz_localize(index.tz)
        end_exclusive = end_exclusive.tz_localize(index.tz)
    mask = (index >= start) & (index < end_exclusive)
    return series[mask]


@dataclass(frozen=True, slots=True)
class UnscoredObservation:
    """An observed series no simulated series of the run meets."""

    station: str
    variable: str
    simulated_at: tuple[str, ...]
    """Stations the run simulates *variable* at."""

    def sentence(self) -> str:
        """The reason, in words."""
        where = ", ".join(self.simulated_at) or "no station"
        return (
            f"{self.variable} observed at {self.station} is not scored: "
            f"the run simulates it at {where}, not at {self.station}"
        )


@dataclass(frozen=True, slots=True)
class RunScores:
    """The scores of one run under one rule.

    ``rows`` holds one entry per paired series and metric, empty without a
    window. ``score`` is the NSE at the rule station: its value is ``None``
    without a window, without a station, or when that station observes nothing
    the run simulates. ``unscored`` lists the observed series of the run that
    meet no simulated series.
    """

    rows: tuple[MetricRow, ...]
    score: MetricScore
    unscored: tuple[UnscoredObservation, ...] = ()

    def unscored_message(self) -> str | None:
        """The message of :data:`UNSCORED_OBSERVATIONS_CHECK`, ``None`` when every series met."""
        if not self.unscored:
            return None
        return "; ".join(item.sentence() for item in self.unscored) + "."


_SeriesPair = tuple[str, str, pd.Series, pd.Series]


def read_timeseries(run_dir: str | Path) -> pd.DataFrame:
    """Return the series stored in ``tables.parquet/timeseries.parquet`` of *run_dir*.

    The frame has the columns ``station_id``, ``variable``, ``source``, ``time``
    and ``value``. A run without the table gives an empty frame. A component
    row is a part of a series and is left out.
    """
    path = Path(run_dir) / TABLES_DIRNAME / f"{TIMESERIES_TABLE}{PARQUET_FILE_SUFFIX}"
    if not path.is_file():
        return pd.DataFrame(columns=list(_COLUMNS))
    frame = read_checked_table(path).to_pandas()
    if "component" in frame.columns:
        frame = frame[frame["component"].isna()]
    return frame[list(_COLUMNS)]


def score_timeseries(
    timeseries: pd.DataFrame, *, rule: MetricRule, period_start: Any = None
) -> RunScores:
    """Score every simulated series of *timeseries* against its observed twin.

    *timeseries* has the columns ``station_id``, ``variable``, ``source``,
    ``time`` and ``value``, simulated and observed rows together.
    *period_start* is the start of the first simulated period.
    """
    pairs, unscored = _series_pairs(timeseries)
    return _score_series(pairs, tuple(unscored), rule, period_start)


def _score_series(
    pairs: Sequence[_SeriesPair],
    unscored: tuple[UnscoredObservation, ...],
    rule: MetricRule,
    period_start: Any,
) -> RunScores:
    """Score each ``(station, variable, simulated, observed)`` under *rule*."""
    rows: list[MetricRow] = []
    at_station: dict[str, MetricScore] = {}
    for station, variable, simulated, observed in pairs:
        paired = pair(
            simulated,
            observed,
            method=time_method_for(variable),
            window=rule.window,
            period_start=period_start,
        )
        scores = score(paired, rule, RUN_METRIC_NAMES, station=station, variable=variable)
        nse = next(item for item in scores if item.metric == HEADLINE_METRIC)
        if rule.window is not None and nse.n_samples > 0:
            lost = paired.n_simulated_nan
            if lost:
                logger.warning(
                    "%s at %s: %d period(s) of the window dropped because the simulated "
                    "value is NaN (a dry cell?); the rows say so in n_sim_nan.",
                    variable,
                    station,
                    lost,
                )
            rows.extend(_row(item, n_sim_nan=lost) for item in scores)
        if rule.station is not None and station == rule.station:
            at_station[variable] = nse
    return RunScores(rows=tuple(rows), score=_headline(at_station, rule), unscored=unscored)


def _series_pairs(
    timeseries: pd.DataFrame,
) -> tuple[list[_SeriesPair], list[UnscoredObservation]]:
    """Return ``(station, variable, simulated, observed)`` for every observed series that meets one.

    The second list holds the observed series of a variable the run simulates
    that meet no simulated series; each is logged as a warning.
    """
    if timeseries.empty:
        return [], []
    frame = timeseries.assign(
        station_id=timeseries["station_id"].astype(str),
        variable=timeseries["variable"].astype(str),
    )
    measured = frame[frame["source"] == OBSERVED]
    pairs: list[_SeriesPair] = []
    unscored: list[UnscoredObservation] = []
    for variable in sorted(measured["variable"].unique()):
        simulated_rows = frame[(frame["variable"] == variable) & (frame["source"] == SIMULATED)]
        sim_stations = sorted(simulated_rows["station_id"].unique())
        observed_rows = measured[measured["variable"] == variable]
        for station in sorted(observed_rows["station_id"].unique()):
            if not sim_stations:
                logger.debug(
                    "Not scoring %s at %s: the run does not simulate it.", variable, station
                )
                continue
            if station not in sim_stations:
                missed = UnscoredObservation(station, variable, tuple(sim_stations))
                logger.warning("%s.", missed.sentence())
                unscored.append(missed)
                continue
            simulated = _series(simulated_rows[simulated_rows["station_id"] == station])
            observed = _series(observed_rows[observed_rows["station_id"] == station])
            pairs.append((station, variable, simulated, observed))
    return pairs, unscored


def _series(rows: pd.DataFrame) -> pd.Series:
    """One series, indexed by its UTC stamps."""
    index = pd.DatetimeIndex(pd.to_datetime(rows["time"], utc=True))
    return pd.Series(rows["value"].to_numpy(dtype=float), index=index).sort_index()


def _row(item: MetricScore, *, n_sim_nan: int) -> MetricRow:
    """The manifest row of one score; *n_sim_nan* is what a NaN simulated value took out."""
    return MetricRow(
        station=item.station,
        variable=item.variable,
        metric=item.metric,
        value=item.value,
        window_name=item.window_name,
        window_role=item.window_role,
        window_start=item.window_start,
        window_end=item.window_end,
        n_samples=item.n_samples,
        n_clipped=item.n_clipped,
        n_sim_nan=n_sim_nan,
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
        metric=HEADLINE_METRIC,
        value=None,
        station=rule.station,
        window_name=rule.window_name,
        window_role=rule.window_role,
        window_start=None if window is None else window.start,
        window_end=None if window is None else window.end,
        n_samples=0,
        metric_rule_version=rule.version,
    )


def calibration_rules(headline: MetricRule, by: CalibratedBy | None) -> tuple[MetricRule, ...]:
    """Return one rule per calibration period of the session that promoted the run.

    Each rule reads the station of *headline* on the days the case of the run
    read, under the name of the period and the role ``calibration``. It does not
    read the observations the search fitted, which the seal does not carry, and
    a *headline* that names no station scores every paired station. A run no
    session promoted has none. A period named like the headline window would
    replace the headline rows, so it is left out with a warning.
    """
    if by is None:
        return ()
    rules: list[MetricRule] = []
    for name, period in by.windows.items():
        if period.role != CALIBRATION_ROLE:
            continue
        if name == HEADLINE_WINDOW:
            logger.warning(
                "The calibration period %r has the name of the headline window, so the run "
                "is not scored on it again.",
                name,
            )
            continue
        rules.append(
            MetricRule(
                station=headline.station,
                window=DateWindow(start=period.start, end=period.end),
                version=headline.version,
                window_name=name,
                window_role=CALIBRATION_ROLE,
            )
        )
    return tuple(rules)


def score_run_under_its_rule(cfg: Any, *, store: RunStore) -> None:
    """Score the series of the run against its observations and record the result.

    The headline rows follow ``[metrics]``, and a promoted run gains the rows of
    each calibration period of its seal (:func:`calibration_rules`). Every row
    goes through the one writer of a metric, into the facts and the ``metrics``
    table, and the NSE at the rule station goes to the headline score, all
    sealed by the record. An observed gauge that meets no simulated series fails
    the non-fatal check :data:`UNSCORED_OBSERVATIONS_CHECK`. A score that cannot
    be computed is logged and the run keeps its results: the seal says
    ``nse = NULL`` and the table says why.
    """
    facts = store.facts
    site = facts.site
    rule = MetricRule.from_config(cfg, gauge=None if site is None else site.gauge)
    try:
        pairs, unscored = _series_pairs(read_timeseries(store.run_dir))
        headline = _score_series(pairs, tuple(unscored), rule, facts.period_start)
        searched = [
            _score_series(pairs, (), period, facts.period_start)
            for period in calibration_rules(rule, facts.calibrated_by)
        ]
    except Exception:
        logger.warning("Could not score the run against its observations", exc_info=True)
        return
    for scores in (headline, *searched):
        for row in scores.rows:
            store.write_metric(store.sim_id, row)
    facts.score = headline.score
    message = headline.unscored_message()
    if message is not None:
        facts.note_validity(
            UNSCORED_OBSERVATIONS_CHECK, False, float(len(headline.unscored)), message
        )


__all__ = [
    "HEADLINE_METRIC",
    "HEADLINE_METRICS",
    "HEADLINE_VARIABLE",
    "MIN_PAIRED_PERIODS",
    "TIMESERIES_TABLE",
    "UNSCORED_OBSERVATIONS_CHECK",
    "Pairs",
    "RunScores",
    "UnscoredObservation",
    "calibration_rules",
    "pair",
    "read_timeseries",
    "score",
    "score_metric",
    "score_run_under_its_rule",
    "score_timeseries",
]
