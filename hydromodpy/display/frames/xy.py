"""XY frame: one variable against another, one point per matched row.

It draws a cloud of points, simulated against observed for one series, two series
of one station period by period, two fields cell by cell, or two columns of the
trials of a session. It adds the one-to-one line, horizontal reference lines and
the scores of the run. It draws no colour by a third variable and no fitted line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import static, variables
from hydromodpy.display.frames.series import (
    observed_on,
    score_text,
    scores,
    zone_area,
    zone_cells,
)
from hydromodpy.display.request import PanelRequest, ReferenceValue
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_field,
    read_mesh,
    read_series,
    refuse_fields,
    refuse_set,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.field_registry import TIME_SERIES_REGISTRY
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session

FIELDS = ("variable", "time", "layer", "station", "observed", "scores", "scale", "reference")
BIG = 2000
"""Beyond this many points the markers shrink, turn half transparent and are rasterised."""
XY_COLUMNS = ("key", "station", "x", "y")


@dataclass(frozen=True, slots=True)
class XYData:
    """What an xy panel draws.

    ``table`` has the columns of ``XY_COLUMNS``, one row per matched pair where
    both values are finite. ``key`` says what a row is: the period START
    (datetime64, or the period number of a run without dates) for two series, the
    face index (int64) for two fields, the trial number (int64) for a session.
    ``station`` is the station of the panel, None for fields and trials. ``x`` and
    ``y`` are float64 in the display unit of their variable.

    ``x_label`` and ``y_label`` carry the unit, ``Observed discharge (m3/s)`` and
    ``Simulated discharge (m3/s)`` for a series against its record. ``log_x`` and
    ``log_y`` set the axis scales. ``one_to_one`` draws the line y = x over the
    common range of both axes, and then both axes share their limits. ``references``
    holds value and label of each horizontal line. ``scores`` holds the rows of
    ``run.metrics`` for the variable and station, None when the panel did not ask.
    ``dropped`` is the share of the matched rows a log axis leaves out. ``window`` is the
    scoring window of ``scores`` as two timestamps when the metrics carry it, and ``draw``
    lightens the points outside it.
    """

    table: pd.DataFrame
    x_label: str
    y_label: str
    log_x: bool
    log_y: bool
    one_to_one: bool = False
    references: tuple[tuple[float, str], ...] = ()
    scores: pd.DataFrame | None = None
    dropped: float = 0.0
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None


def data(subject: Run | Session, panel: PanelRequest) -> XYData:
    """Read the two members of the pair and keep the rows where both are finite.

    ``variable`` holds one name with ``observed = true``, read as observed on x and
    simulated on y through ``read_series`` and ``read_observed`` on the periods of
    ``read_series``, or two names ``[x, y]``. Two series are read at the one
    station of the panel and joined on their period index; a list of stations is
    refused. Two fields are read with ``read_field`` at ``panel.time`` (``"last"``
    when unset) and ``panel.layer``, on the cells of the zone of ``station``
    (``zone:catchment`` when unset), and joined on the face index. A series paired
    with a field is refused. ``time`` as a pair keeps the periods between them,
    as on a series.

    A ``Session`` subject reads ``read_table(session, "trials")``, and the two names
    are its columns, ``cost`` or a searched parameter. ``facet = "parameter"``
    reaches this frame with the token already replaced by ``render``. The session
    columns and their kinds come with a later lot, so this branch is refused in
    this version.

    The display unit comes from ``variables.to_display``. ``scale`` sets both axes
    when given, else each axis follows ``variables.is_log`` of its variable, and
    a log axis drops the rows at zero or below. ``reference`` takes ``one_to_one``,
    ``zero`` and values. ``scores`` asks ``run.metrics`` for the one variable and
    station, as the series frame does. Any other panel field is refused.
    """
    if isinstance(subject, Session):
        raise FigureNotApplicable(
            "An xy panel cannot read the trials of a session yet: the session columns come "
            "with a later version."
        )
    refuse_fields("xy", panel, FIELDS)
    names = list(panel.variable or ())
    if len(names) == 1 and panel.observed:
        names = [names[0], names[0]]
    elif len(names) != 2 or panel.observed:
        raise FigureNotApplicable(
            "An xy panel needs two variables, or one variable with observed = true, not both."
        )
    if isinstance(panel.station, list):
        raise FigureNotApplicable("An xy panel draws one station, not a list of stations.")
    if panel.scores and not panel.observed:
        raise FigureNotApplicable("The scores of a run exist for one variable against its record.")
    series = panel.observed or names[0] in TIME_SERIES_REGISTRY
    if series:
        refuse_set("xy", panel, "layer", "a series has no layer")
    if panel.observed:
        table = _series_pair(subject, panel, names, observed=True)
    elif sum(name in TIME_SERIES_REGISTRY for name in names) == 1:
        raise FigureNotApplicable(
            f"{names[0]!r} and {names[1]!r} cannot be paired: a series and a field have no common rows."
        )
    elif names[0] in TIME_SERIES_REGISTRY:
        table = _series_pair(subject, panel, names, observed=False)
    else:
        table = _field_pair(subject, panel, names)
    log = [variables.is_log(name, panel.scale) for name in names]
    table = table[np.isfinite(table[["x", "y"]]).all(axis=1)]
    matched = len(table)
    for column, is_log in zip(("x", "y"), log, strict=True):
        table = table[table[column] > 0] if is_log else table
    if table.empty:
        raise FigureNotApplicable(
            f"No row of {names[0]!r} and {names[1]!r} has both values finite."
        )
    refs = panel.reference or ()
    found = scores(subject, [(names[0], panel.station)]) if panel.scores else None
    return XYData(
        table=table.reset_index(drop=True),
        x_label=_label(names[0], "Observed" if panel.observed else None),
        y_label=_label(names[1], "Simulated" if panel.observed else None),
        log_x=log[0],
        log_y=log[1],
        one_to_one="one_to_one" in refs,
        references=tuple(
            (r.value, r.label) if isinstance(r, ReferenceValue) else (0.0, "zero")
            for r in refs
            if r != "one_to_one"
        ),
        scores=found,
        dropped=1.0 - len(table) / matched,
        window=_window(found),
    )


def _window(found: pd.DataFrame | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return the one scoring window of the metrics, None without scores or with several."""
    if found is None or not {"window_start", "window_end"} <= set(found.columns):
        return None
    starts, ends = found["window_start"].dropna().unique(), found["window_end"].dropna().unique()
    if len(starts) != 1 or len(ends) != 1:
        return None
    return pd.Timestamp(starts[0]), pd.Timestamp(ends[0])


