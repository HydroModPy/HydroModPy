"""Yearly recharge of each method of [recharge_estimates], beside the run's own.

One column per method, and per piezometer for the water table fluctuation. Each
dot is one year and the bar is the mean over the years. The run's recharge is
drawn the same way in its own colour, and its mean crosses the whole panel, so
the eye reads at once where the run sits in the range the data allow. A method
that gives an effective rainfall (Turc) is marked as such, since it is not a
recharge until a share of it infiltrates. The values come from the table
``recharge_estimates``, which the run writes when its file holds the section.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.display import static
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import Theme

RUN = "run"


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the yearly values of each method and the run's mean on ``ax``."""
    table = read_table(subject, "recharge_estimates")
    monthly = table["month"].notna() if "month" in table else False
    yearly = table[table["year"].notna() & (table["unit"] == "mm") & ~monthly]
    if yearly.empty:
        raise FigureNotApplicable(
            f"Run {subject.name!r}: its table recharge_estimates holds no yearly value."
        )
    yearly = yearly.assign(station=yearly["station"].fillna(""))
    groups = list(yearly.groupby(["method", "station"], sort=False))
    groups.sort(key=lambda item: item[0][0] == RUN)

    labels = []
    for x, ((method, station), group) in enumerate(groups):
        values = group["value"].to_numpy(float)
        role = "simulated" if method == RUN else "recharge"
        spread = np.linspace(-0.12, 0.12, values.size) if values.size > 1 else np.zeros(1)
        ax.scatter(
            x + spread,
            values,
            s=9,
            color=theme.roles[role],
            alpha=0.7,
            linewidths=0,
            zorder=3,
        )
        ax.hlines(values.mean(), x - 0.3, x + 0.3, **static.line_style(theme, role), zorder=4)
        label = method.replace("_", " ") + (f"\n{station}" if station else "")
        if group["quantity"].iloc[0] == "effective_rainfall":
            label += "\n(effective rain)"
        labels.append(label)

    run = yearly[yearly["method"] == RUN]["value"]
    if not run.empty:
        ax.axhline(run.mean(), color=theme.roles["simulated"], linewidth=theme.line_width, ls="--")
    static.style_axes(ax, theme)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_ylabel("recharge (mm/year)")
    static.titles(ax, theme, "Recharge estimated from the data", "one dot per year")
