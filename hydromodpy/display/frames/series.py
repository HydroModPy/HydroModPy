"""Series frame: values along an ordered axis, the time of a run.

It draws one line per variable and station, the observed record over the
simulated one, stacked areas, reference lines and the scores of the run. The
trial columns of a session are drawn against the number of the trial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from hydromodpy.core.units.kinds import kind_row
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.display import static, variables
from hydromodpy.display.request import (
    AGAINST_OBSERVED,
    BUDGET,
    ZONE_PREFIX,
    PanelRequest,
    ReferenceValue,
    is_column,
    is_trial_column,
)
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_budget,
    read_column_series,
    read_mesh,
    read_observed,
    read_period_seconds,
    read_series,
    read_trial_column,
    refuse_fields,
    refuse_set,
)
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.field_registry import kind_of, label_of
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session

FIELDS = (
    "variable", "time", "station", "observed", "scores", "scale", "stack", "reference",
    "against", "cumulative",
)  # fmt: skip
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

    The trials of a session have no time. Their table holds the trial number in a column
    named ``trial`` in place of ``time``, ``axis`` says which, and ``x_label`` names it.
    ``labels`` gives the label of each variable that has no registry row. ``trials`` is the
    number of trials drawn and the number the session ran.
    """

    table: pd.DataFrame
    label: str
    log: bool
    stack: bool
    references: tuple[tuple[float, str], ...] = ()
    scores: pd.DataFrame | None = None
    window: tuple[Any, Any] | None = None
    residual: bool = False
    axis: str = "time"
    x_label: str = "Period"
    labels: dict[str, str] = field(default_factory=dict)
    trials: tuple[int, int] | None = None


def _stations(panel: PanelRequest) -> list[str | None]:
    if panel.station is None:
        return [None]
    return [panel.station] if isinstance(panel.station, str) else list(panel.station)


def zone_cells(mesh: Any, station: str | None) -> np.ndarray:
    """Return the mask of the cells of a zone station, the catchment when unset."""
    station = ZONE_PREFIX + "catchment" if station is None else station
    if not station.startswith(ZONE_PREFIX):
        raise FigureNotApplicable(f"{station!r} is not a zone, so it names no cells.")
    return mesh.zones[station[len(ZONE_PREFIX) :]]


def zone_area(run: Run, station: str | None) -> float | None:
    """Return the area in m2 of the zone a station names, None for any other station."""
    if station is None or not station.startswith(ZONE_PREFIX):
        return None
    mesh = read_mesh(run)
    return float(np.nansum(mesh.areas[zone_cells(mesh, station)]))


def observed_on(run: Run, name: str, station: str | None, index: pd.Index) -> pd.Series:
    """Return the observed record of a series on the periods of ``index``."""
    return read_observed(run, name, station=station).reindex(index)


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
    target = kind_row(kind.cumulates_to)
    factor = convert_between_units(1.0, from_unit=target.stored_unit, to_unit=target.display_unit)
    return pd.Series(total * factor, index=values.index)


def _label(panel: PanelRequest, names: list[str]) -> str:
    first = names[0]
    head, unit = variables.label_parts(first)
    if panel.cumulative:
        target = kind_row(kind_of(first).cumulates_to)
        unit = unit_text(target.display_unit)
        head = f"Cumulative {head[:1].lower() + head[1:]}"
    elif len(names) > 1:
        head = "Budget terms" if BUDGET in (panel.variable or ()) else "Value"
    elif variables.scale(first) == "categorical" and any(
        str(station).startswith(ZONE_PREFIX) for station in _stations(panel)
    ):
        # A zone series of a class field is the share of the zone area where the class is 1.
        head = f"Share of area, {head[:1].lower() + head[1:]}"
    if panel.against == AGAINST_OBSERVED:
        head = "Residual, simulated minus observed"
    return variables.join_unit(head, unit)