def _label(name: str, prefix: str | None) -> str:
    """Return the axis label, ``Observed discharge (m3/s)`` when a prefix is given."""
    head, unit = variables.label_parts(name)
    if prefix is not None:
        head = f"{prefix} {head[:1].lower() + head[1:]}"
    return variables.join_unit(head, unit)


def _series_pair(run: Run, panel: PanelRequest, names: list[str], observed: bool) -> pd.DataFrame:
    """Join two series, or a series and its record, on their period index."""
    window = panel.window
    area = zone_area(run, panel.station)
    sim = [read_series(run, n, station=panel.station, window=window) for n in dict.fromkeys(names)]
    if observed:
        record = observed_on(run, names[0], panel.station, sim[0].index)
        pair = [record, sim[0]]
    else:
        pair = sim if len(sim) == 2 else sim * 2
        if not pair[0].index.equals(pair[1].index):
            raise FigureNotApplicable(
                f"{names[0]!r} and {names[1]!r} are not on the same periods ({len(pair[0])} "
                f"against {len(pair[1])} rows, or a state beside a flux), so they cannot be paired."
            )
    x, y = (
        variables.to_display(n, p.to_numpy(), area=area) for n, p in zip(names, pair, strict=True)
    )
    return pd.DataFrame({"key": pair[0].index, "station": panel.station, "x": x, "y": y})


