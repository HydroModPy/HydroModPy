"""Matplotlib template of the static figures: figure, axes, colorbar, legend and files.

Data artists take their look from ``line_style`` and ``text_style``, and a colormap is always
named, so the output never depends on matplotlib defaults. No function here writes
``rcParams`` or keeps state, so two threads can draw at once.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LogNorm
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import (
    AutoMinorLocator,
    FuncFormatter,
    LogFormatterSciNotation,
    MaxNLocator,
    ScalarFormatter,
)
from matplotlib.transforms import offset_copy

from hydromodpy.display.request import FORMATS, WIDTHS_MM
from hydromodpy.display.theme import Theme

MM = 1 / 25.4
PAD_IN = 3 / 72
SPACE = 0.02


class TimesTenFormatter(ScalarFormatter):
    """Scalar labels with a mathtext offset and no trailing zeros."""

    def __init__(self) -> None:
        super().__init__(useMathText=True, useOffset=False)

    def __call__(self, x: float, pos: int | None = None) -> str:
        label = super().__call__(x, pos)
        head, core, tail = re.match(r"^(\$\\mathdefault\{)?(.*?)(\}\$)?$", label).groups()
        if "." in core:
            core = core.rstrip("0").rstrip(".")
        return f"{head or ''}{core}{tail or ''}"


def line_style(theme: Theme, role: str) -> dict[str, Any]:
    """Keywords of a line that shows the colour role ``role`` at the theme width."""
    return {"color": theme.roles[role], "linewidth": theme.data_line_width}


def text_style(theme: Theme, *, small: bool = True) -> dict[str, Any]:
    """Keywords for ``ax.text`` and ``annotate`` in the theme font."""
    return {
        "family": theme.family,
        "size": theme.small if small else theme.size,
        "color": theme.ink,
        "math_fontfamily": theme.math_family,
    }


def _pin(texts: Any, theme: Theme, **extra: Any) -> None:
    for text in texts:
        text.set(family=theme.family, math_fontfamily=theme.math_family, **extra)


def _pin_ticks(ax: Any, theme: Theme) -> None:
    for axis in (ax.xaxis, ax.yaxis):
        _pin(axis.get_ticklabels(which="both"), theme)
        _pin([axis.get_offset_text()], theme, size=theme.size, color=theme.ink)


def new_figure(
    theme: Theme,
    *,
    width: str | float = "single",
    height_mm: float | None = None,
    nrows: int = 1,
    ncols: int = 1,
    **subplots_kw: Any,
) -> Figure:
    """Return a figure on its own Agg canvas, sized in millimetres, with its axes.

    ``width`` is a column name of ``WIDTHS_MM`` or a number of millimetres. The axes are
    ``fig.axes``, in row order. The height defaults to three quarters of the width per
    row of the grid. No ``pyplot`` and no global state are involved.
    """
    width_mm = float(WIDTHS_MM[width] if isinstance(width, str) else width)
    if height_mm is None:
        height_mm = 0.75 * width_mm * nrows / ncols
    fig = Figure(
        figsize=(width_mm * MM, height_mm * MM),
        dpi=100,
        layout="constrained",
        facecolor=theme.face,
        edgecolor=theme.face,
    )
    fig.get_layout_engine().set(w_pad=PAD_IN, h_pad=PAD_IN, wspace=SPACE, hspace=SPACE)
    FigureCanvasAgg(fig)
    fig.subplots(nrows, ncols, **subplots_kw)
    return fig


def style_axes(ax: Any, theme: Theme, *, grid: bool = True, dates: bool = False) -> None:
    """Set frame, ticks, grid, title and number format on the artists of one axes."""
    for spine in ax.spines.values():
        spine.set_linewidth(theme.line_width)
        spine.set_edgecolor(theme.ink)
    ax.set_facecolor(theme.face)
    common = {
        "direction": "out",
        "top": False,
        "right": False,
        "color": theme.ink,
        "pad": theme.tick_pad,
    }
    ax.tick_params(
        which="major",
        length=theme.tick_size,
        width=theme.line_width,
        labelsize=theme.size,
        labelcolor=theme.ink,
        labelfontfamily=theme.family,
        **common,
    )
    ax.tick_params(
        which="minor", length=theme.minor_tick_size, width=theme.minor_tick_width, **common
    )
    for axis in (ax.xaxis, ax.yaxis):
        if dates and axis is ax.xaxis:
            locator = AutoDateLocator(minticks=3, maxticks=7, interval_multiples=True)
            axis.set_major_locator(locator)
            axis.set_major_formatter(ConciseDateFormatter(locator))
        elif axis.get_scale() == "linear":
            axis.set_minor_locator(AutoMinorLocator())
            axis.set_major_formatter(TimesTenFormatter())
        axis.labelpad = theme.title_pad
        axis.label.set(family=theme.family, size=theme.size, color=theme.ink)
        axis.label.set_math_fontfamily(theme.math_family)
    ax.set_title(ax.get_title(), loc="center", pad=theme.title_pad, fontweight="normal")
    ax.title.set(family=theme.family, size=theme.title_size, color=theme.ink)
    ax.title.set_math_fontfamily(theme.math_family)
    ax.grid(False)
    if grid:
        ax.grid(
            True, which="major", color=theme.ink, alpha=theme.grid_alpha, linewidth=theme.grid_width
        )
        ax.set_axisbelow("line")
    _pin_ticks(ax, theme)


def map_axes(
    ax: Any,
    theme: Theme,
    *,
    extent: tuple[float, float, float, float] | None = None,
    crs: str = "Lambert-93",
    ticks: bool = True,
) -> None:
    """Style a map frame. Equal aspect, no grid, coordinates in km, CRS named in the labels.

    ``extent`` is ``(xmin, ymin, xmax, ymax)`` in metres.
    """
    if extent is not None:
        ax.set_xlim(extent[0], extent[2])
        ax.set_ylim(extent[1], extent[3])
    ax.set_aspect("equal")
    style_axes(ax, theme, grid=False)

    def km(value: float, _pos: int | None = None) -> str:
        km_value = value / 1000
        return f"{km_value:.0f}" if abs(km_value - round(km_value)) < 1e-6 else f"{km_value:.1f}"

    for axis, count in ((ax.xaxis, 5), (ax.yaxis, 3)):
        axis.set_major_locator(MaxNLocator(nbins=count, steps=[1, 2, 5, 10]))
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(FuncFormatter(km))
        axis.set_minor_locator(AutoMinorLocator(1))
    ax.tick_params(axis="y", labelrotation=90)
    for label in ax.get_yticklabels():
        label.set_verticalalignment("center")
    if ticks:
        ax.set_xlabel(f"x ({crs}, km)")
        ax.set_ylabel(f"y ({crs}, km)")
        for axis in (ax.xaxis, ax.yaxis):
            axis.label.set(family=theme.family, size=theme.small, color=theme.muted)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    _pin_ticks(ax, theme)


def scale_bar(
    ax: Any, theme: Theme, *, length_m: float | None = None, loc: str = "lower left"
) -> None:
    """Draw a plain scale bar in data units of metres, a fifth of the map width by default."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    if length_m is None:
        raw = (x1 - x0) / 5
        mag = 10 ** np.floor(np.log10(raw))
        length_m = min((1, 2, 5, 10), key=lambda m: abs(m * mag - raw)) * mag
    x = x0 + 0.05 * (x1 - x0) if "left" in loc else x1 - 0.05 * (x1 - x0) - length_m
    y = y0 + 0.05 * (y1 - y0) if "lower" in loc else y1 - 0.05 * (y1 - y0)
    ax.plot(
        [x, x + length_m],
        [y, y],
        color=theme.ink,
        linewidth=2.0,
        solid_capstyle="butt",
        zorder=20,
        scalex=False,
        scaley=False,
    )
    label = f"{length_m / 1000:g} km" if length_m >= 1000 else f"{length_m:g} m"
    ax.text(
        x + length_m / 2,
        y + 0.012 * (y1 - y0),
        label,
        ha="center",
        va="bottom",
        zorder=20,
        **text_style(theme),
    )


