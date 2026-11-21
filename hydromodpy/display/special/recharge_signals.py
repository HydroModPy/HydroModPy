"""Monthly rain and ETP, then the recharge and the runoff of each method, month by month.

Three panels share the time axis. The top one holds the weather every method
reads: the monthly rain as bars and the ETP as a line. The middle one draws the
recharge of each soil law, of a loaded product such as SIM2 and of the run, the
bottom one their runoff. The eye then reads where a method sends the winter
rain, whether its recharge stops in summer, and how much it gives to the
streams at once. The soil laws share one ru, which is not one soil: the ru that
closes the budget differs from law to law. The values are the monthly rows of
the table ``recharge_estimates``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import static
from hydromodpy.display.special.records import (
    INPUT,
    legend_with_room,
    method_style,
    monthly_signals,
    signal_methods,
)
from hydromodpy.display.theme import Theme

GAP = 0.06
SHARES = (0.26, 0.40, 0.34)


def _stacked(ax: Any) -> list[Any]:
    """Three insets of the host, top to bottom, sharing the x axis."""
    ax.set_axis_off()
    room = 1.0 - GAP * (len(SHARES) - 1)
    panels, top = [], 1.0
    for share in SHARES:
        height = room * share
        panels.append(ax.inset_axes([0.0, top - height, 1.0, height]))
        top -= height + GAP
    for panel in panels[1:]:
        panel.sharex(panels[0])
    return panels


def _months(ax: Any, series: pd.Series, **style: Any) -> None:
    """Draw a monthly series as steps that hold each month to its end, the last one too."""
    edges = series.index.append(pd.DatetimeIndex([series.index[-1] + pd.offsets.MonthBegin()]))
    ax.step(edges, np.append(series.to_numpy(), series.iloc[-1]), where="post", **style)


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the monthly weather, recharge and runoff of each method on ``ax``."""
    signals = monthly_signals(subject)
    methods = signal_methods(signals)
    weather, recharge, runoff = _stacked(ax)

    if (INPUT, "precipitation") in signals.columns:
        rain = signals[(INPUT, "precipitation")].dropna()
        weather.bar(rain.index, rain.to_numpy(), width=25, align="edge",
                    color=theme.roles["inflow"], alpha=0.55, label="rain", zorder=2)  # fmt: skip
    if (INPUT, "etp") in signals.columns:
        etp = signals[(INPUT, "etp")].dropna()
        _months(
            weather, etp, label="ETP", zorder=3, **static.line_style(theme, "evapotranspiration")
        )
    for rank, method in enumerate(methods):
        style = method_style(method, rank, theme)
        for panel, quantity in ((recharge, "recharge"), (runoff, "runoff")):
            if (method, quantity) in signals.columns:
                series = signals[(method, quantity)].dropna()
                if not series.empty:
                    _months(panel, series, **style)

    for panel, label in ((weather, "weather"), (recharge, "recharge"), (runoff, "runoff")):
        static.style_axes(panel, theme, dates=True)
        panel.set_ylabel(f"{label} (mm/month)")
        panel.set_ylim(bottom=0.0)
    for panel in (weather, recharge):
        panel.tick_params(labelbottom=False)
    static.titles(weather, theme, "Recharge and runoff of each method", "monthly sums")
    legend_with_room(weather, theme)
    legend_with_room(recharge, theme)
    if len(methods) > 1:
        static.titles(runoff, theme, "", "one ru for every soil law, not one soil")
