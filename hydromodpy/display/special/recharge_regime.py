"""The mean year of each method: rain and ETP, recharge, runoff, month by month.

Three panels side by side, each over the twelve months of the mean year of the
record. The first holds the rain as bars and the ETP as a line, the second the
recharge of each soil law, of a loaded product and of the run, the third their
runoff. It shows at a glance a recharge that never stops in summer, the mark of
a product that already holds the outflow of the aquifer, beside a soil law that
dries out. The values are the monthly rows of the table ``recharge_estimates``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.display import static
from hydromodpy.display.special.records import (
    INPUT,
    legend_with_room,
    method_style,
    monthly_signals,
    signal_methods,
)
from hydromodpy.display.theme import Theme

GAP = 0.07
MONTHS = np.arange(1, 13)


def _side_by_side(ax: Any) -> list[Any]:
    """Three insets of the host, left to right, each with its own scale."""
    ax.set_axis_off()
    width = (1.0 - 2 * GAP) / 3
    return [ax.inset_axes([i * (width + GAP), 0.0, width, 1.0]) for i in range(3)]


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the mean month of the weather, of the recharge and of the runoff on ``ax``."""
    signals = monthly_signals(subject)
    mean = signals.groupby(signals.index.month).mean().reindex(MONTHS)
    years = signals.index.year.nunique()
    methods = signal_methods(signals)
    weather, recharge, runoff = _side_by_side(ax)

    if (INPUT, "precipitation") in mean.columns:
        weather.bar(MONTHS, mean[(INPUT, "precipitation")].to_numpy(), width=0.8,
                    color=theme.roles["inflow"], alpha=0.55, label="rain", zorder=2)  # fmt: skip
    if (INPUT, "etp") in mean.columns:
        weather.plot(MONTHS, mean[(INPUT, "etp")].to_numpy(), label="ETP", zorder=3,
                     **static.line_style(theme, "evapotranspiration"))  # fmt: skip
    for rank, method in enumerate(methods):
        style = method_style(method, rank, theme)
        for panel, quantity in ((recharge, "recharge"), (runoff, "runoff")):
            if (method, quantity) in mean.columns:
                panel.plot(MONTHS, mean[(method, quantity)].to_numpy(), marker="o",
                           markersize=2.5, **style)  # fmt: skip

    titles = (
        (weather, "Mean year, weather", f"{years} years"),
        (recharge, "recharge", ""),
        (runoff, "runoff", "one ru, not one soil" if len(methods) > 2 else ""),
    )
    for panel, left, right in titles:
        static.style_axes(panel, theme)
        panel.set_xticks(MONTHS, ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
        panel.set_xlim(0.4, 12.6)
        panel.set_ylim(bottom=0.0)
        static.titles(panel, theme, left, right)
    weather.set_ylabel("mean month (mm/month)")
    legend_with_room(weather, theme)
    legend_with_room(recharge, theme)