def panel_labels(axes: Any, theme: Theme) -> None:
    """Write (a), (b), ... above the upper left corner of each axes."""
    for i, ax in enumerate(axes):
        ax.text(
            0.0,
            1.02,
            f"({chr(97 + i)})",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            weight="bold",
            **{**text_style(theme), "size": theme.title_size},
        )


def note(ax: Any, text: str, theme: Theme, *, loc: str = "upper left") -> None:
    """Write a small boxed note inside the axes, for a score or a run name."""
    ax.text(
        0.02 if "left" in loc else 0.98,
        0.98 if "upper" in loc else 0.02,
        text,
        transform=ax.transAxes,
        ha="left" if "left" in loc else "right",
        va="top" if "upper" in loc else "bottom",
        bbox={
            "boxstyle": "square,pad=0.3",
            "facecolor": theme.face,
            "edgecolor": theme.ink,
            "linewidth": theme.line_width,
        },
        **text_style(theme),
    )


def colorbar(
    fig: Figure, mappable: Any, ax: Any, theme: Theme, *, label: str, extend: str = "neither"
) -> Any:
    """Put a colorbar as tall as the axes on its right, labelled along the bar."""
    cb = fig.colorbar(
        mappable, ax=ax, fraction=0.05, pad=0.02, aspect=30, shrink=1.0, extend=extend
    )
    cb.outline.set_linewidth(theme.line_width)
    cb.outline.set_edgecolor(theme.ink)
    cb.ax.tick_params(
        which="both",
        direction="out",
        width=theme.line_width,
        length=theme.tick_size * 0.8,
        pad=theme.tick_pad,
        labelsize=theme.small,
        labelcolor=theme.ink,
        labelfontfamily=theme.family,
        color=theme.ink,
    )
    cb.ax.minorticks_off()
    if isinstance(mappable.norm, LogNorm):
        # Every tick of a log bar gets the same a x 10^b label, even below one decade.
        cb.formatter = cb.minorformatter = LogFormatterSciNotation(
            minor_thresholds=(np.inf, np.inf)
        )
    else:
        cb.formatter = TimesTenFormatter()
    cb.update_ticks()
    cb.set_label(label, family=theme.family, size=theme.size, color=theme.ink)
    cb.ax.yaxis.label.set_math_fontfamily(theme.math_family)
    _pin_ticks(cb.ax, theme)
    return cb