def scores(run: Run, keys: list[tuple[str, str | None]]) -> pd.DataFrame:
    """Return the rows of ``run.metrics`` for each variable and station of ``keys``.

    The rows carry the scoring window in their ``window_start`` and ``window_end``
    columns, which ``score_text`` writes after the numbers.
    """
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


TRIAL_AXIS = "trial"
TRIAL_FIELDS = ("time", "station", "observed", "scores", "stack", "against", "cumulative")


def _trial_data(session: Session, panel: PanelRequest) -> SeriesData:
    """Return each trial column against the trial number, one line per variable."""
    for name in TRIAL_FIELDS:
        refuse_set("series", panel, name, "the trials of a session have no such axis")
    names = [name for name in panel.variable or () if is_trial_column(name)]
    if len(names) != len(panel.variable or ()) or not names:
        raise FigureNotApplicable("A series of a session takes trials.<column> names only.")
    found = {name: read_trial_column(session, name, panel.scale) for name in names}
    frames = [
        pd.DataFrame(
            {
                TRIAL_AXIS: column.values.index.to_numpy(),
                "variable": name,
                "station": None,
                "simulated": column.values.to_numpy(),
            }
        )
        for name, column in found.items()
    ]
    first = found[names[0]]
    return SeriesData(
        table=pd.concat(frames, ignore_index=True),
        label=first.label if len(names) == 1 else "Value",
        log=any(column.log for column in found.values()),
        stack=False,
        references=_references(panel),
        axis=TRIAL_AXIS,
        x_label="Trial",
        labels={name: column.label for name, column in found.items()},
        trials=(len(first.values), first.ran),
    )


def data(subject: Run | Session, panel: PanelRequest) -> SeriesData:
    """Read every variable of the panel at every station, in display unit, on period starts.

    ``budget`` expands through ``read_budget``. Each name goes through
    ``read_series`` with ``panel.time`` as window, then ``read_observed`` when
    ``panel.observed`` (absence drops the column) or ``panel.against`` is
    ``observed`` (absence refuses). A ``per_area`` kind at a zone is divided by the
    zone area of ``read_mesh``. ``cumulative`` sums along time and switches the
    kind to its ``cumulates_to``.
    """
    refuse_fields("series", panel, FIELDS)
    if isinstance(subject, Session):
        return _trial_data(subject, panel)
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
    window = panel.window
    want_observed = panel.observed or against
    frames, keys = [], []
    for station in _stations(panel):
        names = []
        for name in panel.variable:
            names += read_budget(subject, station=station) if name == BUDGET else [name]
        area = zone_area(subject, station)
        for name in dict.fromkeys(names):
            sim = (
                read_column_series(subject, name, window=window)
                if is_column(name)
                else read_series(subject, name, station=station, window=window)
            )
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
                    obs = observed_on(subject, name, station, sim.index)
                except FigureNotApplicable:
                    if against:
                        raise
                    # No record here: the panel then shows the simulation alone.
                else:
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
        scores=scores(subject, keys) if panel.scores else None,
        window=None if window is None else (table["time"].iloc[0], table["time"].iloc[-1]),
        residual=against,
    )


def _color(index: int, many: bool, theme: Theme) -> str:
    """Return the simulated colour of one line, or a distinct colour of the palette among several."""
    return theme.class_color(index) if many else theme.roles["simulated"]


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


def score_text(scores: pd.DataFrame, many: bool, window: bool = True) -> str:
    """Return the key scores of a table as one line, with the scoring window when it is single.

    A panel on dates leaves the window out and writes it under the axis, where it cannot
    run into the panel letter.
    """
    wanted = scores[scores["metric"].isin(KEY_SCORES)]
    parts = []
    for (name, _station, metric), rows in wanted.groupby(
        ["variable", "station", "metric"], dropna=False
    ):
        value = rows["value"].iloc[0]
        if np.isfinite(value):
            prefix = f"{name} " if many else ""
            parts.append(f"{prefix}{metric.upper()} {value:.2f}")
    scored = _scored_window(wanted) if parts and window else ""
    return "   ".join([*parts, f"({scored})"] if scored else parts)


