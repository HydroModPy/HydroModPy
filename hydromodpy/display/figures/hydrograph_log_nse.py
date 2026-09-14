"""The transient hydrograph on the axis its score is computed on.

The second stage calibrates storage against discharge with ``nse_log``, a
Nash-Sutcliffe efficiency taken on log-transformed series. That transform is
what puts the weight on the recessions, so a linear hydrograph hides exactly
the samples the score reads. This figure draws the same series on a log axis,
splits the total into its drainage and runoff contributions, since the ratio
between the two is what the storage parameter actually moves, shades the
window whose samples entered the score and annotates the score itself.

The scoring window and the ``NSElog`` value are calibration notions and this
layer may not reach into ``calibration``, so both arrive as ``render()``
arguments. Without them the hydrograph is still drawn, unshaded and
unannotated: this figure must stay readable on a plain run.

A log axis and a discharge that reaches zero do not mix. The convention here
is the metric's own: ``log_nse`` adds an offset ``eps`` before taking the
logarithm, so a non-positive sample is not dropped from the score, it enters
it as ``log(eps)``. The figure therefore draws every non-positive sample on
the floor ``eps`` rather than dropping it, marks each one and counts them in
the annotation. A sample that never was, a failed timestep, is a different
thing: it stays NaN and breaks the line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.units.labels import AXIS_LABELS, axis_label
from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import style_date_axis
from hydromodpy.results.derive.time_alignment import (
    normalize_datetime_series,
    observed_on_simulation_index,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

SPLIT_COLORS: dict[str, str] = {
    "total": HIGH_CONTRAST_TRIPLET[0],
    "drainage": HIGH_CONTRAST_TRIPLET[2],
    "runoff": HIGH_CONTRAST_TRIPLET[1],
}
"""One colour per curve of the split, darkest for the total they sum to.

The three lightnesses are far apart, so the split survives a greyscale print
and every common colour-vision deficiency.
"""

OBSERVED_COLOR = "black"
FLOOR_FRACTION = 0.01
"""Fraction of the median observed flow used as the log floor.

Same rule as the ``eps`` :func:`hydromodpy.core.metrics.log_nse` picks when
none is given, so the floor of the figure is the floor of the score.
"""

_DEFAULT_VARIABLE = "discharge"
_WINDOW_COLOR = "0.82"


@register
class HydrographLogNseFigure(BaseFigure):
    """Simulated and observed discharge on a log axis, split and scored.

    ``drainage`` and ``runoff`` may be passed as series aligned on the
    simulation index; otherwise they are read from the run under
    ``drainage_variable`` / ``runoff_variable``. One of the two is enough:
    the other follows by difference from the total, and says so in its label.
    """

    spec = FigureSpec(
        name="hydrograph_log_nse",
        title="Hydrograph on a log axis with NSElog",
        kind="comparison",
        required_tables=("timeseries",),
        default_figsize=(8.8, 5.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Refuse only a run holding no discharge series at all.

        Everything else this figure draws is optional: the observations, the
        split, the window and the score. The check runs on the default
        variable, which is the one a gallery renders.
        """
        if not sim.has_table("timeseries"):
            return "missing catalog table(s): timeseries, so no discharge series"
        try:
            stations = list(sim.stations(_DEFAULT_VARIABLE))
        except Exception:
            return None
        if not stations:
            return f"the run holds no simulated {_DEFAULT_VARIABLE!r} series"
        return None

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        station: str = "_catchment",
        variable: str = _DEFAULT_VARIABLE,
        drainage: pd.Series | np.ndarray | None = None,
        runoff: pd.Series | np.ndarray | None = None,
        drainage_variable: str = "drainage",
        runoff_variable: str = "runoff",
        scoring_window: tuple[Any, Any] | None = None,
        nse_log: float | None = None,
        floor: float | None = None,
        **_,
    ) -> Axes:
        total = normalize_datetime_series(sim.timeseries(variable, station=station))
        index = pd.DatetimeIndex(total.index)
        observed = _observed_series(sim, variable, index)
        components, split_note = _split(
            sim,
            total,
            station=station,
            drainage=drainage,
            runoff=runoff,
            drainage_variable=drainage_variable,
            runoff_variable=runoff_variable,
        )
        level = _log_floor(floor, observed, total)

        window = _shade_window(ax, scoring_window, index)

        on_floor: list[tuple[str, int, np.ndarray]] = []
        for label, series, color, style, width in (
            ("simulated total", total, SPLIT_COLORS["total"], "-", 1.8),
            *[
                (label, series, SPLIT_COLORS[key], style, 1.2)
                for key, label, series, style in components
            ],
        ):
            clipped = _draw_series(
                ax, series, color=color, label=label, ls=style, lw=width, floor=level
            )
            if clipped.size:
                on_floor.append((label, clipped.size, clipped))
        for station_id, series in observed:
            _draw_series(
                ax,
                series,
                color=OBSERVED_COLOR,
                label=f"observed ({station_id})",
                ls="--",
                lw=1.0,
                floor=level,
                alpha=0.85,
            )

        if on_floor:
            ax.plot(
                np.concatenate([positions for _, _, positions in on_floor]),
                np.full(sum(count for _, count, _ in on_floor), level),
                ls="none",
                marker="x",
                ms=5.5,
                color="0.25",
                zorder=6,
                label="on the log floor (drawn there, not dropped)",
            )

        ax.set_yscale("log")
        _set_log_limits(ax, level)
        ax.set_xlabel("Date")
        ax.set_ylabel(axis_label(variable))
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(f"Hydrograph on a log axis - {sim.name or sim.sim_id} @ {station}")
        # The legend takes the upper right and the note the upper left: a
        # hydrograph puts its peaks high and its recessions low, and "best"
        # ignores annotations, so pinning both keeps them from stacking.
        ax.legend(loc="upper right", fontsize=8.5, framealpha=0.9)
        ax.annotate(
            "\n".join(
                _note_lines(
                    nse_log=nse_log,
                    window=window,
                    n_samples=int(index.size),
                    split_note=split_note,
                    variable=variable,
                    has_total=_has_data(total),
                    has_observed=bool(observed),
                    floor=level,
                    unit=_unit_of(variable),
                    on_floor=[(label, count) for label, count, _ in on_floor],
                )
            ),
            xy=(0.02, 0.98),
            xycoords="axes fraction",
            ha="left",
            va="top",
            fontsize=8.5,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=7,
        )
        style_date_axis(ax)
        return ax


