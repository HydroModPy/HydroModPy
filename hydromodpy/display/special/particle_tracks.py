"""Pathlines of the particle table in plan, coloured along their way by the age of the water.

Each particle is one line through its recorded positions. Each piece of a line takes the
colour of the time since the release when the water reaches it, so a line runs from light
at its release to dark where it leaves the aquifer, and the colour gives the way of the
flow. The scale is linear and stops at the 99th percentile of the travel times, since a
few very slow particles would otherwise set the whole range. The lines released in the
catchment are coloured. The others are thin and grey, so the catchment reads first. Beyond
``MAX_LINES`` lines of a kind, one in n is drawn, evenly through the release order. The
seepage cells and the pumping cells of the instant are drawn under the lines, since they
are where the paths end. A particle that never moved, or that has no time, has no line.

With ``variable`` the figure draws that field as a map under the lines, with its own
colour bar, for example ``travel_time_to_exit`` or ``watertable_depth``. The lines are
then thin and dark, those of the ``pathlines`` overlay, so one colour scale is read.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
from scipy.spatial import cKDTree

from hydromodpy.display import overlays, static
from hydromodpy.display.frames import map as map_frame
from hydromodpy.display.subject import FigureNotApplicable, read_mesh, read_pathlines
from hydromodpy.display.theme import Theme, colormap, unit_text

CLIP_PERCENT = 99.0
"""The colour scale stops at this percentile of the travel times."""
RAMP = "water_age"
"""Orange for young water, dark blue for old water."""
MAX_LINES = 350
"""Lines drawn at most in the catchment, and at most outside it."""
RASTER_FROM = 20000
"""Beyond this many pieces of line the collection is rasterised."""


def _pieces(paths: list[np.ndarray], shown: np.ndarray) -> np.ndarray:
    """Return every piece of the shown paths, as ``(n, 2, 2)`` start and end points."""
    return np.concatenate([np.stack([paths[i][:-1], paths[i][1:]], axis=1) for i in shown])


def _over_a_field(subject: Any, ax: Any, theme: Theme, name: str, time: str | int | None) -> None:
    """Draw the map of ``name``, then the cells where the paths end and the thin dark lines."""
    paths, _ = read_pathlines(subject)
    instant = "last" if time is None else time
    field = map_frame.of_variable(subject, name, time)
    map_frame.draw(ax, field, theme)
    overlays.seepage(ax, subject, theme, instant)
    overlays.wells(ax, subject, theme, instant)
    overlays.pathlines(ax, subject, theme)
    overlays.network(ax, subject, theme)
    overlays.outline(ax, subject, theme)
    overlays.outlet(ax, subject, theme)
    static.scale_bar(ax, theme)
    count = [ax.get_title(loc="right"), f"{len(paths)} pathlines"]
    if len(paths) > overlays.MAX_PATHLINES:
        count.append(f"one in {-(-len(paths) // overlays.MAX_PATHLINES)} drawn")
    static.titles(ax, theme, ax.get_title(loc="left"), ", ".join(filter(None, count)))
    if ax.get_legend_handles_labels()[0]:
        corner = static.quiet_corner(ax, field.table["x"], field.table["y"])
        static.legend(ax, theme, inside=corner)


def draw(
    subject: Any,
    ax: Any,
    theme: Theme,
    time: str | int | None = None,
    variable: str | list[str] | None = None,
) -> None:
    """Draw the lines on map axes, coloured by the age of the water or over ``variable``."""
    names = [variable] if isinstance(variable, str) else list(variable or ())
    if len(names) > 1:
        raise FigureNotApplicable(
            f"The pathlines are drawn over one variable, not over {', '.join(names)}."
        )
    if names:
        _over_a_field(subject, ax, theme, names[0], time)
        return
    paths, ages = read_pathlines(subject)
    instant = "last" if time is None else time
    mesh = read_mesh(subject)
    starts = np.array([path[0] for path in paths])
    inside = mesh.zones["catchment"][cKDTree(mesh.centres).query(starts)[1]]
    if not inside.any():
        inside[:] = True  # No particle starts in the catchment, so every line is coloured.
    step = max(-(-int(count) // MAX_LINES) for count in (inside.sum(), (~inside).sum()))
    shown, context = np.flatnonzero(inside)[::step], np.flatnonzero(~inside)[::step]
    age = np.concatenate([ages[i][1:] for i in shown])
    travel = np.array([ages[i][-1] for i in shown])
    high = float(np.percentile(travel, CLIP_PERCENT))
    order = np.argsort(-age)  # Old water first, so the young pieces stay visible over it.
    lines = LineCollection(
        _pieces(paths, shown)[order], array=age[order], cmap=colormap(RAMP),
        norm=Normalize(0.0, high if high > 0 else 1.0), linewidths=theme.line_width * 1.3,
        capstyle="round", rasterized=len(age) > RASTER_FROM, zorder=overlays.Z_LINE - 1,
    )  # fmt: skip
    overlays.seepage(ax, subject, theme, instant)
    overlays.wells(ax, subject, theme, instant)
    if len(context):
        ax.add_collection(
            LineCollection(
                [paths[i] for i in context], colors=theme.roles["trial"],
                linewidths=theme.line_width * 0.7, alpha=0.6, capstyle="round", label="Outside the catchment",
                rasterized=len(context) > RASTER_FROM, zorder=overlays.Z_LINE - 2,
            )
        )  # fmt: skip
    ax.add_collection(lines)
    overlays.network(ax, subject, theme)
    overlays.outline(ax, subject, theme)
    overlays.outlet(ax, subject, theme)
    corners = mesh.vertices[:, :2]
    static.map_axes(ax, theme, extent=(*corners.min(axis=0), *corners.max(axis=0)))
    static.scale_bar(ax, theme)
    extend = "max" if travel.max() > high else "neither"
    static.colorbar(ax.figure, lines, ax, theme, label="", extend=extend)
    count = [f"{len(paths)} pathlines"]
    if len(context) or not inside.all():
        count.append(f"{int(inside.sum())} from the catchment in colour")
    if step > 1:
        count.append(f"one in {step} drawn")
    static.titles(
        ax, theme, f"Age of the water along the pathlines ({unit_text('yr')})", ", ".join(count)
    )
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme, inside=static.quiet_corner(ax, *mesh.centres.T))
