"""Particle-tracking plotting helpers.

This module focuses on particle outputs that are part of the new display API.
It currently exposes a static pathline map intended for both on-screen review
and saved reports.
"""
from __future__ import annotations

from pathlib import Path

from hydromodpy.display.common import finalize_figure
from hydromodpy.display.options import DisplayOptions


def plot_pathlines(
    *,
    pathlines_shp: Path,
    endpoints_shp: Path,
    watershed_shp: Path,
    dem_raster: Path,
    options: DisplayOptions,
    save_path: Path | None = None,
) -> None:
    """Plot particle pathlines and endpoints over a watershed background.

    This function reads the exported shapefiles produced by particle tracking
    and builds a map that explains where water particles travel and how long
    they take:
- pathlines show the trajectories;
- endpoints highlight the particle start/end locations;
- the ``time_win_y`` attribute is used as a residence-time color scale.

    The DEM raster is drawn as a grayscale background so the trajectories remain
    readable in their topographic context.
    """

    # Keep heavy GIS imports local so the module stays importable without them.
    import geopandas as gpd
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import numpy as np
    import rasterio
    import rasterio.plot
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    shp_pathlines = gpd.read_file(pathlines_shp)
    shp_endpoints = gpd.read_file(endpoints_shp)
    watershed = gpd.read_file(watershed_shp)

    with rasterio.open(dem_raster) as dem_rio:
        nodata = dem_rio.nodata
        dem_array = dem_rio.read(1)
        if nodata is None:
            dem_data = np.ma.masked_where(dem_array < 0, dem_array)
        else:
            dem_data = np.ma.masked_where(np.isclose(dem_array, float(nodata)), dem_array)

        norm = mcolors.LogNorm(vmin=0.1, vmax=100)
        scalar_mappable = cm.ScalarMappable(cmap="jet", norm=norm)
        scalar_mappable.set_array([])

        fig, ax = plt.subplots(1, 1, figsize=(8, 6), dpi=options.dpi)
        rasterio.plot.show(
            dem_data,
            ax=ax,
            transform=dem_rio.transform,
            cmap="Greys",
            alpha=0.7,
            zorder=-10,
        )

    shp_pathlines.plot(ax=ax, column="time_win_y", cmap="jet", lw=1, norm=norm, zorder=1)
    shp_endpoints.plot(
        ax=ax,
        column="time_win_y",
        cmap="jet",
        lw=0.5,
        markersize=20,
        legend=False,
        norm=norm,
        zorder=2,
        edgecolor="k",
    )
    watershed.plot(ax=ax, facecolor="None", edgecolor="k", lw=2, zorder=-1)
    ax.set_title("Residence times - backward from seepage [y]", fontsize=10)

    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    fig.colorbar(scalar_mappable, cax=cax, orientation="vertical")
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=save_path)
