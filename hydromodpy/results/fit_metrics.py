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
An observed series is stored with ``source = observed`` (``discharge`` at gauge
``J0014010``). It meets the simulated series of the same variable at the same
station, and no other: the derive step writes each station's own series
(:func:`~hydromodpy.calibration.runners.promotion.write_station_series`), so a gauge is
never scored against the outlet. An observed gauge that meets no simulated series is listed in
:attr:`RunScores.unscored`, logged as a warning and sealed as the failed,
non-fatal check :data:`UNSCORED_OBSERVATIONS_CHECK`, which the README of the
run prints.

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
A period of the window the record covers and the simulated value leaves NaN
(a dry cell) is dropped from the pairs, counted on each row as ``n_sim_nan``
and warned about.

Who calls it
------------
The workflow, after extraction and before the seal, passes the result to the
:class:`~hydromodpy.results.record.record.RunRecord`: ``rows`` go to ``metrics`` and
``score`` to ``score``. Nothing here opens the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import OBSERVED, SIMULATED
from hydromodpy.core.scoring.metric_table import RUN_METRIC_NAMES
from hydromodpy.core.time.period_aggregation import period_edges, periods_in_window
from hydromodpy.core.time.time_method import TimeMethod
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
    simulated_nan_stamps,
    time_method_for,
)
from hydromodpy.results.metric_rule import MetricRule, MetricScore, score_run
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
    """The scores of one run under its rule.

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


def fit_metrics(run_dir: str | Path, *, rule: MetricRule, period_start: Any = None) -> RunScores:
    """Score the series stored in ``tables.parquet/timeseries.parquet`` of *run_dir*.

    *period_start* is the start of the first simulated period; without it the
    first period is inferred from the spacing of the stamps. A run without the
    table has no series to score.
    """
    path = Path(run_dir) / TABLES_DIRNAME / f"{TIMESERIES_TABLE}{PARQUET_FILE_SUFFIX}"
    if not path.is_file():
        return score_timeseries(pd.DataFrame(columns=list(_COLUMNS)), rule=rule)
    frame = read_checked_table(path).to_pandas()
    if "component" in frame.columns:
        # A component is a part of a series; the series itself has none.
        frame = frame[frame["component"].isna()]
    return score_timeseries(frame[list(_COLUMNS)], rule=rule, period_start=period_start)


def score_timeseries(
    timeseries: pd.DataFrame, *, rule: MetricRule, period_start: Any = None
) -> RunScores:
    """Score every simulated series of *timeseries* against its observed twin.

    *timeseries* has the columns ``station_id``, ``variable``, ``source``,
    ``time`` and ``value``, simulated and observed rows together.
    """
    pairs, unscored = _pairs(timeseries)
    rows: list[MetricRow] = []
    at_station: dict[str, MetricScore] = {}
    for station, variable, simulated, observed in pairs:
        scores = _score_pair(simulated, observed, rule, station, variable, period_start)
        nse = next(item for item in scores if item.metric == HEADLINE_METRIC)
        if rule.window is not None and nse.n_samples > 0:
            lost = _simulated_nan_in_window(simulated, observed, rule, variable, period_start)
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
    return RunScores(rows=tuple(rows), score=_headline(at_station, rule), unscored=tuple(unscored))


def _pairs(
    timeseries: pd.DataFrame,
) -> tuple[list[tuple[str, str, pd.Series, pd.Series]], list[UnscoredObservation]]:
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
    pairs: list[tuple[str, str, pd.Series, pd.Series]] = []
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
        dated["sim"], dated["obs"], rule, RUN_METRIC_NAMES, station=station, variable=variable
    )
    if min(item.n_samples for item in scores) >= MIN_PAIRED_PERIODS:
        return scores
    nothing = dated.iloc[0:0]
    return score_run(
        nothing["sim"], nothing["obs"], rule, RUN_METRIC_NAMES, station=station, variable=variable
    )


def _simulated_nan_in_window(
    simulated: pd.Series,
    observed: pd.Series,
    rule: MetricRule,
    variable: str,
    period_start: Any,
) -> int:
    """Count the periods of the window the record covers and the simulated value leaves NaN."""
    method = time_method_for(variable)
    dry = simulated_nan_stamps(observed, simulated, method=method, start=period_start)
    if rule.window is None or dry.empty:
        return 0
    inside = periods_in_window(
        dry,
        method=method,
        start=rule.window.start,
        end=rule.window.end,
        grid=pd.DatetimeIndex(normalize_datetime_series(simulated).index),
        period_start=period_start,
    )
    return int(inside.sum())


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
        metric="nse",
        value=None,
        station=rule.station,
        window_name=rule.window_name,
        window_role=rule.window_role,
        window_start=None if window is None else window.start,
        window_end=None if window is None else window.end,
        n_samples=0,
        metric_rule_version=rule.version,
    )


def score_run_under_its_rule(cfg: Any, *, store: RunStore) -> None:
    """Score the series of the run against its observations and record the result.

    The rows go through the one writer of a metric, into the facts and the
    ``metrics`` table, the NSE at the rule station to the headline score, all
    sealed by the record. An observed gauge that
    meets no simulated series fails the non-fatal check
    :data:`UNSCORED_OBSERVATIONS_CHECK`, which the README of the run prints.
    A score that cannot be computed is logged and the run keeps its results:
    the seal says ``nse = NULL`` and the table says why.
    """
    site = store.facts.site
    rule = MetricRule.from_config(cfg, gauge=None if site is None else site.gauge)
    try:
        scores = fit_metrics(store.run_dir, rule=rule, period_start=store.facts.period_start)
    except Exception:
        logger.warning("Could not score the run against its observations", exc_info=True)
        return
    for row in scores.rows:
        store.write_metric(store.sim_id, row)
    store.facts.score = scores.score
    message = scores.unscored_message()
    if message is not None:
        store.facts.note_validity(
            UNSCORED_OBSERVATIONS_CHECK, False, float(len(scores.unscored)), message
        )


__all__ = [
    "HEADLINE_METRIC",
    "HEADLINE_VARIABLE",
    "MIN_PAIRED_PERIODS",
    "TIMESERIES_TABLE",
    "UNSCORED_OBSERVATIONS_CHECK",
    "RunScores",
    "UnscoredObservation",
    "fit_metrics",
    "score_run_under_its_rule",
    "score_timeseries",
]