def _stacked(ax: Any, groups: list[Any], dates: bool, theme: Theme) -> None:
    """Stack bars of each period: inflows above zero, outflows below, one colour role per term."""
    colors = variables.member_colors(list(dict.fromkeys(name for name, _, _ in groups)), theme)
    for sign in (1, -1):
        base = None
        for name, _station, rows in groups:
            x = mdates.date2num(rows["time"]) if dates else rows["time"].to_numpy(dtype=float)
            width = np.append(np.diff(x), np.diff(x)[-1] if len(x) > 1 else 1.0)
            vals = np.nan_to_num(rows["simulated"].to_numpy(dtype=float))
            part = np.clip(vals, 0, None) if sign > 0 else np.clip(vals, None, 0)
            base = np.zeros_like(part) if base is None else base
            ax.bar(
                x, part, width, bottom=base, align="edge", linewidth=0,
                color=colors[name],
                label=label_of(name) if sign > 0 else None,
            )  # fmt: skip
            base = base + part
    if dates:
        ax.xaxis_date()


OBSERVED_LINE_FROM = 200
"""An observed record with more points than this is drawn as a thin line, else as markers."""


def draw_observed(ax: Any, x: Any, y: Any, theme: Theme) -> None:
    """Draw the observed record: a thin line when it is long, else dots."""
    style = static.line_style(theme, "observed")
    if len(y) > OBSERVED_LINE_FROM:
        ax.plot(x, y, label="observed", zorder=4, **{**style, "linewidth": theme.line_width})
    else:
        ax.plot(x, y, label="observed", zorder=4, linestyle="none", marker="o", markersize=2.5, markerfacecolor=style["color"], markeredgewidth=0, color=style["color"])  # fmt: skip


def _layout(data: SeriesData) -> tuple[list[Any], bool, bool, bool]:
    """Return the groups of the table, whether there are several, and whether it is dated or trials."""
    table = data.table
    groups = [
        (n, s, rows)
        for (n, s), rows in table.groupby(["variable", "station"], sort=False, dropna=False)
    ]
    dates = pd.api.types.is_datetime64_any_dtype(table[data.axis])
    return groups, len(groups) > 1, dates, data.axis != "time"


def _line_label(
    data: SeriesData, name: str, station: Any, many: bool, stations: bool, trials: bool
) -> str | None:
    label = "simulated" if not many else data.labels.get(name) or label_of(name)
    if trials and not many:
        label = None
    if data.residual:
        label = "simulated minus observed"
    if stations:
        label += f" ({station})"
    return label


def draw(ax: Any, data: SeriesData, theme: Theme) -> None:
    """Draw lines, or stacked areas, with the observed record as points of the observed role.

    Uses ``static.style_axes`` with dates, ``static.legend`` above the axes and
    the scores as the right title.
    """
    table = data.table
    groups, many, dates, trials = _layout(data)
    if data.log:
        ax.set_yscale("log")
    if data.stack:
        _stacked(ax, groups, dates, theme)
        ax.axhline(0, color=theme.ink, linewidth=theme.line_width, zorder=3)
    else:
        stations = {s for _, s, _ in groups}
        for i, (name, station, rows) in enumerate(groups):
            label = _line_label(data, name, station, many, len(stations) > 1, trials)
            ax.plot(
                rows[data.axis],
                rows["simulated"],
                label=label,
                color=_color(i, many, theme),
                linewidth=theme.data_line_width,
                **({"marker": "o", "markersize": 2.5} if trials else {}),
            )
    if data.window is not None:
        ax.axvspan(*data.window, color=theme.roles["bounds"], alpha=0.12, linewidth=0, zorder=0)
    if data.residual:
        ax.axhline(0, color=theme.ink, linewidth=theme.line_width, zorder=3)
    if "observed" in table:
        seen = table.dropna(subset=["observed"])
        draw_observed(ax, seen["time"], seen["observed"], theme)
    for value, text in data.references:
        ax.axhline(value, color=theme.roles["bounds"], linewidth=theme.line_width, linestyle="--", label=None if text == "zero" else text, zorder=3)  # fmt: skip
    ax.set_ylabel(data.label)
    if not dates:
        ax.set_xlabel(data.x_label)
    static.style_axes(ax, theme, dates=dates)
    if trials:
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    if data.scores is not None and len(data.scores):
        text = score_text(data.scores, many, window=not dates)
        if text:
            ax.set_title(text, loc="right", **static.text_style(theme))
        if dates and text:
            window = _scored_window(data.scores[data.scores["metric"].isin(KEY_SCORES)])
            ax.set_xlabel(window.capitalize(), **static.text_style(theme))
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)


