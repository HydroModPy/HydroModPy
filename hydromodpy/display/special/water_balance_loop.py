"""Monthly rain minus evapotranspiration against the gauged discharge, the storage loop.

Each dot is one month: rain minus the soil's ETR on the y axis, the gauged
discharge over the catchment area on the x axis, both in mm per month. On the
1:1 line the catchment passes on what it receives within the month. Above it
the catchment stores water, below it the aquifer drains. The mean month of the
record is joined in calendar order, so the loop it draws reads the storage of
the catchment (Abherve 2022, section 2.2.3, after Schmidt et al. 2020): a flat
loop means a large and slow store, a steep and narrow one a small store. The
values come from the ``water_balance`` rows of the table ``recharge_estimates``,
which a run with a soil reservoir, a gauge and the section writes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.display import static
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import Theme

METHOD = "water_balance"


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw every month and the loop of the mean month on ``ax``."""
    table = read_table(subject, "recharge_estimates")
    rows = table[table["method"] == METHOD]
    if rows.empty:
        raise FigureNotApplicable(
            f"Run {subject.name!r}: its table recharge_estimates holds no water_balance "
            "row; it needs a soil reservoir and a gauge at the outlet."
        )
    months = rows.pivot_table(index=["year", "month"], columns="quantity", values="value")
    months = months.dropna()
    discharge = months["gauged_discharge"].to_numpy(float)
    balance = months["rain_minus_etr"].to_numpy(float)
    calendar = months.index.get_level_values("month").to_numpy(int)

    ax.scatter(
        discharge,
        balance,
        c=calendar,
        cmap="twilight",
        vmin=0.5,
        vmax=12.5,
        s=8,
        alpha=0.6,
        linewidths=0,
        zorder=3,
    )
    mean = months.groupby(level="month").mean().reindex(range(1, 13)).dropna()
    loop_x = np.append(mean["gauged_discharge"].to_numpy(), mean["gauged_discharge"].iloc[0])
    loop_y = np.append(mean["rain_minus_etr"].to_numpy(), mean["rain_minus_etr"].iloc[0])
    ax.plot(loop_x, loop_y, **static.line_style(theme, "simulated"), zorder=4)
    for month, x, y in zip(
        mean.index, mean["gauged_discharge"], mean["rain_minus_etr"], strict=True
    ):
        ax.annotate(
            str(month),
            (x, y),
            **static.text_style(theme),
            xytext=(2, 2),
            textcoords="offset points",
        )
    high = float(max(np.nanmax(discharge), np.nanmax(balance)))
    ax.plot([0.0, high], [0.0, high], color=theme.muted, linewidth=theme.line_width, ls=":")
    ax.set_xlim(left=0.0)
    static.style_axes(ax, theme)
    ax.set_xlabel("gauged discharge Q/A (mm/month)")
    ax.set_ylabel("rain minus ETR (mm/month)")
    static.titles(ax, theme, "Storage loop of the catchment", f"{len(months)} months")
