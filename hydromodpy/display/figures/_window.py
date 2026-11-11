"""The spin-up of a run, shaded on its series figures.

A run is scored on ``[metrics] window``; what precedes the window start is the
spin-up. A figure never takes that date as an option: it reads the window the
run was scored on, else the ``[metrics]`` window of the run's config. A run
without a window has no spin-up to shade.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

import matplotlib.dates as mdates
import pandas as pd

from hydromodpy.results.run.sealed import metrics_of

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.view import Run

SPINUP_COLOR = "0.82"
SPINUP_LABEL = "before the scoring window"


def window_start(run: Run) -> date | None:
    """Return the first day *run* is scored on, or ``None`` when it has no window.

    The window of the sealed scores comes first, as it is the one the run was
    ranked on; the ``[metrics]`` window of its config serves a run that sealed
    no score.
    """
    frame = metrics_of(run)
    if "window_start" in frame:
        starts = frame["window_start"].dropna()
        if not starts.empty:
            return pd.Timestamp(starts.iloc[0]).date()
    return _configured_window_start(run)


def _configured_window_start(run: Run) -> date | None:
    try:
        snapshot: Any = run.config_snapshot
    except Exception:
        # A stand-in or a run without a catalog row carries no config.
        return None
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    window = metrics.get("window") if isinstance(metrics, dict) else None
    start = window.get("start") if isinstance(window, dict) else None
    return None if start is None else pd.Timestamp(start).date()


def shade_before_window(ax: Axes, run: Run) -> bool:
    """Shade what precedes the scoring window of *run* on a date axis.

    Call it once the series are drawn and before the legend is built. Return
    whether anything was shaded: not when the run has no window, or when the
    window starts at or before the left edge of the axis.
    """
    start = window_start(run)
    if start is None:
        return False
    left, right = ax.get_xlim()
    edge = mdates.date2num(datetime.combine(start, time.min))
    if edge <= left:
        return False
    ax.axvspan(
        left,
        min(edge, right),
        color=SPINUP_COLOR,
        alpha=0.55,
        linewidth=0.0,
        zorder=0,
        label=SPINUP_LABEL,
    )
    ax.set_xlim(left, right)
    return True
