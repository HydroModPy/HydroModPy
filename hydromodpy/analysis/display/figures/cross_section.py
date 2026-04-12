"""Vertical cross-section figure."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.display_config import DisplayOptions


def render_cross_section(
    ax: "Axes",
    *,
    dem_section: np.ndarray,
    wt_section: np.ndarray,
    x_coords: np.ndarray,
    base_level: float | None = None,
    aquifer_thickness: float = 30.0,
    title: str = "",
) -> None:
    """Draw a terrain / water-table cross section on *ax*.

    Reproduces the legacy HydroModPy cross-section style:
    - blue fill from bottom to watertable (saturated)
    - brown fill from watertable to DEM (unsaturated)
    - blue line for water table, saddlebrown line for topography
    """
    # Clip watertable to DEM (can't be above surface).
    wt = np.where(np.isfinite(wt_section), np.minimum(wt_section, dem_section), np.nan)

    valid = np.concatenate([dem_section, wt])
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return

    y_min = float(np.nanmin(wt)) - 5.0 if base_level is None else base_level
    y_max = float(np.nanmax(dem_section)) + 3.0

    # Saturated zone — blue fill from bottom to watertable
    ax.fill_between(x_coords, y_min, wt,
                    color="dodgerblue", alpha=0.3, lw=0)
    ax.plot(x_coords, wt, color="blue", lw=3, label="Water table")

    # Unsaturated zone — brown fill from watertable to DEM
    ax.fill_between(x_coords, wt, dem_section,
                    color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(x_coords, dem_section, color="saddlebrown", lw=3, label="Topography")

    ax.set_xlim(float(np.nanmin(x_coords)), float(np.nanmax(x_coords)))
    ax.set_ylim(y_min, y_max)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m.a.s.l]")
    ax.legend(fontsize=12, loc="upper right", framealpha=0.8)
    if title:
        ax.set_title(title, fontsize=10)


def plot_cross_section(
    *,
    dem_section: np.ndarray,
    wt_section: np.ndarray,
    x_coords: np.ndarray,
    base_level: float | None = None,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (7, 5),
    dpi: int = 300,
):
    """Create a cross-section figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

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