# ---------------------------------------------------------------- interactive
def _flat(x: Any, y: float, **style: Any) -> Any:
    import plotly.graph_objects as go

    return go.Scatter(x=[x.iloc[0], x.iloc[-1]], y=[y, y], mode="lines", hoverinfo="skip", **style)


def draw_interactive(data: SeriesData, theme: Theme) -> tuple[list, dict]:
    """Return the plotly traces of ``draw``: lines or stacked bars, the observed record, references.

    Every trace carries its value in the hover. Bars of a stacked budget start at their
    period start and run to the next one, positive terms up and negative ones down.
    """
    import plotly.graph_objects as go

    from hydromodpy.display import interactive

    table = data.table
    groups, many, dates, trials = _layout(data)
    stations = {s for _, s, _ in groups}
    px = interactive.PX_PER_POINT
    traces = []
    colors = variables.member_colors(list(dict.fromkeys(n for n, _, _ in groups)), theme)
    for i, (name, station, rows) in enumerate(groups):
        x = rows[data.axis]
        label = _line_label(data, name, station, many, len(stations) > 1, trials)
        if data.stack:
            step = np.diff(x.to_numpy())
            step = step / np.timedelta64(1, "ms") if dates else step.astype(float)
            width = np.append(step, step[-1] if len(step) else 1.0)
            traces.append(
                go.Bar(
                    x=x,
                    y=rows["simulated"],
                    width=width,
                    offset=0,
                    name=label_of(name),
                    marker={"color": colors[name], "line": {"width": 0}},
                )  # fmt: skip
            )
            continue
        traces.append(
            go.Scatter(
                x=x,
                y=rows["simulated"],
                name=label,
                showlegend=label is not None,
                mode="lines+markers" if trials else "lines",
                line={"color": _color(i, many, theme), "width": theme.data_line_width * px},
                marker={"size": 2.5 * px},
            )  # fmt: skip
        )
    if "observed" in table:
        seen = table.dropna(subset=["observed"])
        color = theme.roles["observed"]
        long = len(seen) > OBSERVED_LINE_FROM
        traces.append(
            go.Scatter(
                x=seen["time"],
                y=seen["observed"],
                name="observed",
                mode="lines" if long else "markers",
                line={"color": color, "width": theme.line_width * px},
                marker={"color": color, "size": 2.5 * px},
            )  # fmt: skip
        )
    first = table[data.axis]
    if data.residual:
        traces.append(_flat(first, 0.0, line={"color": theme.ink, "width": theme.line_width * px}, showlegend=False))  # fmt: skip
    for value, text in data.references:
        style = {"color": theme.roles["bounds"], "width": theme.line_width * px, "dash": "dash"}
        traces.append(_flat(first, value, line=style, name=text, showlegend=text != "zero"))
    axes = {
        "xaxis": {} if dates else {"title": {"text": data.x_label}},
        "yaxis": {
            "title": {"text": interactive.plain(data.label)},
            **({"type": "log"} if data.log else {}),
        },  # fmt: skip
    }
    if data.scores is not None and len(data.scores):
        axes["title"] = score_text(data.scores, many, window=not dates)
    return traces, axes
