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
``nse_window_end``, ``nse_n`` and ``metric_rule_version``. The four columns
keep the ``nse_`` prefix whatever the metric, because that is their name in
``simulation.parquet`` and in the summaries.

Without a window there is no score: ``value`` is ``None`` and ``nse_n`` is 0.
A window is inclusive of both days. The kernels are the ones of
:mod:`hydromodpy.core.metrics`; a value they cannot compute (constant
observations, empty overlap) is ``None`` too, never ``NaN``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Final

import pandas as pd
from pydantic import Field, model_validator

from hydromodpy.core import metrics as kernels
from hydromodpy.core.config_kit.base import HydroModelBase

METRIC_RULE_VERSION: Final[str] = "1"
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


class MetricScore(HydroModelBase):
    """One score and the facts that make it comparable."""

    metric: str = Field(description="Metric name: nse, kge, rmse or nse_log")
    value: float | None = Field(description="The score, or null when it could not be computed")
    nse_window_start: date | None = Field(description="First day scored, null without a window")
    nse_window_end: date | None = Field(description="Last day scored, null without a window")
    nse_n: int = Field(ge=0, description="Samples the score used")
    metric_rule_version: str = Field(description="Version of the rule the score follows")


_KERNELS: dict[str, Callable[[pd.Series, pd.Series], float]] = {
    "nse": kernels.nse,
    "kge": lambda sim, obs: kernels.kge(sim, obs)["kge"],
    "rmse": kernels.rmse,
    "nse_log": kernels.log_nse,
}

METRIC_NAMES: Final[tuple[str, ...]] = tuple(_KERNELS)
"""The metrics :func:`score` knows."""


def score(simulated: pd.Series, observed: pd.Series, rule: MetricRule, metric: str) -> MetricScore:
    """Score *simulated* against *observed* under *rule*.

    Both series are indexed by time. Only the days of ``rule.window`` count,
    and only the instants both series carry a finite value at. Without a
    window the score is ``None`` with zero samples: a run nobody declared a
    window for has no rank.
    """
    kernel = _KERNELS.get(metric)
    if kernel is None:
        raise ValueError(f"unknown metric {metric!r}; known: {', '.join(METRIC_NAMES)}")
    if rule.window is None:
        return MetricScore(
            metric=metric,
            value=None,
            nse_window_start=None,
            nse_window_end=None,
            nse_n=0,
            metric_rule_version=rule.version,
        )
    sim = _within(simulated, rule.window)
    obs = _within(observed, rule.window)
    paired = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1, join="inner").dropna()
    n = int(len(paired))
    value: float | None = None
    if n > 0:
        raw = float(kernel(paired["sim"].to_numpy(), paired["obs"].to_numpy()))
        value = None if math.isnan(raw) else raw
    return MetricScore(
        metric=metric,
        value=value,
        nse_window_start=rule.window.start,
        nse_window_end=rule.window.end,
        nse_n=n,
        metric_rule_version=rule.version,
    )


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
    "METRIC_NAMES",
    "METRIC_RULE_VERSION",
    "DateWindow",
    "MetricRule",
    "MetricScore",
    "score",
]
