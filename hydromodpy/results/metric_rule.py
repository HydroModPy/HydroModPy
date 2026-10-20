"""The metric of a run is a complete rule: a station, a window, a version.

Why
---
A score that does not say what it was computed on cannot rank runs. The NSE
of a run used to be computed on whatever overlap the simulated and observed
series happened to have, spin-up included, at a station picked by one of four
rules. Here the rule is declared (``[metrics] station`` and ``window``), the
score records the window and the sample count it used, and a run scored under
another version of the rule is told apart by ``metric_rule_version``.

Format
------
:class:`MetricRule` is what the configuration declares; :class:`MetricScore`
is what a run stores next to the value: ``nse_window_start``,
``nse_window_end``, ``nse_n``, ``n_clipped`` and ``metric_rule_version``. The window columns
keep the ``nse_`` prefix whatever the metric, because that is their name in
``simulation.parquet`` and in the summaries.

Without a window there is no score: ``value`` is ``None`` and ``nse_n`` is 0.
A window is inclusive of both days. The kernels are the ones of
:mod:`hydromodpy.core.metrics`; a value they cannot compute (constant
observations, empty overlap) is ``None`` too, never ``NaN``.

``nse_log`` clips a negative value to zero, as the calibration cost does, and
the score says how many it clipped in ``n_clipped``: 0 when nothing was
clipped, ``None`` on a metric that never clips.

The rule of a run comes from its configuration
(:meth:`MetricRule.from_config`): ``[metrics] station``, else ``[site]
gauge``, else the gauge the run deduced, and ``[metrics] window``. A score names the station and the variable
it was read at when the caller knows them, so a reader can find the row the
headline NSE stands for.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from hydromodpy.core import metrics as kernels
from hydromodpy.core.config_kit.base import HydroModelBase

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

METRIC_RULE_VERSION: Final[str] = "2"
"""Version of the scoring rule. Bump it when a score stops being comparable."""


class DateWindow(HydroModelBase):
    """A closed range of days, ``start`` and ``end`` included."""

    start: date = Field(description="First day of the window")
    end: date = Field(description="Last day of the window, included")

    @model_validator(mode="after")
    def _ordered(self) -> DateWindow:
        if self.end < self.start:
            raise ValueError(f"window ends on {self.end}, before it starts on {self.start}")
        return self

    def contains(self, when: date) -> bool:
        """Return whether *when* falls inside the window."""
        return self.start <= when <= self.end


class MetricRule(HydroModelBase):
    """Where and when a run is scored."""

    station: str | None = Field(default=None, description="Station the metric is read at")
    window: DateWindow | None = Field(
        default=None, description="Days the metric is computed on; none means no score"
    )
    version: str = Field(default=METRIC_RULE_VERSION, description="Version of the scoring rule")

    @classmethod
    def from_config(cls, config: HydroModPyConfig, *, gauge: str | None = None) -> MetricRule:
        """Return the rule a configuration declares.

        The station is ``[metrics] station``, else ``[site] gauge``, else
        *gauge*, the gauge the run deduced (its single hydrometric station,
        :func:`~hydromodpy.data.sites.gauge.gauge_of_run`). The window is
        ``[metrics] window``; without it the rule scores nothing.
        """
        metrics = config.metrics
        site = config.site
        station = metrics.station if metrics is not None else None
        if station is None and site is not None:
            station = site.gauge
        if station is None:
            station = gauge
        declared = metrics.window if metrics is not None else None
        window = None if declared is None else DateWindow(start=declared.start, end=declared.end)
        return cls(station=station, window=window)


class MetricScore(HydroModelBase):
    """One score and the facts that make it comparable."""

    metric: str = Field(description="Metric name, one of METRIC_NAMES")
    value: float | None = Field(description="The score, or null when it could not be computed")
    station: str | None = Field(default=None, description="Station the score was read at")
    variable: str | None = Field(default=None, description="Variable the score was read on")
    nse_window_start: date | None = Field(description="First day scored, null without a window")
    nse_window_end: date | None = Field(description="Last day scored, null without a window")
    nse_n: int = Field(ge=0, description="Samples the score used")
    n_clipped: int | None = Field(
        default=None,
        ge=0,
        description="Negative values clipped to zero before a log-scale score; "
        "null on a metric that never clips",
    )
    metric_rule_version: str = Field(description="Version of the rule the score follows")


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

METRIC_NAMES: Final[tuple[str, ...]] = tuple(_KERNELS)
"""The metrics :func:`score` knows: the four headline scores, then the panel of a run.