LEGEND_ROW_CHARS = 40
"""A legend whose labels hold more characters than this is set on two columns."""


def legend(ax: Any, theme: Theme) -> Any:
    """Put the legend in one row above the axes, right aligned, above the title when there is one."""
    titled = any(ax.get_title(loc=loc) for loc in ("left", "center", "right"))
    lift = theme.title_size + theme.title_pad + 2.0 if titled else 2.0
    anchor = offset_copy(ax.transAxes, fig=ax.figure, y=lift, units="points")
    handles, labels = ax.get_legend_handles_labels()
    wide = sum(map(len, labels)) > LEGEND_ROW_CHARS
    leg = ax.legend(
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        bbox_transform=anchor,
        ncols=2 if wide else max(len(handles), 1),
        frameon=True,
        fancybox=False,
        shadow=False,
        borderpad=0.4,
        labelspacing=0.3,
        handletextpad=0.5,
        handlelength=1.6,
        columnspacing=1.2,
        borderaxespad=0.0,
        markerscale=1.0,
        prop={"family": theme.family, "size": theme.small},
    )
    leg.get_frame().set(
        edgecolor=theme.ink, facecolor=theme.face, linewidth=theme.line_width, alpha=1.0
    )
    _pin(leg.get_texts() + [leg.get_title()], theme, color=theme.ink, size=theme.small)
    return leg


def save(
    fig: Figure, path: str | Path, theme: Theme, *, formats: tuple[str, ...] = ("png",)
) -> list[Path]:
    """Write the figure once per format next to ``path`` and return the written paths.

    Every format is checked before the first file is written. PNG is written at the theme
    dpi. SVG and PDF are vector files without a date, so a second write of the same figure
    gives the same bytes.
    """
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if unknown:
        raise ValueError(
            f"Unknown figure format {unknown[0]!r}. Known formats: {', '.join(FORMATS)}."
        )
    target = Path(path)
    if target.suffix.lstrip(".").lower() in FORMATS:
        target = target.with_suffix("")
    target.parent.mkdir(parents=True, exist_ok=True)
    for ax in fig.axes:
        _pin_ticks(ax, theme)
    written = []
    for fmt in formats:
        out = target.with_name(f"{target.name}.{fmt}")
        kwargs: dict[str, Any] = {"facecolor": theme.face}
        if fmt == "png":
            kwargs["dpi"] = theme.dpi
        elif fmt == "svg":
            kwargs["metadata"] = {"Date": None}
        else:
            kwargs["metadata"] = {"CreationDate": None, "Creator": None, "Producer": None}
        fig.savefig(out, format=fmt, **kwargs)
        written.append(out)
    return written
