"""2-D spatial field figures (raster overlays, concentration maps)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.display_config import DisplayOptions


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
# Composite seepage + pathlines + water-table depth
# ======================================================================

def render_seepage_pathlines_wtd(
    ax: "Axes",
    *,
    wtd_masked: np.ma.MaskedArray,
    transform,
    seepage_masked: np.ma.MaskedArray | None = None,
    watershed_gdf=None,
    pathlines_gdf=None,
    cross_section_col: int | None = None,
    wtd_vmin: float = 0.0,
    wtd_vmax: float = 10.0,
    title: str = "",
) -> None:
    """Composite map: water-table depth + seepage overlay + pathlines.

    Reproduces the legacy figure with WTD in jet colormap, seepage cells
    in black, pathlines in black, and watershed contour.
    """
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    from rasterio.plot import plotting_extent
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    extent = plotting_extent(wtd_masked, transform)

    # Water-table depth background — use ax.imshow for reliable vmin/vmax
    norm = mcolors.Normalize(vmin=wtd_vmin, vmax=wtd_vmax)
    ax.imshow(
        wtd_masked, extent=extent, cmap="jet", norm=norm,
        alpha=0.5, zorder=1, origin="upper", aspect="equal",
    )

    # Seepage overlay in black
    if seepage_masked is not None:
        seepage_binary = np.ma.masked_where(seepage_masked <= 0, seepage_masked)
        if seepage_binary.count() > 0:
            from matplotlib.colors import ListedColormap
            ax.imshow(
                seepage_binary, extent=extent,
                cmap=ListedColormap(["black"]), alpha=1.0,
                zorder=2, origin="upper", aspect="equal",
            )

    # Pathlines overlay
    if pathlines_gdf is not None and len(pathlines_gdf) > 0:
        pathlines_gdf.plot(ax=ax, color="black", lw=0.5, zorder=3)

    # Watershed contour
    if watershed_gdf is not None:
        watershed_gdf.plot(ax=ax, facecolor="None", edgecolor="k", lw=2.5, zorder=4)

    # Cross-section location line (vertical, at column position)
    if cross_section_col is not None:
        x_pos = transform.c + cross_section_col * transform.a
        ax.axvline(x=x_pos, color="k", ls="--", lw=2, zorder=5)

    # Colorbar
    sm = cm.ScalarMappable(cmap="jet", norm=norm)
    sm.set_array([])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    ax.figure.colorbar(sm, cax=cax, orientation="vertical", label="Water-table depth [m]")

    if title:
        ax.set_title(title, fontsize=10)


def plot_seepage_pathlines_wtd(
    *,
    wtd_masked: np.ma.MaskedArray,
    transform,
    seepage_masked: np.ma.MaskedArray | None = None,
    watershed_gdf=None,
    pathlines_gdf=None,
    cross_section_col: int | None = None,
    wtd_vmin: float = 0.0,
    wtd_vmax: float = 10.0,
    title: str = "",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 6),
    dpi: int = 300,
):
    """Create composite seepage+pathlines+WTD figure, render, optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_seepage_pathlines_wtd(
        ax,
        wtd_masked=wtd_masked,
        transform=transform,
        seepage_masked=seepage_masked,
        watershed_gdf=watershed_gdf,
        pathlines_gdf=pathlines_gdf,
        cross_section_col=cross_section_col,
        wtd_vmin=wtd_vmin,
        wtd_vmax=wtd_vmax,
        title=title,
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
