"""Two parameters of a run set on log axes, each run coloured by one score.

``variable`` is ``[x, y]`` or ``[x, y, quantity]``. The quantity is a metric of the table
of ``RunSet.score``, or else a quantity of ``RunSet.score_network`` (its climatological
row). Unset, it is ``nse``. ``time`` is a pair of dates, the one window the runs are
scored on, and unset it is the window each run was sealed with. ``station`` picks one
station, or the bound of a network quantity scored on two bounds. A run whose simulated series has missing values in the window is drawn as a ring
over its marker, since its score covers fewer periods.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from matplotlib.ticker import NullFormatter

from hydromodpy.core.scoring.metric_table import SERIES_METRIC_NAMES
from hydromodpy.display import static
from hydromodpy.display.special.records import axis_label
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import Theme, colormap

DEFAULT_QUANTITY = "nse"
MARKER_SIZE = 28
RING_SIZE = 70


def _window(time: Any) -> tuple[str, str] | None:
    if time is None:
        return None
    if not isinstance(time, list) or len(time) != 2 or not all(
        isinstance(item, str) and item[:1].isdigit() for item in time
    ):  # fmt: skip
        raise FigureNotApplicable(
            f"time = {time!r}: write two dates, [start, end], the window the runs are scored on."
        )
    return time[0], time[1]


def _column(table: pd.DataFrame, name: str) -> str:
    for key in (name, f"param_{name}"):
        if key in table:
            return key
    raise FigureNotApplicable(f"No run of the set holds a parameter {name!r}.")


def _one_row_per_run(rows: pd.DataFrame, quantity: str, keys: list[str]) -> pd.DataFrame:
    left = rows.drop_duplicates(keys)
    if left.duplicated("sim_id").any():
        names = ", ".join(sorted({" ".join(map(str, row)) for row in left[keys].to_numpy()}))
        raise FigureNotApplicable(
            f"{quantity!r} is scored more than once per run ({names}). Name one with station, which names the bound for a network quantity."
        )
    return left


def _scored(subject: Any, quantity: str, window: Any, station: str | None) -> pd.DataFrame:
    """Return one row per run: ``sim_id``, ``value``, ``n_sim_nan`` and the parameters."""
    if quantity in SERIES_METRIC_NAMES:
        windows = None if window is None else {"window": window}
        table = subject.score(windows, [quantity], None, station)
        rows = table[table["value"].notna()]
        return _one_row_per_run(rows, quantity, ["sim_id", "station", "variable", "window_name"])
    table = subject.score_network(None, window)
    climatological = table["year"].isna() | (table["year"].astype(str) == "")
    rows = table[climatological & (table["quantity"] == quantity) & table["value"].notna()]
    if station is not None:
        rows = rows[rows["bound"] == station]
    if rows.empty:
        known = ", ".join(sorted(set(table["quantity"])))
        raise FigureNotApplicable(
            f"{quantity!r} is neither a metric of Run.score nor a quantity of "
            f"Run.score_network. The network quantities are: {known}."
        )
    rows = _one_row_per_run(rows, quantity, ["sim_id", "output", "window_name", "bound"])
    return rows.assign(n_sim_nan=0)


def draw(
    subject: Any,
    ax: Any,
    theme: Theme,
    *,
    station: str | None = None,
    time: Any = None,
    variable: Any = None,
) -> None:
    """Draw the runs on the plane of two parameters, coloured by one score."""
    names = [variable] if isinstance(variable, str) else list(variable or ())
    if len(names) not in (2, 3):
        raise FigureNotApplicable(
            "variable = [x, y] names the two parameters, and a third name the score to colour by."
        )
    x, y = names[:2]
    quantity = names[2] if len(names) == 3 else DEFAULT_QUANTITY
    if not list(subject):
        raise FigureNotApplicable("The run set is empty, so there is no plane to draw.")
    rows = _scored(subject, quantity, _window(time), station)
    xs, ys = _column(rows, x), _column(rows, y)
    rows = rows[rows[[xs, ys]].notna().all(axis=1)]
    if rows.empty:
        raise FigureNotApplicable(f"No run holds both {x!r} and {y!r} with a {quantity!r} score.")
    if (rows[[xs, ys]] <= 0).any(axis=None):
        raise FigureNotApplicable(f"{x!r} and {y!r} go on log axes, so they must be positive.")
    points = ax.scatter(
        rows[xs], rows[ys], c=rows["value"], cmap=colormap(theme.ramps["sequential"]),
        s=MARKER_SIZE, linewidths=0, zorder=3,
    )  # fmt: skip
    nan = rows[rows["n_sim_nan"] > 0]
    if not nan.empty:
        ax.scatter(
            nan[xs], nan[ys], s=RING_SIZE, facecolors="none", edgecolors=theme.ink,
            linewidths=theme.line_width, zorder=4,
            label=f"{len(nan)} runs with missing simulated values",
        )  # fmt: skip
        static.legend(ax, theme)
    for axis in "xy":
        getattr(ax, f"set_{axis}scale")("log")
        getattr(ax, f"{axis}axis").set_minor_formatter(NullFormatter())
    ax.set_xlabel(axis_label(x, None))
    ax.set_ylabel(axis_label(y, None))
    static.style_axes(ax, theme)
    static.colorbar(ax.figure, points, ax, theme, label=quantity)
