"""Streambed, stream stage and aquifer head along the main stem of the SFR network.

The main stem is the longest upstream path from the outlet, found on the reach table by
``results.derive.main_stem``. The x axis is the distance to the outlet at the middle of
each reach. Without a time the stage and the head are the mean of the periods with their
min-max envelope, and a gap of the mean head above or below the mean stage is filled as
a gain or a loss. With a time the figure shows that period alone. A note says how many
reaches and how many kilometres of the network the main stem covers. The tributaries are
not drawn.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from hydromodpy.display import static
from hydromodpy.display.subject import FigureNotApplicable, read_field, read_table
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.derive.main_stem import main_stem

STAGE = "stage"


def draw(subject: Any, ax: Any, theme: Theme, *, time: Any = None) -> None:
    """Draw the bed, the stage and the aquifer head along the main stem on ``ax``."""
    reaches = read_table(subject, "sfr_reaches").sort_values(["network_id", "reach"])
    reaches = reaches.reset_index(drop=True)
    table = read_table(subject, "timeseries")
    sim = table[(table["source"] == "simulated") & (table["variable"] == STAGE)]
    sim = sim[sim["station_id"].isin(reaches["reach_id"])]
    if sim.empty:
        raise FigureNotApplicable(
            f"Run {subject.name!r}: it holds no SFR stage series, so there is no profile to draw."
        )
    stem, distance = main_stem(reaches)
    rows = reaches.iloc[stem]
    stage = sim.pivot_table(index="timestep", columns="station_id", values="value")
    stage = stage.reindex(columns=rows["reach_id"])
    steps = list(stage.index)
    if time is not None:
        steps = [int(subject.periods.step_at(time))]
        stage = stage.loc[steps]
    cells = rows["cell2d"].to_numpy(int)
    head = np.array([read_field(subject, "head", time=int(s))[cells] for s in steps])
    x = distance / 1000.0
    ax.plot(
        x, rows["rtp"].to_numpy(float), label="Streambed top", **static.line_style(theme, "bed")
    )
    for values, role, label, dash in (
        (stage.to_numpy(float), "river", "Stream stage", "-"),
        (head, "aquifer_head", "Aquifer head", "--"),
    ):
        ax.plot(
            x, np.nanmean(values, axis=0), label=label, ls=dash, **static.line_style(theme, role)
        )
        if len(values) > 1:
            ax.fill_between(
                x, np.nanmin(values, axis=0), np.nanmax(values, axis=0),
                color=theme.roles[role], alpha=0.2, linewidth=0,
            )  # fmt: skip
    gap = (np.nanmean(head, axis=0), np.nanmean(stage.to_numpy(float), axis=0))
    for sign, role, label in (
        (gap[0] >= gap[1], "gain", "Gaining"),
        (gap[0] < gap[1], "loss", "Losing"),
    ):
        ax.fill_between(
            x, *gap, where=sign, interpolate=True, color=theme.roles[role], alpha=0.4,
            linewidth=0, label=label,
        )  # fmt: skip
    ax.invert_xaxis()
    ax.set_xlabel("Distance to the outlet along the main stem (km)")
    ax.set_ylabel(f"Elevation ({unit_text('m')})")
    when = f"period {steps[0]}" if time is not None else f"mean of {len(steps)} periods, min-max"
    ax.set_title(f"{rows['network_id'].iloc[-1]}, {when}")
    static.style_axes(ax, theme)
    static.legend(ax, theme)
    forks = any(len(down) > 1 for down in reaches["downstream"])
    rule = "\nforks follow the larger flow share" if forks and "ustrf" in reaches else ""
    total = reaches["rlen"].sum()
    static.note(
        ax,
        f"Main stem: {len(rows)} of {len(reaches)} reaches, "
        f"{rows['rlen'].sum() / 1000.0:.1f} of {total / 1000.0:.1f} km of the network{rule}",
        theme,
        loc="lower left",
    )
