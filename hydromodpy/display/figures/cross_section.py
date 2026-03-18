"""Vertical cross-section figure."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.display.options import DisplayOptions


def render_cross_section(
    ax: Axes,
    *,
    dem_section: np.ndarray,
    wt_section: np.ndarray,
    x_coords: np.ndarray,
    base_level: float | None = None,
) -> None:
    """Draw a terrain / water-table cross section on *ax*.

    All inputs are 1-D arrays of equal length.  The caller is responsible for
    extracting them from raster files.
    """
    valid = np.concatenate([dem_section, wt_section])
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        auto_base, auto_top = 0.0, 1.0
    else:
        auto_base = float(np.nanmin(valid) - 5.0)
        auto_top = float(np.nanmax(valid) + 5.0)

    if base_level is None:
        base_level = auto_base
    top_level = auto_top

    ax.fill_between(x_coords, base_level, wt_section, color="dodgerblue", alpha=0.5, lw=0)
    ax.plot(x_coords, wt_section, color="navy", lw=1.5)
    ax.plot(x_coords, dem_section, color="saddlebrown", lw=1.5)
    ax.fill_between(x_coords, wt_section, dem_section, color="saddlebrown", alpha=0.5, lw=0)
    ax.fill_between(x_coords, base_level, dem_section, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x_coords, np.full_like(x_coords, base_level), color="dimgray", lw=1.0)
    ax.set_xlim(float(x_coords[0]), float(x_coords[-1]) if len(x_coords) else 0.0)
    ax.set_ylim(base_level, top_level)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")


def plot_cross_section(
    *,
    dem_section: np.ndarray,
    wt_section: np.ndarray,
    x_coords: np.ndarray,
    base_level: float | None = None,
    options: DisplayOptions | None = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (6, 4),
    dpi: int = 300,
):
    """Create a cross-section figure, render, and optionally save."""
    from hydromodpy.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_cross_section(
        ax,
        dem_section=dem_section,
        wt_section=wt_section,
        x_coords=x_coords,
        base_level=base_level,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax
