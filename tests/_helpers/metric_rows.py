"""Short factories for the headline metric of a run: one row and its score on ``[metrics] window``."""

from __future__ import annotations

from datetime import date
from typing import Any

from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import (
    EVALUATION_ROLE,
    HEADLINE_WINDOW,
    METRIC_RULE_VERSION,
    DateWindow,
    MetricScore,
)

GAUGE = "J0014010"
WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))


def headline_row(
    metric: str = "nse",
    value: float | None = 0.8,
    *,
    station: str | None = GAUGE,
    variable: str | None = "discharge",
    window: DateWindow = WINDOW,
    n_samples: int = 10,
    **fields: Any,
) -> MetricRow:
    """Return a row of the headline period; *fields* are written as they are."""
    return MetricRow(
        **{
            "station": station,
            "variable": variable,
            "metric": metric,
            "value": value,
            "window_name": HEADLINE_WINDOW,
            "window_role": EVALUATION_ROLE,
            "window_start": window.start,
            "window_end": window.end,
            "n_samples": n_samples,
            "metric_rule_version": METRIC_RULE_VERSION,
            **fields,
        }
    )


def headline_score(
    value: float | None = 0.8,
    *,
    metric: str = "nse",
    station: str | None = GAUGE,
    variable: str | None = "discharge",
    window: DateWindow = WINDOW,
    n_samples: int = 10,
    **fields: Any,
) -> MetricScore:
    """Return the score of the headline period; *fields* are written as they are."""
    return MetricScore(
        **{
            "metric": metric,
            "value": value,
            "station": station,
            "variable": variable,
            "window_name": HEADLINE_WINDOW,
            "window_role": EVALUATION_ROLE,
            "window_start": window.start,
            "window_end": window.end,
            "n_samples": n_samples,
            "metric_rule_version": METRIC_RULE_VERSION,
            **fields,
        }
    )