The ``kge_*`` entries are the decomposition of the KGE, 2009 form (``beta`` is the
ratio of the sums, ``alpha`` the ratio of the standard deviations): ``r`` tells timing,
``alpha`` amplitude and ``beta`` volume, which a bare score cannot separate.
"""

CLIPPED_METRICS: Final[frozenset[str]] = frozenset({"nse_log"})
"""The metrics that clip a negative value to zero, and so report ``n_clipped``."""

HEADLINE_METRICS: Final[tuple[str, ...]] = ("nse", "kge", "rmse", "nse_log")
"""The metrics :func:`score_run` computes unless told otherwise."""


def score(
    simulated: pd.Series,
    observed: pd.Series,
    rule: MetricRule,
    metric: str,
    *,
    station: str | None = None,
    variable: str | None = None,
) -> MetricScore:
    """Score *simulated* against *observed* under *rule*.

    Both series are indexed by time. Only the days of ``rule.window`` count,
    and only the instants both series carry a finite value at. Without a
    window the score is ``None`` with zero samples: a run nobody declared a
    window for has no rank. *station* and *variable* name where the series
    were read; they are recorded, not checked.
    """
    kernel = _KERNELS.get(metric)
    if kernel is None:
        raise ValueError(f"unknown metric {metric!r}; known: {', '.join(METRIC_NAMES)}")
    if rule.window is None:
        return MetricScore(
            metric=metric,
            value=None,
            station=station,
            variable=variable,
            nse_window_start=None,
            nse_window_end=None,
            nse_n=0,
            n_clipped=0 if metric in CLIPPED_METRICS else None,
            metric_rule_version=rule.version,
        )
    sim = _within(simulated, rule.window)
    obs = _within(observed, rule.window)
    paired = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1, join="inner").dropna()
    n = int(len(paired))
    value: float | None = None
    n_clipped = 0 if metric in CLIPPED_METRICS else None
    if n > 0:
        sim_values, obs_values = paired["sim"].to_numpy(), paired["obs"].to_numpy()
        if metric in CLIPPED_METRICS:
            n_clipped = kernels.clip_negatives(sim_values, obs_values)[2]
        raw = float(kernel(sim_values, obs_values))
        value = None if math.isnan(raw) else raw
    return MetricScore(
        metric=metric,
        value=value,
        station=station,
        variable=variable,
        nse_window_start=rule.window.start,
        nse_window_end=rule.window.end,
        nse_n=n,
        n_clipped=n_clipped,
        metric_rule_version=rule.version,
    )


def score_run(
    simulated: pd.Series,
    observed: pd.Series,
    rule: MetricRule,
    metrics: Sequence[str] = HEADLINE_METRICS,
    *,
    station: str | None = None,
    variable: str | None = None,
) -> list[MetricScore]:
    """Score one simulated series against its observations on every metric of *metrics*.

    Each score follows :func:`score`: same window, same samples, same rule
    version. The order of *metrics* is kept.
    """
    return [
        score(simulated, observed, rule, metric, station=station, variable=variable)
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


__all__ = [
    "HEADLINE_METRICS",
    "METRIC_NAMES",
    "METRIC_RULE_VERSION",
    "DateWindow",
    "MetricRule",
    "MetricScore",
    "score",
    "score_run",
]