def _field_pair(run: Run, panel: PanelRequest, names: list[str]) -> pd.DataFrame:
    """Join two fields on the cells of a zone, read at one instant."""
    if isinstance(panel.time, list):
        raise FigureNotApplicable("Two fields are read at one instant, not over a window.")
    mesh = read_mesh(run)
    cells = np.flatnonzero(zone_cells(mesh, panel.station))
    time = "last" if panel.time is None else panel.time
    values = [read_field(run, n, time=time, layer=panel.layer) for n in names]
    if values[0].shape != values[1].shape:
        raise FigureNotApplicable(f"{names[0]!r} and {names[1]!r} do not share their cells.")
    x, y = (
        variables.to_display(n, v[cells], area=mesh.areas[cells])
        for n, v in zip(names, values, strict=True)
    )
    return pd.DataFrame({"key": cells.astype("int64"), "station": None, "x": x, "y": y})


def draw(ax: Any, data: XYData, theme: Theme) -> None:
    """Draw the points as small markers of the ``simulated`` role, without edges.

    Beyond 2,000 points the markers shrink and turn half transparent and are
    rasterised. The one-to-one line is a thin ink line, the references dashed
    lines of the ``bounds`` role. Axes go through ``static.style_axes``. The scores
    are written as the right title with the text the series frame writes, read
    from ``KEY_SCORES`` and its score text in ``frames/series.py``.
    """
    table = data.table
    big = len(table) > BIG
    style = static.line_style(theme, "simulated")
    inside = np.ones(len(table), dtype=bool)
    if data.window is not None and pd.api.types.is_datetime64_any_dtype(table["key"]):
        inside = ((table["key"] >= data.window[0]) & (table["key"] <= data.window[1])).to_numpy()
    for hit, alpha, text in (
        (inside, 0.5 if big else 0.8, None),
        (~inside, 0.2, "Outside scoring window"),
    ):
        if hit.any():
            ax.scatter(
                table["x"][hit], table["y"][hit], s=1.5 if big else 6, color=style["color"],
                alpha=alpha, linewidths=0, rasterized=big, zorder=3, label=text,
            )  # fmt: skip
    for scale, axis in ((data.log_x, "x"), (data.log_y, "y")):
        if scale:
            getattr(ax, f"set_{axis}scale")("log")
    ax.set_xlabel(data.x_label)
    ax.set_ylabel(data.y_label)
    static.style_axes(ax, theme)
    for value, text in data.references:
        if value > 0 or not data.log_y:
            ax.axhline(value, color=theme.roles["bounds"], linewidth=theme.line_width, linestyle="--", label=None if text == "zero" else text, zorder=2)  # fmt: skip
    if data.one_to_one:
        both = table[["x", "y"]].to_numpy()
        low, high = both.min(), both.max()
        if data.log_x or data.log_y:
            low, high = low / 1.15, high * 1.15
        else:
            pad = 0.05 * (high - low or 1.0)
            low, high = low - pad, high + pad
        ax.plot([low, high], [low, high], color=theme.ink, linewidth=theme.line_width, label="1:1", zorder=2)  # fmt: skip
        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.set_aspect("equal", adjustable="box")
    if data.scores is not None and len(data.scores):
        text = score_text(data.scores, many=False)
        if text:
            if data.one_to_one:
                # Square axes are narrow, so the text goes inside them, two scores a line.
                parts = text.split("   ")
                rows = [p for p in parts if not p.startswith("(")]
                lines = ["   ".join(rows[i : i + 2]) for i in range(0, len(rows), 2)]
                static.note(ax, "\n".join(lines + parts[len(rows) :]), theme, loc="upper left")
            else:
                ax.set_title(text, loc="right", **static.text_style(theme))
    static.dropped_note(ax, data.dropped, "points", theme, loc="lower right")
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)
