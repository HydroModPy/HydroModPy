"""Mixin for spatial figures drawn on a CRS-aware axes.

A figure that inherits from :class:`GeoFigureMixin` gains three helpers
that are useful for maps: :meth:`add_scale_bar` draws a simple metric
scale bar, :meth:`add_north_arrow` adds a small N arrow, and
:meth:`add_basemap` delegates to ``basemaps.add_basemap`` when the
optional contextily dependency is available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.axes import Axes


class GeoFigureMixin:
    """Helpers for figures drawn on projected (x,y) axes.

    The mixin assumes axes are in a projected CRS whose units are metres
    (this is the HydroModPy convention — all meshes live in a metric CRS).
    """

    crs: str | None = None

    def add_scale_bar(
        self,
        ax: "Axes",
        *,
        length_m: float | None = None,
        location: tuple[float, float] = (0.05, 0.05),
        color: str = "black",
    ) -> None:
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
        label = (
            f"{length_m / 1000:g} km" if length_m >= 1000 else f"{length_m:g} m"
        )
        ax.text(
            x0 + length_m / 2.0,
            y0 + height * 0.02,
            label,
            ha="center",
            va="bottom",
            color=color,
            fontsize=8,
        )

    def add_north_arrow(
        self,
        ax: "Axes",
        *,
        location: tuple[float, float] = (0.95, 0.95),
        size: float = 0.05,
    ) -> None:
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

    def add_basemap(self, ax: "Axes", *, crs: str | None = None, source: str | None = None) -> None:
        from hydromodpy.display.geo import basemaps

        basemaps.add_basemap(ax, crs=crs or self.crs, source=source)


def _nice_round(value: float) -> float:
    """Round ``value`` to 1-2-5 × 10^n for a tidy scale bar length."""
    import math

    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    frac = value / (10 ** exp)
    if frac < 1.5:
        nice = 1.0
    elif frac < 3.5:
        nice = 2.0
    elif frac < 7.5:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10 ** exp)


__all__ = ["GeoFigureMixin"]
