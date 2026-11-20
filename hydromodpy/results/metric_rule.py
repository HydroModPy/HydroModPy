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
:class:`MetricsConfig` is the ``[metrics]`` section of a project file, read by
the root configuration. :class:`MetricRule` is what the configuration declares; :class:`MetricScore`
is what a run stores next to the value: ``window_name``, ``window_role``,
``window_start``, ``window_end``, ``n_samples``, ``n_clipped`` and
``metric_rule_version``. :class:`PeriodWindow` is a named period of a calibration:
its role, its extent and, when the cases of a session read different days, the
window of each case.

The headline score of a run is the period :data:`HEADLINE_WINDOW`, the one
``[metrics] window`` declares. A reader that wants one row per metric filters on
that name, and any other period (a validation, a split-sample) stays beside it.

Without a window there is no score: ``value`` is ``None`` and ``n_samples`` is 0.
A window is inclusive of both days. The scores are computed by
:mod:`hydromodpy.results.score` with the kernels of
:mod:`hydromodpy.core.scoring.metrics`; a value they cannot compute (constant
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

from collections.abc import Mapping
from datetime import date
from typing import Annotated, Final, Protocol

from pydantic import Field, ValidationInfo, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.stored import Vocabulary, reading_stored
from hydromodpy.core.config_kit.types import StationName
from hydromodpy.core.site.config import SiteConfig

METRIC_RULE_VERSION: Final[str] = "2"
"""Version of the scoring rule. Bump it when a score stops being comparable."""

HEADLINE_WINDOW: Final[str] = "metrics"
"""Name of the period the headline score of a run is computed on, ``[metrics] window``."""

CALIBRATION_ROLE: Final[str] = "calibration"
"""Role of a period the search scores: the cost, the best trial and the label read it."""

VALIDATION_ROLE: Final[str] = "validation"
"""Role of a period kept apart from the search and scored beside it, ``validation_window``."""

EVALUATION_ROLE: Final[str] = "evaluation"
"""Role of the period ``[metrics] window`` of a run, under the name :data:`HEADLINE_WINDOW`."""

WindowRole = Annotated[str, Vocabulary(CALIBRATION_ROLE, VALIDATION_ROLE, EVALUATION_ROLE)]
"""What a period is for. ``validation`` is kept apart from the search and scored beside it.

Another word reads as it is, and no computation counts it as calibration."""


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


class PeriodWindow(HydroModelBase):
    """A named period of a search: its role, its extent, and the window of each case."""

    role: WindowRole = Field(description="What the period is for")
    start: date = Field(description="First day of the period over all cases")
    end: date = Field(description="Last day of the period over all cases, included")
    by_case: dict[str, DateWindow] = Field(
        default_factory=dict,
        description="Window of each case by case id, empty when every case reads start to end",
    )

    @model_validator(mode="after")
    def _ordered(self, info: ValidationInfo) -> PeriodWindow:
        if not reading_stored(info) and self.end < self.start:
            raise ValueError(f"period ends on {self.end}, before it starts on {self.start}")
        return self

    def of(self, case_id: str) -> DateWindow:
        """Return the days *case_id* reads: its own window, else the whole extent."""
        return self.by_case.get(case_id) or DateWindow(start=self.start, end=self.end)


def calibration_extent(windows: Mapping[str, PeriodWindow]) -> DateWindow | None:
    """Return the span of the periods a search scores, ``None`` when it scores no dated period."""
    scored = [window for window in windows.values() if window.role == CALIBRATION_ROLE]
    if not scored:
        return None
    return DateWindow(
        start=min(window.start for window in scored), end=max(window.end for window in scored)
    )


class MetricsWindow(HydroModelBase):
    """The dates a run is scored on, both included."""

    start: Annotated[date, Profile.USER] = Field(
        description="First day the scores count, as an ISO 8601 date.",
        examples=["2001-01-01"],
    )
    end: Annotated[date, Profile.USER] = Field(
        description="Last day the scores count, included, as an ISO 8601 date.",
        examples=["2002-12-31"],
    )

    @model_validator(mode="after")
    def _ordered(self) -> MetricsWindow:
        if self.end < self.start:
            raise ValueError(
                f"[metrics] window ends on {self.end} before it starts on {self.start}."
            )
        return self


class MetricsConfig(HydroModelBase):
    """The station and the window the scores of a run are computed on."""

    station: Annotated[StationName | None, Profile.USER] = Field(
        default=None,
        description=(
            "Station the run is scored at. Unset, it is [site] gauge; without a gauge, "
            "the only discharge station the run loads, when it loads exactly one."
        ),
        examples=["J0014010"],
    )
    window: Annotated[MetricsWindow | None, Profile.USER] = Field(
        default=None,
        description=(
            "Dates the run is scored on, as {start, end}. Unset, the scores are left "
            "empty: a score over an overlap the data happen to give is not comparable."
        ),
        examples=[{"start": "2001-01-01", "end": "2002-12-31"}],
    )


class ScoringDeclaration(Protocol):
    """What :meth:`MetricRule.from_config` reads of a configuration."""

    @property
    def metrics(self) -> MetricsConfig | None: ...

    @property
    def site(self) -> SiteConfig | None: ...


class MetricRule(HydroModelBase):
    """Where and when a run is scored."""

    station: str | None = Field(default=None, description="Station the metric is read at")
    window: DateWindow | None = Field(
        default=None, description="Days the metric is computed on; none means no score"
    )
    version: str = Field(default=METRIC_RULE_VERSION, description="Version of the scoring rule")
    window_name: str = Field(default=HEADLINE_WINDOW, description="Name of the period")
    window_role: WindowRole = Field(default=EVALUATION_ROLE, description="What the period is for")

    @classmethod
    def from_config(cls, config: ScoringDeclaration, *, gauge: str | None = None) -> MetricRule:
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

    metric: str = Field(description="Metric name, one of RUN_METRIC_NAMES")
    value: float | None = Field(description="The score, or null when it could not be computed")
    station: str | None = Field(default=None, description="Station the score was read at")
    variable: str | None = Field(default=None, description="Variable the score was read on")
    window_name: str | None = Field(default=None, description="Name of the period scored")
    window_role: WindowRole | None = Field(default=None, description="What that period is for")
    window_start: date | None = Field(description="First day scored, null without a window")
    window_end: date | None = Field(description="Last day scored, null without a window")
    n_samples: int = Field(ge=0, description="Samples the score used")
    n_clipped: int | None = Field(
        default=None,
        ge=0,
        description="Negative values clipped to zero before a log-scale score; "
        "null on a metric that never clips",
    )
    metric_rule_version: str = Field(description="Version of the rule the score follows")


__all__ = [
    "CALIBRATION_ROLE",
    "EVALUATION_ROLE",
    "HEADLINE_WINDOW",
    "METRIC_RULE_VERSION",
    "DateWindow",
    "MetricRule",
    "MetricScore",
    "MetricsConfig",
    "MetricsWindow",
    "PeriodWindow",
    "ScoringDeclaration",
    "WindowRole",
    "calibration_extent",
]
