"""Shared helpers for HydroModPy spatial figures.

These helpers consolidate the small matplotlib idioms every map figure
needs: no scientific-notation offset on metric coordinates (which
collides with the title), comma-separated tick labels, sane tick density,
and an optional watershed outline drawn on top of the field.

The helpers stay backend-agnostic - they only touch a matplotlib Axes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


def style_map_axes(
    ax: Axes,
    *,
    xlabel: str = "x (m)",
    ylabel: str = "y (m)",
    max_ticks: int = 4,
) -> None:
    """Apply the standard HydroModPy map styling to ``ax``.

    - Disables the ``+6.8e6`` offset that otherwise collides with the title.
    - Forces plain (no scientific) formatting with thousands-separator commas.
    - Caps the number of ticks on each axis so labels don't overlap.
    - Enables equal aspect so the catchment shape is not distorted.
    - ``steps=[1, 2, 5, 10]`` keeps tick positions on round values - avoids
      ugly labels like ``387,342``.
    """
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_aspect("equal", adjustable="datalim")

    # ``useOffset=False`` + ``style='plain'`` kills the "+6.8e6" prefix.
    ax.ticklabel_format(useOffset=False, style="plain", axis="both")
    locator_kw = {"nbins": max_ticks, "integer": False, "prune": "both", "steps": [1, 2, 5, 10]}
    ax.xaxis.set_major_locator(MaxNLocator(**locator_kw))
    ax.yaxis.set_major_locator(MaxNLocator(**locator_kw))
    # Comma thousands separator - "388,000" is readable where "388000" is not.
    fmt = FuncFormatter(lambda v, _pos: f"{int(v):,}" if abs(v) >= 1 else f"{v:g}")
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)
    ax.tick_params(axis="both", which="major", labelsize=9)


def overlay_watershed_contour(
    ax: Axes,
    sim: Run,
    *,
    color: str = "black",
    linewidth: float = 1.0,
    alpha: float = 0.8,
    target_crs: str | None = None,
) -> None:
    """Draw the catchment polygon outline on top of a map, if available.

    Silently no-ops when the ``watershed`` feature is missing - this keeps
    the helper safe on synthetic cases that have no delineation.
    """
    try:
        gdf = sim.geographic("watershed")
    except Exception:
        return
    if gdf is None or gdf.empty:
        return
    try:
        if target_crs not in (None, "") and gdf.crs is not None and str(gdf.crs) != str(target_crs):
            gdf = gdf.to_crs(target_crs)
        gdf.boundary.plot(ax=ax, color=color, linewidth=linewidth, alpha=alpha, zorder=5)
    except Exception:
        # Rare case: geometry column is missing or CRS mismatch - don't abort.
        return


def style_date_axis(ax: Axes, *, rotation: int = 0) -> None:
    """Apply ConciseDateFormatter to avoid the "2000-012000-05…" overlap."""
    import matplotlib.dates as mdates

    locator = mdates.AutoDateLocator(minticks=3, maxticks=8)
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    if rotation:
        for label in ax.get_xticklabels():
            label.set_rotation(rotation)
            label.set_ha("right")


__all__ = ["overlay_watershed_contour", "style_date_axis", "style_map_axes"]
