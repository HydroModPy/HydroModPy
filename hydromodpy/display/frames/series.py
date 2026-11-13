"""Series frame: values along an ordered axis, the time of a run.

It draws one line per variable and station, the observed record over the
simulated one, stacked areas, reference lines and the scores of the run. Trial
numbers on the axis come with the session columns of a later lot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from hydromodpy.core.units.kinds import QUANTITY_KINDS
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.display import static, variables
from hydromodpy.display.request import (
    AGAINST_OBSERVED,
    BUDGET,
    ZONE_PREFIX,
    PanelRequest,
    ReferenceValue,
)
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_budget,
    read_mesh,
    read_observed,
    read_period_seconds,
    read_series,
)
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.field_registry import kind_of, label_of
from hydromodpy.results.run.view import Run

SERIES_COLUMNS = ("time", "variable", "station", "simulated", "observed")


@dataclass(frozen=True, slots=True)
class SeriesData:
    """What a series panel draws.

    ``table`` is long, one row per period, variable and station, with the columns
    of ``SERIES_COLUMNS``: ``time`` the period START (datetime64, or the period
    number of a run without dates), ``variable`` and ``station`` as asked (station
    None when the run picked its only one), ``simulated`` in the display unit
    (float64). ``observed`` is present only when the panel asked for it and the
    run holds it, NaN for a period without observation. With ``against =
    "observed"`` the ``simulated`` column holds simulated minus observed and
    ``observed`` is dropped. ``references`` holds value and label of each
    horizontal line. ``scores`` holds the rows of ``run.metrics`` for the drawn
    variable and station, None when the panel did not ask. ``window`` holds the first and
    last period of the requested time window in the units of the ``time`` column, None
    without one, and ``draw`` shades it. ``residual`` is true for ``against = "observed"``.
    """

    table: pd.DataFrame
    label: str
    log: bool
    stack: bool
    references: tuple[tuple[float, str], ...] = ()
    scores: pd.DataFrame | None = None
    window: tuple[Any, Any] | None = None
    residual: bool = False


def _stations(panel: PanelRequest) -> list[str | None]:
    if panel.station is None:
        return [None]
    return [panel.station] if isinstance(panel.station, str) else list(panel.station)


def _window(panel: PanelRequest) -> tuple[Any, Any] | None:
    if isinstance(panel.time, list) and len(panel.time) == 2:
        return panel.time[0], panel.time[1]
    return None


def _zone_area(run: Run, station: str | None) -> float | None:
    if station is None or not station.startswith(ZONE_PREFIX):
        return None
    mesh = read_mesh(run)
    return float(np.nansum(mesh.areas[mesh.zones[station[len(ZONE_PREFIX) :]]]))


def _convert(
    name: str, values: pd.Series, area: float | None, seconds: np.ndarray | None
) -> pd.Series:
    """Return ``values`` in display unit, or the running sum of its rate when ``seconds`` is given."""
    raw = values.to_numpy(dtype=float)
    if seconds is None:
        return pd.Series(variables.to_display(name, raw, area=area), index=values.index)
    kind = kind_of(name)
    total = np.cumsum(np.where(np.isnan(raw), 0.0, raw) * seconds)
    total[np.isnan(raw)] = np.nan
    if kind.per_area:
        total = total / area
    target = QUANTITY_KINDS[kind.cumulates_to]
    factor = convert_between_units(1.0, from_unit=target.stored_unit, to_unit=target.display_unit)
    return pd.Series(total * factor, index=values.index)


def _label(panel: PanelRequest, names: list[str]) -> str:
    first = names[0]
    unit = unit_text(kind_of(first).display_unit)
    head = variables.label(first).rpartition(" (")[0] or variables.label(first)
    if panel.cumulative:
        target = QUANTITY_KINDS[kind_of(first).cumulates_to]
        unit = unit_text(target.display_unit)
        head = f"Cumulative {head[:1].lower() + head[1:]}"
    elif len(names) > 1:
        head = "Budget terms" if BUDGET in (panel.variable or ()) else "Value"
    if panel.against == AGAINST_OBSERVED:
        head = "Residual, simulated minus observed"
    return f"{head} ({unit})" if unit else head


def _scores(run: Run, keys: list[tuple[str, str | None]]) -> pd.DataFrame:
    metrics = run.metrics
    rows = []
    for name, station in keys:
        hit = metrics["variable"] == name
        if station is not None:
            hit &= metrics["station"].astype(str) == station
        rows.append(metrics[hit])
    return pd.concat(rows, ignore_index=True) if rows else metrics.iloc[0:0]


def _references(panel: PanelRequest) -> tuple[tuple[float, str], ...]:
    found = []
    for ref in panel.reference or ():
        if isinstance(ref, ReferenceValue):
            found.append((ref.value, ref.label))
        elif ref == "zero":
            found.append((0.0, "zero"))
        else:
            raise FigureNotApplicable(f"The reference {ref!r} does not apply to a series.")
    return tuple(found)


def data(subject: Run, panel: PanelRequest) -> SeriesData:
    """Read every variable of the panel at every station, in display unit, on period starts.

    ``budget`` expands through ``read_budget``. Each name goes through
    ``read_series`` with ``panel.time`` as window, then ``read_observed`` when
    ``panel.observed`` (absence drops the column) or ``panel.against`` is
    ``observed`` (absence refuses). A ``per_area`` kind at a zone is divided by the
    zone area of ``read_mesh``. ``cumulative`` sums along time and switches the
    kind to its ``cumulates_to``.
    """
    if panel.reduce is not None or panel.change is not None:
        raise FigureNotApplicable(
            "A series keeps its time axis, so reduce and change do not apply to it. "
            "Use a map to reduce over time or to draw a change."
        )
    if panel.cumulative:
        for name in panel.variable or ():
            if name != BUDGET and kind_of(name).cumulates_to is None:
                raise FigureNotApplicable(
                    f"{name!r} cannot be cumulated: its kind has no running sum over time."
                )
    if panel.against not in (None, AGAINST_OBSERVED):
        raise FigureNotApplicable(
            f"A series can only be drawn against {AGAINST_OBSERVED!r}, not {panel.against!r}."
        )
    if not panel.variable:
        raise FigureNotApplicable("A series panel needs a variable.")
    against = panel.against == AGAINST_OBSERVED
    window = _window(panel)
    want_observed = panel.observed or against
    frames, keys = [], []
    for station in _stations(panel):
        names = []
        for name in panel.variable:
            names += read_budget(subject, station=station) if name == BUDGET else [name]
        area = _zone_area(subject, station)
        for name in dict.fromkeys(names):
            sim = read_series(subject, name, station=station, window=window)
            seconds = read_period_seconds(subject, sim.index) if panel.cumulative else None
            frame = pd.DataFrame(
                {
                    "time": sim.index,
                    "variable": name,
                    "station": station,
                    "simulated": _convert(name, sim, area, seconds).to_numpy(),
                }
            )
            if want_observed:
                try:
                    obs = read_observed(subject, name, station=station)
                except FigureNotApplicable:
                    if against:
                        raise
                    # No record here: the panel then shows the simulation alone.
                else:
                    obs = obs.reindex(sim.index)
                    frame["observed"] = _convert(name, obs, area, seconds).to_numpy()
            if against:
                frame["simulated"] = frame["simulated"] - frame["observed"]
                frame = frame.drop(columns="observed")
            frames.append(frame)
            keys.append((name, station))
    table = pd.concat(frames, ignore_index=True)
    table = table[[c for c in SERIES_COLUMNS if c in table.columns]]
    log = (
        panel.scale == "log"
        if against or panel.cumulative
        else any(variables.is_log(name, panel.scale) for name, _ in keys)
    )
    return SeriesData(
        table=table,
        label=_label(panel, list(dict.fromkeys(name for name, _ in keys))),
        log=log,
        stack=panel.stack,
        references=_references(panel),
        scores=_scores(subject, keys) if panel.scores else None,
        window=None if window is None else (table["time"].iloc[0], table["time"].iloc[-1]),
        residual=against,
    )


def _color(index: int, many: bool, theme: Theme) -> str:
    """Return the simulated colour of one line, or a distinct colour of the palette among several."""
    return theme.categorical[index % len(theme.categorical)] if many else theme.roles["simulated"]


KEY_SCORES = ("nse", "kge", "pbias", "rmse")
"""Scores written on a panel, when the run holds them. Every other metric stays in the table."""


def _scored_window(scores: pd.DataFrame) -> str:
    """Return ``scored 2001-01 to 2002-12`` when the metrics carry one window, else nothing."""
    if not {"window_start", "window_end"} <= set(scores.columns):
        return ""
    starts, ends = scores["window_start"].dropna().unique(), scores["window_end"].dropna().unique()
    if len(starts) != 1 or len(ends) != 1:
        return ""
    return f"scored {str(starts[0])[:7]} to {str(ends[0])[:7]}"


def _score_text(scores: pd.DataFrame, many: bool) -> str:
    wanted = scores[scores["metric"].isin(KEY_SCORES)]
    parts = []
    for (name, _station, metric), rows in wanted.groupby(
        ["variable", "station", "metric"], dropna=False
    ):
        value = rows["value"].iloc[0]
        if np.isfinite(value):
            prefix = f"{name} " if many else ""
            parts.append(f"{prefix}{metric.upper()} {value:.2f}")
    window = _scored_window(wanted) if parts else ""
    return "   ".join([*parts, f"({window})"] if window else parts)


def _stacked(ax: Any, groups: list[Any], dates: bool, theme: Theme) -> None:
    """Stack bars of each period: inflows above zero, outflows below, one colour role per term."""
    for sign in (1, -1):
        base = None
        for i, (name, _station, rows) in enumerate(groups):
            x = mdates.date2num(rows["time"]) if dates else rows["time"].to_numpy(dtype=float)
            width = np.append(np.diff(x), np.diff(x)[-1] if len(x) > 1 else 1.0)
            vals = np.nan_to_num(rows["simulated"].to_numpy(dtype=float))
            part = np.clip(vals, 0, None) if sign > 0 else np.clip(vals, None, 0)
            base = np.zeros_like(part) if base is None else base
            ax.bar(
                x, part, width, bottom=base, align="edge", linewidth=0,
                color=_color(i, True, theme),
                label=label_of(name) if sign > 0 else None,
            )  # fmt: skip
            base = base + part
    if dates:
        ax.xaxis_date()


def draw(ax: Any, data: SeriesData, theme: Theme) -> None:
    """Draw lines, or stacked areas, with the observed record as points of the observed role.

    Uses ``static.style_axes`` with dates, ``static.legend`` above the axes and
    the scores as the right title.
    """
    table = data.table
    dates = pd.api.types.is_datetime64_any_dtype(table["time"])
    groups = [
        (n, s, rows)
        for (n, s), rows in table.groupby(["variable", "station"], sort=False, dropna=False)
    ]
    many = len(groups) > 1
    if data.log:
        ax.set_yscale("log")
    if data.stack:
        _stacked(ax, groups, dates, theme)
        ax.axhline(0, color=theme.ink, linewidth=theme.line_width, zorder=3)
    else:
        stations = {s for _, s, _ in groups}
        for i, (name, station, rows) in enumerate(groups):
            label = "simulated" if not many else label_of(name)
            if data.residual:
                label = "simulated minus observed"
            if len(stations) > 1:
                label += f" ({station})"
            ax.plot(
                rows["time"],
                rows["simulated"],
                label=label,
                color=_color(i, many, theme),
                linewidth=theme.data_line_width,
            )
    if data.window is not None:
        ax.axvspan(*data.window, color=theme.roles["bounds"], alpha=0.12, linewidth=0, zorder=0)
    if data.residual:
        ax.axhline(0, color=theme.ink, linewidth=theme.line_width, zorder=3)
    if "observed" in table:
        seen = table.dropna(subset=["observed"])
        style = static.line_style(theme, "observed")
        if len(seen) > 200:
            ax.plot(
                seen["time"],
                seen["observed"],
                label="observed",
                zorder=4,
                **{**style, "linewidth": theme.line_width},
            )
        else:
            ax.plot(seen["time"], seen["observed"], label="observed", zorder=4, linestyle="none", marker="o", markersize=2.5, markerfacecolor=style["color"], markeredgewidth=0, color=style["color"])  # fmt: skip
    for value, text in data.references:
        ax.axhline(value, color=theme.roles["bounds"], linewidth=theme.line_width, linestyle="--", label=None if text == "zero" else text, zorder=3)  # fmt: skip
    ax.set_ylabel(data.label)
    if not dates:
        ax.set_xlabel("Period")
    static.style_axes(ax, theme, dates=dates)
    if data.scores is not None and len(data.scores):
        text = _score_text(data.scores, many)
        if text:
            ax.set_title(text, loc="right", **static.text_style(theme))
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)
