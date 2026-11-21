"""Records of a run or a session that more than one special figure reads or marks.

The station a run was scored at, the completed trials of a session, the two marks of
the returned and of the acceptable trials, the monthly water signals of the methods of
``recharge_estimates`` and the style each method is drawn with. The returned trial and the acceptable cost
of a phase come from ``results/session/acceptance.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import static
from hydromodpy.display.frames.series import scores
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import Theme, unit_text

STAR_SIZE = 65
RING_SIZE = 40
RUN = "run"
INPUT = "input"
MONTHLY_QUANTITIES = ("recharge", "runoff", "precipitation", "etp")


def scored_station(run: Any, variable: str, station: str | None) -> str | None:
    """Return ``station``, else the station of the first score of ``variable``, else None."""
    if station is not None:
        return station
    rows = scores(run, [(variable, None)])
    return None if rows.empty else str(rows["station"].iloc[0])


def completed_trials(session: Any) -> pd.DataFrame:
    """Return the completed trials of a session that hold a cost, in trial order."""
    trials = read_table(session, "trials")
    return trials[(trials["status"] == "completed") & trials["cost"].notna()].sort_values("trial")


def axis_label(name: str, units: str | None) -> str:
    """Return ``name (unit)`` with the unit set in the theme text, or ``name`` alone."""
    unit = unit_text(units or "")
    return f"{name} ({unit})" if unit else name


def mark_returned(ax: Any, x: Any, y: Any, theme: Theme) -> None:
    """Mark the trial the session returned with a star."""
    ax.scatter([x], [y], marker="*", s=STAR_SIZE, color=theme.roles["best"],
               edgecolors=theme.ink, linewidths=theme.line_width, zorder=5,
               label="Returned trial")  # fmt: skip


def ring_acceptable(
    ax: Any, x: Any, ys: list[Any], cost: Any, threshold: float | None, theme: Theme
) -> None:
    """Ring each point of the ``ys`` curves whose cost is at or under ``threshold``.

    The ring has one legend entry that gives the threshold. Without a threshold nothing is
    ringed.
    """
    if threshold is None:
        return
    kept = np.asarray(cost, float) <= threshold
    if not kept.any():
        return
    ax.scatter(
        np.tile(np.asarray(x, float)[kept], len(ys)),
        np.concatenate([np.asarray(y, float)[kept] for y in ys]),
        s=RING_SIZE, facecolors="none", edgecolors=theme.ink, linewidths=theme.line_width,
        zorder=4, label=f"Cost under {threshold:.3g}",
    )  # fmt: skip


def monthly_signals(run: Any) -> pd.DataFrame:
    """The monthly sums of ``recharge_estimates``, one column per (method, quantity), in mm.

    The index is the first day of each month. A run writes these rows when its
    ``[recharge_estimates]`` names soil_methods or compare_loaded.
    """
    table = read_table(run, "recharge_estimates")
    rows = table[table["month"].notna() & table["quantity"].isin(MONTHLY_QUANTITIES)]
    if rows.empty:
        raise FigureNotApplicable(
            f"Run {run.name!r}: its table recharge_estimates holds no monthly signal; write "
            'soil_methods = "all" or compare_loaded = true under [recharge_estimates].'
        )
    date = pd.to_datetime(
        {"year": rows["year"].astype(int), "month": rows["month"].astype(int), "day": 1}
    )
    return rows.assign(date=date).pivot_table(
        index="date", columns=["method", "quantity"], values="value", sort=False
    )


def signal_methods(signals: pd.DataFrame) -> list[str]:
    """The methods of ``signals`` with a recharge, in the order written, the run last."""
    methods = [m for m in dict.fromkeys(signals.columns.get_level_values("method")) if m != INPUT]
    methods = [m for m in methods if (m, "recharge") in signals.columns]
    return [m for m in methods if m != RUN] + [m for m in methods if m == RUN]


def method_style(method: str, rank: int, theme: Theme) -> dict[str, Any]:
    """The line of ``method``: the run dashed in its role, a product in its role, a law by rank."""
    if method == RUN:
        return {"color": theme.roles["simulated"], "linewidth": theme.data_line_width * 1.4,
                "linestyle": "--", "label": "run", "zorder": 5}  # fmt: skip
    color = theme.roles.get(method) or theme.class_color(rank)
    return {"color": color, "linewidth": theme.data_line_width, "label": method.replace("_", " "),
            "zorder": 4}  # fmt: skip


HEADROOM = 1.7
"""The top of a panel of lines, as a multiple of its highest value, so a legend has room."""


def legend_with_room(ax: Any, theme: Theme) -> None:
    """Raise the top of ``ax`` and put its legend on the side where its lines stay lowest."""
    xs, ys = [], []
    for artist in (*ax.get_lines(), *ax.patches):
        if hasattr(artist, "get_xydata"):
            data = np.asarray(artist.get_xydata(), dtype=float)
        else:
            x, y = artist.get_x(), artist.get_height()
            data = np.array([[x + artist.get_width() / 2, y]], dtype=float)
        xs.append(data[:, 0])
        ys.append(data[:, 1])
    if not xs:
        return
    y = np.concatenate(ys)
    high = float(np.nanmax(y)) if np.isfinite(y).any() else 0.0
    if high > 0.0:
        ax.set_ylim(0.0, high * HEADROOM)
    x = np.concatenate(xs)
    (x0, x1), share = ax.get_xlim(), static.CORNER_SHARE[0]
    left = y[x < x0 + share * (x1 - x0)]
    right = y[x > x1 - share * (x1 - x0)]
    peak = {
        side: float(np.nanmax(v)) if v.size else 0.0
        for side, v in (("left", left), ("right", right))
    }
    static.legend(ax, theme, inside="upper left" if peak["left"] < peak["right"] else "upper right")
