"""The 10 to 90 % band and the median of one series across the runs of a set, at one station.

The runs are compared on the stamps they all share, so a run with a shorter record
trims the band for everyone. The band is the 10 % and the 90 % quantiles across the runs
at each stamp, and the legend says so. The median line sits inside it and
the observed record, when one run holds it, is drawn over both. The station is the one
the first run scored, unless one is asked. A run without the series is left out.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from hydromodpy.display import static, variables
from hydromodpy.display.frames.series import draw_observed
from hydromodpy.display.special.records import scored_station
from hydromodpy.display.subject import FigureNotApplicable, read_observed, read_series
from hydromodpy.display.theme import Theme

VARIABLE = "discharge"
MIN_RUNS = 2
LOW, HIGH = 0.1, 0.9


def draw(subject: Any, ax: Any, theme: Theme, *, station: str | None = None) -> None:
    """Draw the range and the median of the runs on their shared stamps, with the record."""
    runs = list(subject)
    if not runs:
        raise FigureNotApplicable("The run set is empty, so there is no band to draw.")
    station = scored_station(runs[0], VARIABLE, station)
    columns: dict[int, pd.Series] = {}
    for number, run in enumerate(runs):
        try:
            columns[number] = read_series(run, VARIABLE, station=station)
        except FigureNotApplicable:
            continue
    if len(columns) < MIN_RUNS:
        raise FigureNotApplicable(
            f"Only {len(columns)} of the {len(runs)} runs hold {VARIABLE!r} at station "
            f"{station!r}. A band needs at least {MIN_RUNS}."
        )
    table = pd.concat(columns, axis=1, join="inner")
    if table.empty:
        raise FigureNotApplicable("The runs share no stamp, so their band is empty.")
    shown = pd.DataFrame(variables.to_display(VARIABLE, table.to_numpy()), index=table.index)
    color = static.line_style(theme, "simulated")["color"]
    ax.fill_between(
        shown.index, shown.quantile(LOW, axis=1), shown.quantile(HIGH, axis=1), color=color,
        alpha=0.3, linewidth=0, label=f"10 to 90 % of {shown.shape[1]} runs",
    )  # fmt: skip
    ax.plot(
        shown.index, shown.median(axis=1), label="Median", **static.line_style(theme, "simulated")
    )
    for run in runs:
        try:
            record = read_observed(run, VARIABLE, station=station).reindex(table.index)
        except FigureNotApplicable:
            continue
        seen = pd.Series(variables.to_display(VARIABLE, record.to_numpy()), index=record.index)
        seen = seen.dropna()
        draw_observed(ax, seen.index, seen, theme)
        break
    dates = pd.api.types.is_datetime64_any_dtype(table.index)
    if variables.is_log(VARIABLE):
        ax.set_yscale("log")
    head, unit = variables.label_parts(VARIABLE)
    ax.set_ylabel(variables.join_unit(head, unit))
    if not dates:
        ax.set_xlabel("Period")
    static.style_axes(ax, theme, dates=dates)
    static.legend(ax, theme)