def _draw_series(
    ax: Axes,
    series: pd.Series,
    *,
    color: str,
    label: str,
    ls: str,
    lw: float,
    floor: float,
    alpha: float = 1.0,
) -> np.ndarray:
    """Draw one series on the log axis and return the abscissas it floored.

    A sample at or below ``floor`` is moved onto it, because the score reads
    it there too. A NaN stays a NaN, so the line breaks where a timestep
    produced nothing instead of dropping to a flow that was never simulated.
    """
    values = series.to_numpy(dtype="float64")
    floored = np.isfinite(values) & (values <= floor)
    # A steady run has one stress period, so its "hydrograph" is one or two
    # points and a line through them is invisible. The sibling figure
    # hydrograph_sim_obs.py marks those the same way.
    marker = "o" if len(series) <= 2 else None
    ax.plot(
        series.index,
        np.where(floored, floor, values),
        color=color,
        ls=ls,
        lw=lw,
        alpha=alpha,
        label=label,
        marker=marker,
        zorder=4,
    )
    return np.asarray(pd.DatetimeIndex(series.index)[floored])


def _set_log_limits(ax: Axes, floor: float) -> None:
    """Frame the panel on the floor, with room above the peaks.

    The legend and the note sit in the upper corners of a hydrograph, which
    is also where its peaks are; a factor five of headroom keeps them from
    covering the storms a reader came to see.
    """
    peaks = [
        float(np.nanmax(line.get_ydata()))
        for line in ax.lines
        if np.any(np.isfinite(np.asarray(line.get_ydata(), dtype="float64")))
    ]
    if not peaks:
        return
    ax.set_ylim(floor / 1.6, max(peaks) * 5.0)


def _observed_series(
    sim: Run,
    variable: str,
    index: pd.DatetimeIndex,
) -> list[tuple[str, pd.Series]]:
    """Return every observed gauge aligned on the simulation index.

    A run with no observation is a normal run here, not a failure: the second
    stage may be replayed on a period no gauge covers, and the hydrograph is
    still the thing to look at.
    """
    try:
        frame = sim.observed(variable)
    except Exception:
        return []
    aligned: list[tuple[str, pd.Series]] = []
    for station_id, group in frame.groupby("station_id"):
        series = normalize_datetime_series(group.set_index("datetime")["value"])
        on_index = observed_on_simulation_index(series, index)
        if not bool(np.any(np.isfinite(on_index.to_numpy(dtype="float64")))):
            continue
        aligned.append((str(station_id), on_index))
    return aligned


def _split(
    sim: Run,
    total: pd.Series,
    *,
    station: str,
    drainage: pd.Series | np.ndarray | None,
    runoff: pd.Series | np.ndarray | None,
    drainage_variable: str,
    runoff_variable: str,
) -> tuple[list[tuple[str, str, pd.Series, str]], str | None]:
    """Return the drawable components of the split, and what is missing.

    Each component is ``(key, label, series, linestyle)``. One component is
    enough: the catchment accounting has the total as the sum of the two, so
    the other follows by difference and its label says which one it is.
    """
    index = pd.DatetimeIndex(total.index)
    parts = {
        "drainage": _usable(
            _component(sim, drainage, drainage_variable, station=station, index=index)
        ),
        "runoff": _usable(_component(sim, runoff, runoff_variable, station=station, index=index)),
    }
    derived: set[str] = set()
    if parts["drainage"] is None and parts["runoff"] is not None:
        parts["drainage"] = total - parts["runoff"]
        derived.add("drainage")
    elif parts["runoff"] is None and parts["drainage"] is not None:
        parts["runoff"] = total - parts["drainage"]
        derived.add("runoff")
    if parts["drainage"] is None:
        return [], (
            "no drainage / runoff split available on this run: the total only, "
            "pass drainage= or runoff= to show what the storage parameter moves"
        )
    labels = {"drainage": "drainage (groundwater", "runoff": "runoff (surface"}
    components = [
        (
            key,
            f"{labels[key]}, by difference)" if key in derived else f"{labels[key]})",
            parts[key],
            "-." if key == "drainage" else ":",
        )
        for key in ("drainage", "runoff")
    ]
    return components, None


