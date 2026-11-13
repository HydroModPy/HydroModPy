"""Distribution frame: the values of one variable against how often they occur.

It draws a histogram by default and the exceedance curve with ``cumulative``,
which gives the flow duration curve of a series and the hypsometric curve of
``topography``. A field is weighted by cell area over a zone at one instant, a
series by period length over its periods. It draws no boxes: boxes per category
are the job of the groups frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import static, variables
from hydromodpy.display.frames.map import stored_field
from hydromodpy.display.frames.series import observed_on, zone_area, zone_cells
from hydromodpy.display.request import (
    AGAINST_OBSERVED,
    ZONE_PREFIX,
    PanelRequest,
    is_trial_column,
)
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_mesh,
    read_period_seconds,
    read_series,
    read_trial_column,
    refuse_fields,
    refuse_set,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session

FIELDS = (
    "variable", "time", "layer", "station", "observed", "scale", "reduce", "against",
    "cumulative",
)  # fmt: skip
HISTOGRAM_COLUMNS = ("source", "low", "high", "share")
EXCEEDANCE_COLUMNS = ("source", "value", "exceedance")
MAX_BINS = 50
"""A histogram never has more bins than this."""


@dataclass(frozen=True, slots=True)
class DistributionData:
    """What a distribution panel draws.

    With ``exceedance`` false, ``table`` has the columns of ``HISTOGRAM_COLUMNS``,
    one row per bin and source: ``source`` is ``simulated`` or ``observed``, ``low``
    and ``high`` are the bin edges in the display unit (float64), ``share`` is the
    weight in the bin over the total weight, so a log axis that leaves rows out sums to less than 1, a fraction from 0 to 1. Both sources
    share the same edges. With ``exceedance`` true, ``table`` has the columns of
    ``EXCEEDANCE_COLUMNS``, one row per value and source, values in decreasing
    order: ``exceedance`` is the share of weight whose value is at least ``value``.

    ``label`` is the value axis label with its unit. ``weight`` is ``area`` for a
    field and ``time`` for a series or ``trials`` for a session, and gives the
    frequency axis label (``Share of area (%)``, ``Exceedance, share of time
    (%)``). ``log`` sets the value axis to a log scale. ``dropped`` is the largest share
    over the sources of weight at zero or below that a log axis leaves out, 0.0 otherwise.
    ``residual`` is true for ``against = "observed"``.
    """

    table: pd.DataFrame
    label: str
    weight: str
    log: bool
    exceedance: bool
    dropped: float = 0.0
    residual: bool = False
    trials: tuple[int, int] | None = None


def _check(subject: Run | Session, panel: PanelRequest) -> str:
    """Refuse what a distribution cannot draw and return the one variable name."""
    refuse_fields("distribution", panel, FIELDS)
    if panel.against not in (None, AGAINST_OBSERVED):
        raise FigureNotApplicable(f"A distribution can only be drawn against {AGAINST_OBSERVED!r}.")
    if not panel.variable or len(panel.variable) != 1 or isinstance(panel.station, list):
        raise FigureNotApplicable("A distribution takes one variable and one station.")
    name = panel.variable[0]
    if isinstance(subject, Session):
        if not is_trial_column(name):
            raise FigureNotApplicable("A distribution of a session takes a trials.<column>.")
        for field in ("time", "layer", "station", "observed", "reduce", "against"):
            refuse_set("distribution", panel, field, "the trials of a session have no such axis")
        return name
    if variables.scale(name) == "categorical" and panel.reduce != "frequency":
        raise FigureNotApplicable(
            f"{name!r} is categorical. Use type = 'groups' for its class shares, or "
            "reduce = 'frequency' for the share of steps."
        )
    return name


def _sample(subject: Run, name: str, panel: PanelRequest) -> tuple[pd.DataFrame, str]:
    """Return one row per cell or period with ``weight``, ``simulated`` and maybe ``observed``."""
    station = panel.station
    zone = station is None or station.startswith(ZONE_PREFIX)
    against = panel.against == AGAINST_OBSERVED
    if zone and subject.has_field(name):
        if against:
            raise FigureNotApplicable(f"{name!r} has no observed field to subtract.")
        refuse_set("distribution", panel, "observed", "a field has no observed record")
        mesh = read_mesh(subject)
        cells = zone_cells(mesh, station)
        values = stored_field(subject, name, panel)
        if panel.reduce != "frequency":
            values = variables.to_display(name, values, area=mesh.areas)
        return pd.DataFrame({"weight": mesh.areas[cells], "simulated": values[cells]}), "area"
    refuse_set("distribution", panel, "layer", "a series has no layer")
    refuse_set("distribution", panel, "reduce", "a series is not reduced over time")
    sim = read_series(subject, name, station=station, window=panel.window)
    area = zone_area(subject, station)
    frame = pd.DataFrame({"simulated": variables.to_display(name, sim.to_numpy(), area=area)})
    try:
        frame["weight"] = read_period_seconds(subject, sim.index)
    except FigureNotApplicable:
        frame["weight"] = 1.0
    if panel.observed or against:
        try:
            obs = observed_on(subject, name, station, sim.index)
        except FigureNotApplicable:
            if against:
                raise
            # No record here: the panel then shows the simulation alone.
        else:
            frame["observed"] = variables.to_display(name, obs.to_numpy(), area=area)
    return frame, "time"


def _label(name: str, panel: PanelRequest) -> str:
    if panel.reduce == "frequency":
        return variables.FREQUENCY_LABEL
    head, unit = variables.label_parts(name)
    if panel.against == AGAINST_OBSERVED:
        head = "Residual, simulated minus observed"
    return variables.join_unit(head, unit)


def _histogram(
    sources: dict[str, tuple[np.ndarray, np.ndarray]], log: bool, total: float
) -> pd.DataFrame:
    """Bin every source on the same edges and return its shares of the total weight."""
    every = np.concatenate([values for values, _ in sources.values()])
    edges = np.histogram_bin_edges(np.log10(every) if log else every, bins="auto")
    if len(edges) - 1 > MAX_BINS:
        edges = np.histogram_bin_edges(np.log10(every) if log else every, bins=MAX_BINS)
    shown = 10.0**edges if log else edges
    rows = []
    for source, (values, weights) in sources.items():
        mass, _ = np.histogram(np.log10(values) if log else values, edges, weights=weights)
        share = mass / total
        rows.append(
            pd.DataFrame({"source": source, "low": shown[:-1], "high": shown[1:], "share": share})
        )
    return pd.concat(rows, ignore_index=True)


def _exceedance(values: np.ndarray, weights: np.ndarray, total: float, source: str) -> pd.DataFrame:
    """Return the values from the largest down, with the share of weight at or above each."""
    order = np.argsort(-values, kind="stable")
    share = pd.Series(np.cumsum(weights[order]) / total)
    frame = pd.DataFrame({"source": source, "value": values[order], "exceedance": share})
    frame["exceedance"] = frame.groupby("value", sort=False)["exceedance"].transform("max")
    return frame


def data(subject: Run | Session, panel: PanelRequest) -> DistributionData:
    """Read the sample of one variable and its weights, then bin it or sort it.

    A field is read with ``read_field`` at ``panel.time`` (``"last"`` when unset)
    and ``panel.layer``, after ``reduce`` as on a map, on the cells of the zone of
    ``station`` (``zone:catchment`` when unset), weighted by ``MeshView.areas``. A
    series is read with ``read_series`` at the station of the panel over the
    window of ``time``, weighted by ``read_period_seconds``, or by one per period
    for a run without dates. ``observed = true`` adds the record of
    ``read_observed`` as a second source, and both sources then keep only the
    periods where both are finite, so they describe the same sample. ``against =
    "observed"`` replaces the sample by simulated minus observed on those periods.
    A ``Session`` subject reads one column ``trials.<column>`` with one weight per trial,
    on log bins when the parameter was searched in log space.

    ``cumulative`` gives the exceedance curve. Otherwise the bin edges come from
    ``numpy.histogram_bin_edges(values, bins="auto")`` with at most ``MAX_BINS``
    bins, equally spaced in log10 on a log axis. ``log`` follows ``variables.is_log``
    and the panel ``scale``; for a residual only ``scale`` decides. A categorical
    variable is refused unless ``reduce = "frequency"`` makes it a share, and the
    refusal points at the groups frame. ``by``, ``change``, ``stack`` and a list of
    variables are refused. One variable and one station only.
    """
    name = _check(subject, panel)
    if isinstance(subject, Session):
        column = read_trial_column(subject, name, panel.scale)
        frame = pd.DataFrame({"weight": 1.0, "simulated": column.values.to_numpy()})
        weight, label, log, ran = "trials", column.label, column.log, column.ran
    else:
        frame, weight = _sample(subject, name, panel)
        label, log, ran = None, None, None
    against = panel.against == AGAINST_OBSERVED
    if against:
        frame["simulated"] = frame["simulated"] - frame["observed"]
        frame = frame.drop(columns="observed")
    if "observed" in frame:
        frame = frame[np.isfinite(frame["observed"])]
    frame = frame[np.isfinite(frame["simulated"]) & (frame["weight"] > 0)]
    if frame.empty:
        raise FigureNotApplicable(f"{name!r} has no finite value to draw in this panel.")
    if log is None:
        log = panel.scale == "log" if against else variables.is_log(name, panel.scale)
    total = float(frame["weight"].sum())
    sources, dropped = {}, 0.0
    for source in (c for c in ("simulated", "observed") if c in frame):
        keep = frame[frame[source] > 0] if log else frame
        dropped = max(dropped, 1.0 - float(keep["weight"].sum()) / total)
        sources[source] = (keep[source].to_numpy(float), keep["weight"].to_numpy(float))
    if not len(sources["simulated"][0]):
        raise FigureNotApplicable(f"{name!r} has no value above zero for a log axis.")
    if panel.cumulative:
        table = pd.concat(
            [_exceedance(v, w, total, s) for s, (v, w) in sources.items()], ignore_index=True
        )
    else:
        table = _histogram(sources, log, total)
    columns = EXCEEDANCE_COLUMNS if panel.cumulative else HISTOGRAM_COLUMNS
    return DistributionData(
        table[list(columns)],
        label or _label(name, panel),
        weight,
        log,
        panel.cumulative,
        dropped,
        against,
        trials=None if ran is None else (len(frame), ran),
    )


def draw(ax: Any, data: DistributionData, theme: Theme) -> None:
    """Draw a step histogram, or the exceedance curve, one colour role per source.

    The histogram draws the outline of the bins (``stairs``) of the ``simulated``
    and ``observed`` roles, the share in percent on the y axis. The exceedance
    curve draws exceedance in percent on x from 0 to 100 and the value on y, so a
    flow duration curve and a hypsometric curve read as usual. ``dropped`` above
    zero writes a small note naming the share left out. A residual draws a zero
    line. Axes go through ``static.style_axes``, legend above when two sources.
    """
    table, many = data.table, data.table["source"].nunique() > 1
    for source, rows in table.groupby("source", sort=False):
        style = static.line_style(theme, "observed" if source == "observed" else "simulated")
        if data.exceedance:
            ax.plot(rows["exceedance"] * 100, rows["value"], label=source, **style)
        else:
            edges = np.append(rows["low"].to_numpy(), rows["high"].iloc[-1])
            ax.stairs(rows["share"] * 100, edges, label=source, **style)
    on_y = data.exceedance
    if data.log:
        (ax.set_yscale if on_y else ax.set_xscale)("log")
    if data.residual:
        (ax.axhline if on_y else ax.axvline)(
            0, color=theme.ink, linewidth=theme.line_width, zorder=3
        )
    share = f"share of {data.weight} (%)"
    frequency = f"Exceedance, {share}" if on_y else f"Share of {data.weight} (%)"
    (ax.set_ylabel if on_y else ax.set_xlabel)(data.label)
    (ax.set_xlabel if on_y else ax.set_ylabel)(frequency)
    if on_y:
        ax.set_xlim(0, 100)
    else:
        ax.set_ylim(bottom=0)
    static.style_axes(ax, theme)
    static.dropped_note(ax, data.dropped, data.weight, theme)
    if many:
        static.legend(ax, theme)
