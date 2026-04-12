"""Generic geospatial map figures.

Every ``render_*`` function draws on an existing Axes.
Every ``plot_*`` wrapper creates a figure, renders, and optionally saves.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes


def _resolve_gdf(source):
    """Convert a file path or GeoDataFrame into a GeoDataFrame."""
    import geopandas as gpd

    if source is None:
        return None
    if isinstance(source, gpd.GeoDataFrame):
        return source
    return gpd.read_file(str(source))

    from hydromodpy.analysis.display.display_config import DisplayOptions


# ======================================================================
# Helpers
# ======================================================================

def _open_dem(dem_path):
    """Open a DEM raster and return (masked_array, bounds, transform, handle).

    The caller is responsible for closing *handle* when done.
    """
    import rasterio

    dem = rasterio.open(str(dem_path))
    dem_array = dem.read(1)
    nodata = dem.nodata
    if nodata is not None:
        mask = np.isclose(dem_array.astype(float), float(nodata))
    else:
        mask = dem_array < 0
    dem_masked = np.ma.masked_where(mask, dem_array)
    return dem_masked, dem.bounds, dem.transform, dem


def _setup_map_axes(ax, bounds):
    """Apply common axis settings for map panels."""
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    ax.set_aspect("equal")
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)


def _stream_order_colors(n: int) -> list:
    """Return *n* blue-scale colours for Strahler orders."""
    import matplotlib.pyplot as plt

    cmap = plt.cm.Blues
    return [cmap(0.3 + 0.7 * i / max(n - 1, 1)) for i in range(n)]


# ======================================================================
# DEM map
# ======================================================================

def render_dem_map(
    ax: Axes,
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    title: str = "",
    basemap: bool = False,
) -> None:
    """DEM terrain with watershed contour and station overlays.

    Parameters
    ----------
    streams_gdf : GeoDataFrame or None
        Pre-loaded stream network.
    station_points : list[dict] or None
        Each dict has keys ``x``, ``y`` and optional ``label``, ``marker``
        (default ``"o"``), ``color`` (default ``"white"``), ``group``
        (used as legend label for the batch).
    """
    import geopandas as gpd
    from rasterio.plot import show

    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import matplotlib.lines as mlines
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    dem_masked, bounds, transform, dem_handle = _open_dem(dem_path)
    _setup_map_axes(ax, bounds)

    show(dem_masked, ax=ax, transform=transform, cmap="terrain",
         alpha=0.75, zorder=2, aspect="auto")

    legend_handles = []

    # Streams
    if streams_gdf is not None:
        streams_gdf.plot(ax=ax, lw=1.5, color="navy", zorder=3)
        legend_handles.append(
            mlines.Line2D([], [], color="navy", lw=1.5, label="Streams"))

    # Watershed contour
    contour = None
    try:
        contour = _resolve_gdf(watershed_shp)
        contour.plot(ax=ax, lw=1.5, zorder=4, edgecolor="k", facecolor="None")
        legend_handles.append(
            mlines.Line2D([], [], color="k", lw=1.5, label="Watershed"))
    except Exception:
        pass

    # OSM basemap
    if basemap:
        try:
            import contextily as cx
            crs = contour.crs if contour is not None else None
            if crs is not None:
                cx.add_basemap(ax, crs=crs, zorder=0, alpha=0.4)
        except Exception:
            pass

    # Station overlays from generic dicts
    if station_points:
        from collections import defaultdict

        by_group: dict[tuple, list[dict]] = defaultdict(list)
        for pt in station_points:
            key = (pt.get("marker", "o"), pt.get("color", "white"), pt.get("group", ""))
            by_group[key].append(pt)

        for (marker, color, group), pts in by_group.items():
            xs = [p["x"] for p in pts]
            ys = [p["y"] for p in pts]
            label = group or None
            h = ax.scatter(
                xs, ys, color=color, marker=marker, zorder=6,
                edgecolor="k", lw=1, label=label,
            )
            if label:
                legend_handles.append(h)

    if legend_handles:
        ax.legend(handles=legend_handles, loc="lower right", title=title,
                  framealpha=0.8, fontsize=7)

    # Colorbar — built from a standalone ScalarMappable to avoid
    # the imshow/set_clim callback conflict with ultraplot axes.
    valid = dem_masked.compressed()
    if valid.size > 0:
        vmin_f, vmax_f = float(valid.min()), float(valid.max())
        sm = cm.ScalarMappable(
            cmap="terrain",
            norm=mcolors.Normalize(vmin=vmin_f, vmax=vmax_f),
        )
        sm.set_array([])
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.05)
        cbar = ax.figure.colorbar(sm, cax=cax, orientation="vertical")
        vmin_i, vmax_i = int(round(vmin_f)), int(round(vmax_f))
        vmid = int(round(vmin_f + (vmax_f - vmin_f) / 2))
        cbar.set_ticks([vmin_i, vmid, vmax_i])
        cbar.set_ticklabels([str(vmin_i), str(vmid), str(vmax_i)])
        cbar.ax.tick_params(labelsize=8)

    dem_handle.close()


def plot_dem_map(
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    title: str = "",
    basemap: bool = False,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (6, 6),
    dpi: int = 300,
):
    """Create a DEM map figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_dem_map(
        ax,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        streams_gdf=streams_gdf,
        station_points=station_points,
        title=title,
        basemap=basemap,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Geology map
# ======================================================================

def render_geology_map(
    ax: Axes,
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    geology_rgba: np.ndarray | None = None,
    geology_bounds: tuple[float, float, float, float] | None = None,
    geology_gdf=None,
    legend_entries: list[dict] | None = None,
    streams_gdf=None,
    title: str = "",
) -> None:
    """Geology overlay on DEM.

    Raster mode : provide *geology_rgba* (H, W, 4) + *geology_bounds*.
    Vector mode : provide *geology_gdf* (GeoDataFrame) with a colour column.
    *legend_entries*: list of ``{"label": str, "color": str, "alpha": float}``.
    """
    import geopandas as gpd
    import matplotlib.patches as mpatches
    from rasterio.plot import show

    dem_masked, bounds, transform, dem_handle = _open_dem(dem_path)
    _setup_map_axes(ax, bounds)

    # Background DEM
    show(dem_masked, ax=ax, transform=transform, cmap="terrain",
         alpha=0.3, zorder=1, aspect="auto")

    handles = []

    # Raster overlay
    if geology_rgba is not None and geology_bounds is not None:
        ax.imshow(
            geology_rgba,
            extent=[geology_bounds[0], geology_bounds[2],
                    geology_bounds[1], geology_bounds[3]],
            origin="upper",
            interpolation="nearest",
            zorder=2,
        )
        if legend_entries:
            for entry in legend_entries:
                handles.append(mpatches.Patch(
                    facecolor=entry["color"],
                    alpha=entry.get("alpha", 0.55),
                    label=entry["label"],
                    edgecolor="k",
                ))

    # Vector overlay (alternative)
    elif geology_gdf is not None:
        for name, group in geology_gdf.groupby("NATURE"):
            color = group["hex"].iloc[0] if "hex" in group.columns else "#cccccc"
            group.plot(color=color, ax=ax, alpha=0.5, edgecolor="dimgrey", zorder=2)
        for name, group in geology_gdf.groupby("NATURE"):
            color = group["hex"].iloc[0] if "hex" in group.columns else "#cccccc"
            if "Partie marine" not in str(name):
                label = str(name).split(":")[0].upper()
                handles.append(mpatches.Patch(
                    facecolor=color, alpha=0.5, label=label, edgecolor="k",
                ))

    if handles:
        ax.legend(handles=handles, loc="upper right", ncol=1,
                  fontsize=5.5, framealpha=0.8)

    # Streams
    if streams_gdf is not None:
        streams_gdf.plot(ax=ax, lw=1.5, color="navy", zorder=3)

    # Watershed contour
    try:
        contour = _resolve_gdf(watershed_shp)
        contour.plot(ax=ax, lw=1.5, zorder=4, edgecolor="k", facecolor="None")
    except Exception:
        pass

    if title:
        ax.set_title(title, fontsize=9)

    dem_handle.close()


def plot_geology_map(
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    geology_rgba: np.ndarray | None = None,
    geology_bounds: tuple[float, float, float, float] | None = None,
    geology_gdf=None,
    legend_entries: list[dict] | None = None,
    streams_gdf=None,
    title: str = "",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (6, 6),
    dpi: int = 300,
):
    """Create a geology map figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_geology_map(
        ax,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        geology_rgba=geology_rgba,
        geology_bounds=geology_bounds,
        geology_gdf=geology_gdf,
        legend_entries=legend_entries,
        streams_gdf=streams_gdf,
        title=title,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Hydrography map
# ======================================================================

def render_hydrography_map(
    ax: Axes,
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    streams_gdf=None,
    strahler_col: str | None = None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
) -> None:
    """River network with Strahler-order colouring over DEM.

    *streams_gdf* is a pre-loaded GeoDataFrame.  When *strahler_col* is
    given, lines are coloured and scaled by stream order.
    """
    import geopandas as gpd
    from rasterio.plot import show

    dem_masked, bounds, transform, dem_handle = _open_dem(dem_path)
    _setup_map_axes(ax, bounds)

    show(dem_masked, ax=ax, transform=transform, cmap="terrain",
         alpha=0.4, zorder=1, aspect="auto")

    # Watershed contour
    try:
        contour = _resolve_gdf(watershed_shp)
        contour.plot(ax=ax, lw=1.5, zorder=4, edgecolor="k",
                     facecolor="None", label="Watershed")
    except Exception:
        pass

    # Stream network
    if streams_gdf is not None:
        col = strahler_col or ("strahler" if "strahler" in streams_gdf.columns else None)
        if col and col in streams_gdf.columns:
            orders = sorted(streams_gdf[col].unique())
            cmap = _stream_order_colors(len(orders))
            for i, order in enumerate(orders):
                subset = streams_gdf[streams_gdf[col] == order]
                lw = 0.5 + order * 0.5
                subset.plot(ax=ax, lw=lw, color=cmap[i], zorder=3,
                            label=f"Order {order}")
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore", UserWarning)
                ax.legend(loc="lower right", fontsize=6, framealpha=0.8, title=title)
        else:
            streams_gdf.plot(ax=ax, lw=1.5, color="navy", zorder=3, label="Streams")
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore", UserWarning)
                ax.legend(loc="lower right", fontsize=7, framealpha=0.8, title=title)

    # Outlet marker
    if outlet_xy is not None:
        ax.plot(outlet_xy[0], outlet_xy[1], "r*", markersize=12,
                zorder=10, label="Outlet")

    dem_handle.close()


def plot_hydrography_map(
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    streams_gdf=None,
    strahler_col: str | None = None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (6, 6),
    dpi: int = 300,
):
    """Create a hydrography map figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_hydrography_map(
        ax,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        streams_gdf=streams_gdf,
        strahler_col=strahler_col,
        outlet_xy=outlet_xy,
        title=title,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Pathlines map
# ======================================================================

def render_pathlines_map(
    ax: Axes,
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    pathlines_gdf,
    endpoints_gdf,
    color_column: str = "time_win_y",
    norm=None,
    title: str = "Residence times - backward from seepage [y]",
) -> None:
    """Particle pathlines and endpoints over a DEM background.

    *pathlines_gdf* and *endpoints_gdf* are pre-loaded GeoDataFrames.
    *norm* is an optional ``matplotlib.colors.Normalize`` instance.
    """
    import geopandas as gpd
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import rasterio
    import rasterio.plot
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    with rasterio.open(str(dem_path)) as dem_rio:
        nodata = dem_rio.nodata
        dem_array = dem_rio.read(1)
        if nodata is None:
            dem_data = np.ma.masked_where(dem_array < 0, dem_array)
        else:
            dem_data = np.ma.masked_where(
                np.isclose(dem_array, float(nodata)), dem_array,
            )

        if norm is None:
            norm = mcolors.LogNorm(vmin=0.1, vmax=100)
        scalar_mappable = cm.ScalarMappable(cmap="jet", norm=norm)
        scalar_mappable.set_array([])

        rasterio.plot.show(
            dem_data, ax=ax, transform=dem_rio.transform,
            cmap="Greys", alpha=0.7, zorder=-10,
        )

    pathlines_gdf.plot(
        ax=ax, column=color_column, cmap="jet", lw=1, norm=norm, zorder=1,
    )
    endpoints_gdf.plot(
        ax=ax, column=color_column, cmap="jet", lw=0.5, markersize=20,
        legend=False, norm=norm, zorder=2, edgecolor="k",
    )

    try:
        watershed = _resolve_gdf(watershed_shp)
        watershed.plot(ax=ax, facecolor="None", edgecolor="k", lw=2, zorder=-1)
    except Exception:
        pass

    ax.set_title(title, fontsize=10)

    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    ax.figure.colorbar(scalar_mappable, cax=cax, orientation="vertical")


def plot_pathlines_map(
    *,
    dem_path: str | Path,
    watershed_shp: str | Path,
    pathlines_gdf,
    endpoints_gdf,
    color_column: str = "time_win_y",
    norm=None,
    title: str = "Residence times - backward from seepage [y]",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 6),
    dpi: int = 300,
):
    """Create a pathlines map figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_pathlines_map(
        ax,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        pathlines_gdf=pathlines_gdf,
        endpoints_gdf=endpoints_gdf,
        color_column=color_column,
        norm=norm,
        title=title,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax
