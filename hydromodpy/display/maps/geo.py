"""Scale bar and north arrow for a map drawn on projected axes.

The axes are in a projected CRS whose units are meters, the HydroModPy
convention for every mesh. A GeoDataFrame is put in such a CRS by
:func:`hydromodpy.core.io.crs.project_gdf_for_metric_operations`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.axes import Axes

__all__ = ["north_arrow", "scale_bar"]


def scale_bar(
    ax: Axes,
    *,
    length_m: float | None = None,
    location: tuple[float, float] = (0.05, 0.05),
    color: str = "black",
) -> None:
    """Draw a metric scale bar, one fifth of the map width rounded to 1-2-5."""
    import matplotlib.patches as mpatches

    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    width = xmax - xmin
    height = ymax - ymin
    if length_m is None:
        length_m = _nice_round(width / 5.0)
    x0 = xmin + location[0] * width
    y0 = ymin + location[1] * height
    bar = mpatches.Rectangle(
        (x0, y0),
        length_m,
        height * 0.01,
        facecolor=color,
        edgecolor=color,
    )
    ax.add_patch(bar)
    label = f"{length_m / 1000:g} km" if length_m >= 1000 else f"{length_m:g} m"
    ax.text(
        x0 + length_m / 2.0,
        y0 + height * 0.02,
        label,
        ha="center",
        va="bottom",
        color=color,
        fontsize=8,
    )


def north_arrow(
    ax: Axes,
    *,
    location: tuple[float, float] = (0.95, 0.95),
    size: float = 0.05,
) -> None:
    """Draw a small N arrow in the axes fraction frame."""
    ax.annotate(
        "N",
        xy=location,
        xycoords="axes fraction",
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        xytext=(location[0], location[1] - size),
        textcoords="axes fraction",
        arrowprops={"facecolor": "black", "width": 2, "headwidth": 8},
    )


def _nice_round(value: float) -> float:
    """Round ``value`` to 1-2-5 × 10^n for a tidy scale bar length."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    frac = value / (10**exp)
    if frac < 1.5:
        nice = 1.0
    elif frac < 3.5:
        nice = 2.0
    elif frac < 7.5:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10**exp)
