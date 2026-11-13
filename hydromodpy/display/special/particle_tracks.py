"""Pathlines of the particle table in plan, coloured by travel time, in kilometres.

Each particle is one line through its recorded positions, coloured by the time it took
from release to its last record. The colour scale is linear and stops at the 99th
percentile of the times, since a few very slow particles would otherwise set the whole
range. A particle that never moved, or that has no time, has no line. Lines are drawn from
the slowest to the fastest, so the short and fast paths stay visible over the long ones.
The catchment outline and the outlet are drawn over the lines, so the tracks read in
their catchment. The count of lines is the right title.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
from pyproj import CRS
from pyproj.exceptions import CRSError

from hydromodpy.display import overlays, static
from hydromodpy.display.special.records import moving_particles
from hydromodpy.display.subject import FigureNotApplicable, read_mesh
from hydromodpy.display.theme import Theme, unit_text

CLIP_PERCENT = 99.0
"""The colour scale stops at this percentile of the travel times, a longer path takes the top colour."""
RASTER_FROM = 2000
"""Beyond this many lines the collection is rasterised."""


def _crs_name(run: Any) -> str:
    """Return the short name of the mesh CRS for the axis labels."""
    try:
        return CRS.from_user_input(read_mesh(run).crs).name.rsplit(" / ", 1)[-1]
    except (FigureNotApplicable, CRSError):
        return "mesh CRS"


def draw(subject: Any, ax: Any, theme: Theme) -> None:
    """Draw the lines on map axes with a colorbar of the travel time in years."""
    segments, years = moving_particles(subject)
    order = np.argsort(-years)
    high = float(np.percentile(years, CLIP_PERCENT))
    extend = "max" if years.max() > high else "neither"
    lines = LineCollection(
        [segments[i] for i in order], array=years[order], norm=Normalize(0.0, high),
        cmap=theme.ramps["sequential"], linewidths=theme.line_width,
        rasterized=len(segments) > RASTER_FROM,
    )  # fmt: skip
    ax.add_collection(lines)
    overlays.outline(ax, subject, theme)
    overlays.outlet(ax, subject, theme)
    ax.autoscale_view()
    static.map_axes(ax, theme, crs=_crs_name(subject))
    static.scale_bar(ax, theme)
    static.colorbar(
        ax.figure, lines, ax, theme, label=f"Travel time ({unit_text('yr')})", extend=extend
    )
    ax.set_title(f"{len(segments)} pathlines", loc="right", **static.text_style(theme))