def _usable(series: pd.Series | None) -> pd.Series | None:
    """Drop a component holding no finite sample.

    A series read from the run or handed in on another clock reindexes to all
    NaN. Kept, it would put a curve in the legend that draws nothing, which a
    reader takes for a split gone off the panel rather than for a split the
    run does not carry.
    """
    if series is None or not _has_data(series):
        return None
    return series


def _has_data(series: pd.Series) -> bool:
    """Whether a series carries at least one sample that can be drawn."""
    return bool(np.any(np.isfinite(series.to_numpy(dtype="float64"))))


def _component(
    sim: Run,
    given: pd.Series | np.ndarray | None,
    variable: str,
    *,
    station: str,
    index: pd.DatetimeIndex,
) -> pd.Series | None:
    """Return one component of the split, from the argument or from the run."""
    if given is not None:
        return _on_index(given, index, variable)
    try:
        series = sim.timeseries(variable, station=station)
    except Exception:
        return None
    return normalize_datetime_series(series).reindex(index)


def _on_index(values: pd.Series | np.ndarray, index: pd.DatetimeIndex, label: str) -> pd.Series:
    """Put a caller-supplied component on the simulation index."""
    if isinstance(values, pd.Series):
        return normalize_datetime_series(values).reindex(index)
    array = np.asarray(values, dtype="float64").reshape(-1)
    if array.size != index.size:
        raise ValueError(
            f"the {label} component holds {array.size} samples, the simulated series "
            f"holds {index.size}."
        )
    return pd.Series(array, index=index)


def _log_floor(
    floor: float | None,
    observed: list[tuple[str, pd.Series]],
    total: pd.Series,
) -> float:
    """Return the flow below which the log axis, like the score, cannot look.

    Mirrors the default ``eps`` of :func:`hydromodpy.core.metrics.log_nse`:
    one percent of the median positive observation, or of the median positive
    simulation when the run carries no observation.
    """
    if floor is not None:
        return float(floor)
    pools = [series for _, series in observed] or [total]
    values = np.concatenate([series.to_numpy(dtype="float64") for series in pools])
    positives = values[np.isfinite(values) & (values > 0.0)]
    median = float(np.median(positives)) if positives.size else 1.0
    return max(1e-9, FLOOR_FRACTION * median)


def _shade_window(
    ax: Axes,
    scoring_window: tuple[Any, Any] | None,
    index: pd.DatetimeIndex,
) -> tuple[pd.Timestamp, pd.Timestamp, int] | None:
    """Shade the scored period and return its bounds and sample count."""
    if scoring_window is None:
        return None
    start, end = (pd.Timestamp(bound) for bound in scoring_window)
    if start > end:
        raise ValueError(f"the scoring window ends ({end}) before it starts ({start}).")
    ax.axvspan(
        start,
        end,
        color=_WINDOW_COLOR,
        alpha=0.55,
        linewidth=0.0,
        zorder=0,
        label="scoring window",
    )
    scored = int(np.sum((index >= start) & (index <= end)))
    return start, end, scored


def _note_lines(
    *,
    nse_log: float | None,
    window: tuple[pd.Timestamp, pd.Timestamp, int] | None,
    n_samples: int,
    split_note: str | None,
    variable: str,
    has_total: bool,
    has_observed: bool,
    floor: float,
    unit: str,
    on_floor: list[tuple[str, int]],
) -> list[str]:
    """Return the annotation, one line per thing a reader must not assume."""
    lines = []
    if not has_total:
        lines.append(f"the simulated {variable} series holds no finite sample: nothing is drawn")
    if nse_log is None:
        lines.append("NSElog not given: the score is a calibration notion, pass nse_log=")
    else:
        lines.append(f"NSElog = {float(nse_log):.3f}")
    if window is None:
        lines.append("no scoring window given: every sample is drawn, none is marked as scored")
    else:
        start, end, scored = window
        lines.append(
            f"scoring window {start:%Y-%m-%d} to {end:%Y-%m-%d}: "
            f"{scored} of {n_samples} samples scored"
        )
    if split_note is not None:
        lines.append(split_note)
    if not has_observed:
        lines.append("no observed series on this run: nothing to score against")
    if on_floor:
        counts = ", ".join(f"{label} {count}" for label, count in on_floor)
        lines.append(f"log floor {floor:.3g} {unit}: {counts} of {n_samples} samples drawn on it")
    return lines


def _unit_of(variable: str) -> str:
    """Return the canonical unit of one variable, for the floor annotation."""
    return AXIS_LABELS.get(variable, (variable, ""))[1]
