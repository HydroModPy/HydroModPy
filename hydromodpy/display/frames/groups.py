"""Groups frame: named categories against a value, as bars or as boxes.

A category is a variable of a list (the budget terms, the series of a lake), a
class of a categorical field, a calendar month, a period, or a run of a run set.
It draws one bar per category when each holds one value, side by side or stacked
for several members, and one box per category when each holds many values, such
as the monthly regime of a flow. It draws no time axis and no map.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import static, variables
from hydromodpy.display.frames.map import stored_field
from hydromodpy.display.frames.series import observed_on, zone_area, zone_cells
from hydromodpy.display.request import BUDGET, PanelRequest
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_budget,
    read_mesh,
    read_period_seconds,
    read_series,
    refuse_fields,
    refuse_set,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.time_alignment import time_method_for
from hydromodpy.results.field_registry import BUDGET_SIGN_RULE, FIELD_REGISTRY, label_of
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run

FIELDS = (
    "variable", "time", "layer", "station", "observed", "scale", "stack", "by", "reduce"
)  # fmt: skip
GROUPS_COLUMNS = ("category", "member", "source", "value", "low", "q1", "median", "q3", "high", "n")
FEW = 10
"""A group with fewer values has whiskers at its minimum and maximum."""
BOX_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
"""Weighted quantiles of a box: whisker, box, median, box, whisker."""
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NAN5 = (np.nan,) * 5
BOX_NOTE = (
    "Box 25 to 75 %, line median, whiskers {whiskers}, n = {count} per box, weighted by {weight}"
)
NOTE_WIDTH = 48
"""Characters of a note line and of a category label before it wraps."""


@dataclass(frozen=True, slots=True)
class GroupsData:
    """What a groups panel draws.

    ``table`` has the columns of ``GROUPS_COLUMNS``, one row per category, member
    and source, in drawing order. ``category`` is the text under the axis (a
    variable label, a class name, ``Jan`` to ``Dec``, a period start as
    ``2001-03`` for a calendar month, else ``start to end`` as dates, or a period
    number, a run name). ``member`` is the variable the
    row belongs to, the same as ``category`` when the categories are the
    variables. ``source`` is ``simulated`` or ``observed``. For bars, ``value`` is
    the value in the display unit (float64) and the five quantile columns are NaN.
    For boxes, ``low``, ``q1``, ``median``, ``q3`` and ``high`` are the weighted
    quantiles of ``BOX_QUANTILES`` in the display unit and ``value`` is NaN. ``n`` is
    the number of values behind the row, which says how much a box can be trusted.

    ``label`` is the value axis label with its unit. ``boxes`` says which of the
    two the table holds. ``stack`` stacks the members of a category, inflows above
    zero and outflows below. ``sign_rule`` is ``BUDGET_SIGN_RULE`` when the members
    are budget terms, written over the panel, else empty. ``log`` sets the value
    axis to a log scale. ``weight`` names what weights a box, ``period length`` for a
    series and ``cell area`` for a field, and the note of a box says it.
    """

    table: pd.DataFrame
    label: str
    boxes: bool
    stack: bool = False
    sign_rule: str = ""
    log: bool = False
    weight: str = ""


def _row(category, member, source, n: int, value: float = np.nan, box=NAN5) -> tuple:
    return (category, member, source, value, *box, n)


def _kept(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.isfinite(values) & (weights > 0)


def _quantiles(values: np.ndarray, weights: np.ndarray) -> tuple[float, ...]:
    """Weighted quantiles of ``BOX_QUANTILES``, interpolated on the mid-points of the weights."""
    keep = _kept(values, weights)
    if not keep.any():
        return NAN5
    order = np.argsort(values[keep])
    v, w = values[keep][order], weights[keep][order]
    return tuple(float(q) for q in np.interp(BOX_QUANTILES, (np.cumsum(w) - 0.5 * w) / w.sum(), v))


def _reduce(values: np.ndarray, weights: np.ndarray, how: str | None) -> float:
    """Weighted mean or maximum of the finite values, NaN when there are none."""
    keep = np.isfinite(values)
    if not keep.any():
        return np.nan
    if how == "max":
        return float(values[keep].max())
    return float(np.average(values[keep], weights=weights[keep]))


def _zone_mask(run: Run, panel: PanelRequest) -> tuple[np.ndarray, np.ndarray]:
    mesh = read_mesh(run)
    mask = zone_cells(mesh, panel.station)
    return mask, mesh.areas[mask]


def _series(run: Run, name: str, panel: PanelRequest) -> tuple[pd.Series, np.ndarray]:
    """Return the series in display unit and the length in s of each period."""
    raw = read_series(run, name, station=panel.station, window=panel.window)
    values = variables.to_display(name, raw.to_numpy(), area=zone_area(run, panel.station))
    return pd.Series(values, index=raw.index), read_period_seconds(run, raw.index)


def _variable_rows(run: Run, panel: PanelRequest) -> list[tuple]:
    """One bar per variable: its series reduced over time, weighted by period length."""
    names: list[str] = []
    for name in panel.variable:
        names += read_budget(run, station=panel.station) if name == BUDGET else [name]
    rows = []
    for name in dict.fromkeys(names):
        values, seconds = _series(run, name, panel)
        value = _reduce(values.to_numpy(), seconds, panel.reduce)
        rows.append(_row(label_of(name), name, "simulated", int(np.isfinite(values).sum()), value))
    return rows


def _class_rows(run: Run, panel: PanelRequest, name: str) -> list[tuple]:
    """One bar per class: the share of the zone area in that class, in percent."""
    mask, areas = _zone_mask(run, panel)
    field = stored_field(run, name, panel)[mask]
    areas = np.where(np.isfinite(field), areas, 0.0)
    return [
        _row(
            text,
            name,
            "simulated",
            int((field == code).sum()),
            100 * areas[field == code].sum() / areas.sum(),
        )
        for code, text in FIELD_REGISTRY[name].classes
    ]


def _cell(category: str, member: str, source: str, v, w, how: str | None) -> tuple:
    """One row: the weighted five quantiles without ``reduce``, else one reduced value."""
    n = int(_kept(v, w).sum())
    if how is None:
        return _row(category, member, source, n, box=_quantiles(v, w))
    return _row(category, member, source, n, _reduce(v, w, how))


def _starts(index: pd.Index, seconds: np.ndarray, name: str) -> pd.Index:
    """Return the START of each period of a series index.

    A state is stamped by the END of its period and a flux by its START, which is the
    rule of the reads, so the start of a state is its stamp minus the period length.
    """
    if not isinstance(index, pd.DatetimeIndex) or time_method_for(name) != "point":
        return index
    return index - pd.to_timedelta(seconds, unit="s")


def _month_rows(run: Run, panel: PanelRequest, name: str) -> list[tuple]:
    """Boxes, or bars with ``reduce``, of the periods of one series grouped by month of start."""
    sim, seconds = _series(run, name, panel)
    sources = {"simulated": sim}
    if panel.observed:
        record = observed_on(run, name, panel.station, sim.index)
        sources["observed"] = pd.Series(variables.to_display(name, record.to_numpy()), sim.index)
    months = _starts(sim.index, seconds, name).month
    return [
        _cell(MONTHS[m - 1], name, source, values.to_numpy()[hit], seconds[hit], panel.reduce)
        for source, values in sources.items()
        for m in sorted(set(months))
        for hit in [np.asarray(months == m)]
    ]


def _period_label(start: Any, seconds: float) -> str:
    """Return ``2001-03`` for a calendar month, else ``start to end`` as dates, else the number."""
    if not isinstance(start, pd.Timestamp):
        return str(start)
    length = pd.to_timedelta(float(seconds), unit="s")
    end = start + length
    if start.day == 1 and end.day == 1 and 28 <= length.days <= 31:
        return f"{start:%Y-%m}"
    return f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"


def _period_rows(run: Run, panel: PanelRequest, name: str) -> list[tuple]:
    """One box, or bar with ``reduce``, per period of a field over the cells of the zone.

    Period ``i`` is read at step ``i``, which is the rule of the reads: a state is the
    value at the period end, a flux the value over the period. The label names the
    period, so it does not depend on the stamp the variable carries.
    """
    mask, areas = _zone_mask(run, panel)
    stamps = read_series(run, name, station=panel.station or "zone:catchment").index
    seconds = read_period_seconds(run, stamps)
    starts = _starts(stamps, seconds, name)
    cell_areas = read_mesh(run).areas
    rows = []
    for step in range(len(stamps)):
        at = panel.model_copy(update={"time": step, "reduce": None, "change": None})
        cells = variables.to_display(name, stored_field(run, name, at), area=cell_areas)
        text = _period_label(starts[step], seconds[step])
        rows.append(_cell(text, name, "simulated", cells[mask], areas, panel.reduce))
    return rows


def _label(names: list[str], budget: bool) -> str:
    head, unit = variables.label_parts(names[0])
    if len(names) > 1:
        head = "Budget terms" if budget else "Value"
    return variables.join_unit(head, unit)


def data(subject: Run | RunSet, panel: PanelRequest) -> GroupsData:
    """Read the values of each category and reduce them to a bar or a box.

    Without ``by``, the categories are the variables of the list, ``budget``
    expanded by ``read_budget``. Each is a series at the station or zone of the
    panel, read by ``read_series`` over the window of ``time`` and reduced over
    time by ``reduce`` (``mean`` or ``max``; required, and ``frequency`` refused).
    One categorical field without ``by`` gives one bar per class: the share of
    the zone area (``zone:catchment`` when unset) in that class at ``time``, in
    percent.

    ``by = "month"`` groups the periods of a series by the calendar month of their
    start. ``by = "time"`` gives one category per period of a field, its values over
    the cells of the zone, weighted by cell area. ``by = "run"`` takes a
    ``RunSet`` subject and gives one category per run, each reduced as without
    ``by``, the terms stacked with ``stack``. With ``by``, ``reduce`` set gives
    bars and ``reduce`` unset gives boxes, except ``by = "run"``, which needs
    ``reduce``. ``observed = true`` adds the record of ``read_observed`` as a
    second source on the same periods, for series only.

    Values are in the display unit; a ``per_area`` kind at a zone is divided by the
    zone area of ``read_mesh``, as on a series. Budget terms keep the stored sign,
    positive into the aquifer. ``against``, ``change``, ``cumulative`` and a box
    with ``stack`` are refused. So are ``layer`` on a series, ``observed`` outside
    ``by = "month"``, ``time`` with ``by = "time"`` and ``scale`` on bars of terms or classes,
    since each would change nothing.
    """
    refuse_fields("groups", panel, FIELDS)
    if panel.reduce == "frequency":
        raise FigureNotApplicable("A groups panel reduces by mean or max, not frequency.")
    if not panel.variable:
        raise FigureNotApplicable("A groups panel needs a variable.")
    first, budget = panel.variable[0], BUDGET in panel.variable
    classed = not budget and bool(getattr(FIELD_REGISTRY.get(first), "classes", ()))
    boxes = panel.by in ("month", "time") and panel.reduce is None
    share = classed and panel.by is None and panel.reduce is None
    if not (share or panel.by == "time"):
        refuse_set("groups", panel, "layer", "a series has no layer")
    if panel.by != "month":
        refuse_set("groups", panel, "observed", "only the regime by month reads the record")
    if panel.by == "time":
        refuse_set("groups", panel, "time", "each period of the run is a category")
    if budget or classed:
        refuse_set("groups", panel, "scale", "this panel has no value axis to scale")
    if boxes and panel.stack:
        raise FigureNotApplicable("Boxes cannot be stacked.")
    if panel.by is None and panel.reduce is None and not classed:
        raise FigureNotApplicable(
            "A groups panel needs by (month, time or run) or reduce (mean or max). "
            "Boxes need by = 'month' or 'time'."
        )
    if panel.by == "run":
        if not isinstance(subject, RunSet) or panel.reduce is None:
            raise FigureNotApplicable("by = 'run' needs a run set and reduce = 'mean' or 'max'.")
        rows = [(r.name or r.sim_id, *x[1:]) for r in subject for x in _variable_rows(r, panel)]
    elif not isinstance(subject, Run):
        raise FigureNotApplicable("A run set is drawn by groups with by = 'run' only.")
    elif panel.by == "month":
        rows = _month_rows(subject, panel, first)
    elif panel.by == "time":
        rows = _period_rows(subject, panel, first)
    elif classed and panel.reduce is None:
        rows = _class_rows(subject, panel, first)
    else:
        rows = _variable_rows(subject, panel)
    table = pd.DataFrame(rows, columns=list(GROUPS_COLUMNS))
    table = table.dropna(subset=list(GROUPS_COLUMNS[3:9]), how="all", ignore_index=True)
    if table.empty:
        raise FigureNotApplicable("No category of this groups panel holds a finite value.")
    return GroupsData(
        table=table,
        label="Share of area (%)"
        if share
        else _label(list(dict.fromkeys(table["member"])), budget),
        boxes=boxes,
        stack=panel.stack,
        sign_rule=BUDGET_SIGN_RULE if budget else "",
        log=not budget and not classed and variables.is_log(first, panel.scale),
        weight="cell area" if panel.by == "time" else "period length",
    )


def _color(row: Any, members: list[str], theme: Theme) -> str:
    """Observed role, one colour per class or per member (as the series frame), else simulated."""
    if row.source == "observed":
        return theme.roles["observed"]
    classes = [text for _, text in getattr(FIELD_REGISTRY.get(row.member), "classes", ())]
    if row.category in classes:
        return variables.class_colors(row.member, theme)[classes.index(row.category)]
    if len(members) > 1:
        return variables.member_colors(members, theme)[row.member]
    return theme.roles["simulated"]


def _draw_boxes(ax: Any, table: pd.DataFrame, theme: Theme, cats: list[str]) -> None:
    sources = list(dict.fromkeys(table["source"]))
    width = 0.7 / len(sources)
    for k, source in enumerate(sources):
        rows = table[table["source"] == source]
        shift = (k - (len(sources) - 1) / 2) * width
        x = np.array([cats.index(c) for c in rows["category"]]) + shift
        stats = [
            {"whislo": r.low, "q1": r.q1, "med": r.median, "q3": r.q3, "whishi": r.high}
            for r in rows.itertuples()
        ]
        color = theme.roles[source]
        line = {"color": color, "linewidth": theme.line_width}
        ax.bxp(
            stats, positions=x, widths=width * 0.85, showfliers=False, patch_artist=True,
            boxprops={"edgecolor": color, "facecolor": color, "alpha": 0.5, "linewidth": theme.line_width},
            medianprops={"color": theme.ink, "linewidth": theme.data_line_width},
            whiskerprops=line, capprops=line, manage_ticks=False,
        )  # fmt: skip
        ax.plot([], [], color=color, linewidth=4, alpha=0.5, label=source)


def _bar_slots(table: pd.DataFrame, stack: bool, one: bool) -> list[tuple[list[str], str]]:
    """Return the groups of members drawn at one x offset, with their source.

    Stacked members, and the rows of a table with one row per category, share one offset.
    """
    members = list(dict.fromkeys(table["member"]))
    sources = list(dict.fromkeys(table["source"]))
    if one or stack:
        return [(members, s) for s in sources]
    return [([m], s) for m in members for s in sources]


def _bar_part(values: np.ndarray, sign: int) -> np.ndarray:
    """Return all values (0), only the positive ones (1) or only the negative ones (-1)."""
    if sign == 0:
        return values
    return np.clip(values, 0, None) if sign > 0 else np.clip(values, None, 0)


def _draw_bars(ax: Any, table: pd.DataFrame, stack: bool, theme: Theme, cats: list[str]) -> None:
    members = list(dict.fromkeys(table["member"]))
    sources = list(dict.fromkeys(table["source"]))
    one = len(table) == len(cats) * len(sources)  # one row per category and source
    slots = _bar_slots(table, stack, one)
    width = 0.8 / len(slots)
    seen: set[str | None] = set()
    for k, (group, source) in enumerate(slots):
        base = np.zeros(len(cats))
        for sign in (1, -1) if stack else (0,):
            for member in group:
                rows = table[(table["source"] == source) & (table["member"] == member)]
                x = np.array([cats.index(c) for c in rows["category"]])
                part = _bar_part(np.nan_to_num(rows["value"].to_numpy(float)), sign)
                text = source if len(sources) > 1 else None
                if text is None and len(members) > 1 and not one:
                    text = label_of(member)
                ax.bar(
                    x + (k - (len(slots) - 1) / 2) * width, part, width * 0.9, bottom=base[x],
                    color=[_color(r, members, theme) for r in rows.itertuples()], linewidth=0,
                    label=None if text in seen or sign < 0 else text,
                )  # fmt: skip
                seen.add(text)
                base[x] += part


def _box_note(table: pd.DataFrame, weight: str) -> str:
    """Say what the whiskers are, how many values a box holds and what weights them."""
    low, high = int(table["n"].min()), int(table["n"].max())
    whiskers = "5 to 95 %" if low >= FEW else "min to max"
    if low < FEW <= high:
        whiskers = "5 to 95 %, min to max under ten values"
    count = str(low) if low == high else f"{low} to {high}"
    return textwrap.fill(BOX_NOTE.format(whiskers=whiskers, count=count, weight=weight), NOTE_WIDTH)


def draw(ax: Any, data: GroupsData, theme: Theme) -> None:
    """Draw vertical bars or boxes, one colour per member, sources side by side.

    Bars of several members sit side by side, or stacked when ``stack`` is set,
    positive parts above zero and negative parts below, as the stacked series do.
    A box is drawn from its five numbers with ``Axes.bxp``, never recomputed. The
    observed source takes the ``observed`` role. A zero line is drawn when values
    change sign. ``sign_rule`` is written as the right title. Long category names
    turn 45 degrees. Axes go through ``static.style_axes``, legend above the axes
    when there are several members or sources.
    """
    table = data.table
    cats = list(dict.fromkeys(table["category"]))
    if data.log:
        ax.set_yscale("log")
    if data.boxes:
        _draw_boxes(ax, table, theme, cats)
        low, high = np.nanmin(table["low"]), np.nanmax(table["high"])
        if not data.log:
            ax.set_ylim(low - 0.05 * (high - low), high + 0.05 * (high - low))
    else:
        _draw_bars(ax, table, data.stack, theme, cats)
    numbers = table[["value", "low", "high"]].to_numpy(float)
    if np.nanmin(numbers) < 0 < np.nanmax(numbers):
        ax.axhline(0, color=theme.ink, linewidth=theme.line_width, zorder=3)
    ax.set_ylabel(data.label)
    static.style_axes(ax, theme)
    ax.grid(False, axis="x")
    ax.set_xticks(range(len(cats)), [textwrap.fill(c, NOTE_WIDTH // 4) for c in cats])
    ax.set_xlim(-0.6, len(cats) - 0.4)
    if len(cats) > 6 and max(map(len, cats)) > 6:
        ax.tick_params(axis="x", labelrotation=45)
        for text in ax.get_xticklabels():
            text.set_horizontalalignment("right")
    if data.sign_rule:
        ax.set_title(data.sign_rule, loc="right", **static.text_style(theme))
    if data.boxes:
        ax.set_xlabel(_box_note(data.table, data.weight), **static.text_style(theme))
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)
