"""2-D spatial field figures (raster overlays, concentration maps)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.options import DisplayOptions


# ======================================================================
# Generic raster field
# ======================================================================

def render_raster_field(
    ax: Axes,
    *,
    raster_masked: np.ma.MaskedArray,
    transform,
    watershed_gdf=None,
    streams_gdf=None,
    cmap: str = "terrain",
    alpha: float = 0.7,
    colorbar_label: str = "",
) -> None:
    """Display a masked raster over an Axes with optional vector overlays.

    *transform* is a rasterio-compatible affine transform.
    """
    import rasterio.plot
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    rasterio.plot.show(
        raster_masked, ax=ax, transform=transform,
        cmap=cmap, alpha=alpha, zorder=1,
    )

    if watershed_gdf is not None:
        watershed_gdf.plot(ax=ax, facecolor="None", edgecolor="k", lw=2, zorder=2)
    if streams_gdf is not None:
        streams_gdf.plot(ax=ax, color="navy", lw=1, zorder=0)

    if colorbar_label:
        import matplotlib.cm as cm
        import matplotlib.colors as mcolors

        vmin = float(np.nanmin(raster_masked))
        vmax = float(np.nanmax(raster_masked))
        sm = cm.ScalarMappable(cmap=cmap, norm=mcolors.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.1)
        ax.figure.colorbar(sm, cax=cax, orientation="vertical", label=colorbar_label)


def plot_raster_field(
    *,
    raster_masked: np.ma.MaskedArray,
    transform,
    watershed_gdf=None,
    streams_gdf=None,
    cmap: str = "terrain",
    alpha: float = 0.7,
    colorbar_label: str = "",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 6),
    dpi: int = 300,
):
    """Create a raster-field figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_raster_field(
        ax,
        raster_masked=raster_masked,
        transform=transform,
        watershed_gdf=watershed_gdf,
        streams_gdf=streams_gdf,
        cmap=cmap,
        alpha=alpha,
        colorbar_label=colorbar_label,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Concentration map (transport)
# ======================================================================

def render_concentration_map(
    ax: Axes,
    *,
    dem_masked: np.ma.MaskedArray,
    dem_transform,
    concentration_masked: np.ma.MaskedArray,
    watershed_gdf=None,
    streams_gdf=None,
    norm=None,
    cmap: str = "turbo",
    colorbar_label: str = "[NO3] mg/L",
) -> None:
    """Seepage concentration over a DEM background.

    *concentration_masked* and *dem_masked* must share the same spatial
    extent and *dem_transform*.  *norm* is typically a ``LogNorm``.
    """
    import matplotlib.cm as cm
    import rasterio.plot
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    rasterio.plot.show(
        dem_masked, ax=ax, transform=dem_transform,
        cmap="Greys_r", alpha=0.4, zorder=-10,
    )

    rasterio.plot.show(
        concentration_masked, ax=ax, transform=dem_transform,
        cmap=cmap, alpha=1, zorder=1,
    )

    if watershed_gdf is not None:
        watershed_gdf.plot(ax=ax, facecolor="None", edgecolor="k", lw=3, zorder=2)
    if streams_gdf is not None:
        streams_gdf.plot(ax=ax, color="navy", lw=1, zorder=0)

    if norm is not None:
        scalar_mappable = cm.ScalarMappable(cmap=cmap, norm=norm)
        scalar_mappable.set_array([])
        divider = make_axes_locatable(ax)
        cax = divider.new_vertical(size="5%", pad=0.6, pack_start=True)
        ax.figure.add_axes(cax)
        ax.figure.colorbar(
            scalar_mappable, cax=cax, orientation="horizontal",
            label=colorbar_label,
        )


def plot_concentration_map(
    *,
    dem_masked: np.ma.MaskedArray,
    dem_transform,
    concentration_masked: np.ma.MaskedArray,
    watershed_gdf=None,
    streams_gdf=None,
    norm=None,
    cmap: str = "turbo",
    colorbar_label: str = "[NO3] mg/L",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 8),
    dpi: int = 300,
):
    """Create a concentration map figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_concentration_map(
        ax,
        dem_masked=dem_masked,
        dem_transform=dem_transform,
        concentration_masked=concentration_masked,
        watershed_gdf=watershed_gdf,
        streams_gdf=streams_gdf,
        norm=norm,
        cmap=cmap,
        colorbar_label=colorbar_label,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax
