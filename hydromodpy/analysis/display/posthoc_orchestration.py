"""Post-hoc orchestration — generate display figures from disk outputs.

Unlike :mod:`hydromodpy.analysis.display.orchestration`, these suites do not
require live runtime objects.  They read everything from the files
produced by a completed simulation, using :class:`PosthocContext`.

Usage::

    from hydromodpy.analysis.display.posthoc import PosthocContext
    from hydromodpy.analysis.display.posthoc_orchestration import plot_posthoc_all
    from hydromodpy.analysis.display.display_config import display_options_from_raw_toml

    ctx = PosthocContext.from_toml("project/config.toml")
    options = display_options_from_raw_toml(raw_toml)
    plot_posthoc_all(ctx, options)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.display.common import (
    ensure_dir,
    finalize_figure,
    make_figure,
    _single_axes,
)
from hydromodpy.analysis.display.display_config import DisplayOptions
from hydromodpy.analysis.display.posthoc import GeographicArtifacts, PosthocContext, RunArtifacts

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers — data loading from disk
# ------------------------------------------------------------------

def _load_npy_dict(path: Path | None) -> dict[int, np.ndarray] | None:
    """Load a dict-of-arrays .npy file, or return None."""
    if path is None or not path.exists():
        return None
    return np.load(path, allow_pickle=True).item()


def _load_field_dict_from_store(
    store: Any,
    sim_id: str,
    variable: str,
) -> dict[int, np.ndarray] | None:
    """Load a multi-timestep spatial field from a ResultStore.

    Returns a dict mapping timestep index → ndarray, matching the
    legacy ``.npy`` dict layout used by the posthoc helpers.
    Returns ``None`` if the variable is not found.
    """
    try:
        sims = store.list_simulations(sim_id=sim_id)
        if sims.empty:
            return None
        n_timesteps = int(sims.iloc[0].get("n_timesteps") or 1)
    except Exception:
        n_timesteps = 1

    result: dict[int, np.ndarray] = {}
    for t in range(n_timesteps):
        try:
            result[t] = store.query_field(sim_id, variable, t)
        except KeyError:
            break
    return result if result else None


def _load_raster(path: Path):
    """Load a raster and return (masked_array, transform, nodata)."""
    import rasterio

    with rasterio.open(path) as src:
        data = src.read(1).astype(float)
        nodata = src.nodata
        transform = src.transform
        if nodata is not None:
            mask = np.isclose(data, float(nodata))
        else:
            mask = data < -9000
        masked = np.ma.masked_where(mask, data)
    return masked, transform, nodata


# ------------------------------------------------------------------
# Individual figure generators
# ------------------------------------------------------------------

def _plot_dem_overview(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
) -> None:
    """DEM overview map with watershed contour."""
    dem_path = run.base_raster(geo)
    if dem_path is None or geo.watershed_shp is None:
        return

    from hydromodpy.analysis.display.figures.maps import plot_dem_map

    plot_dem_map(
        dem_path=dem_path,
        watershed_shp=geo.watershed_shp,
        title=run.run_id,
        options=options,
        save_path=output_dir / "dem_overview.png",
    )


def _plot_watertable_maps(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Water-table depth and elevation raster maps."""
    dem_path = run.base_raster(geo)
    if dem_path is None:
        return

    from hydromodpy.analysis.display.figures.spatial import render_raster_field

    for label, npy_path, raster_list, cmap, cb_label in [
        ("watertable_depth", run.watertable_depth_npy,
         run.watertable_depth_rasters, "Blues", "WT depth [m]"),
        ("watertable_elevation", run.watertable_elevation_npy,
         run.watertable_elevation_rasters, "terrain", "WT elevation [m]"),
        ("seepage_areas", run.seepage_areas_npy,
         run.seepage_areas_rasters, "Reds", "Seepage [m/d]"),
    ]:
        # Prefer raster files; fall back to .npy or ResultStore
        if raster_list:
            raster_path = raster_list[-1]  # last stress period
        elif npy_path is not None:
            # Load from npy dict and overlay on DEM grid
            data_dict = _load_npy_dict(npy_path)
            if data_dict is None:
                continue
            last_key = max(data_dict.keys())
            arr = data_dict[last_key].astype(float)

            dem_masked, transform, nodata = _load_raster(dem_path)
            if nodata is not None:
                arr_masked = np.ma.masked_where(
                    np.isclose(dem_masked.data, float(nodata)), arr,
                )
            else:
                arr_masked = np.ma.masked_where(arr < -9000, arr)

            import geopandas as gpd

            ws_gdf = None
            if geo.watershed_shp is not None:
                ws_gdf = gpd.read_file(str(geo.watershed_shp))

            fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
            ax = _single_axes(axs)
            render_raster_field(
                ax,
                raster_masked=arr_masked,
                transform=transform,
                watershed_gdf=ws_gdf,
                cmap=cmap,
                colorbar_label=cb_label,
            )
            ax.set_title(f"{label.replace('_', ' ').title()} — {run.run_id}", fontsize=10)
            fig.tight_layout()
            finalize_figure(fig, options=options, save_path=output_dir / f"{label}.png")
            continue
        elif store is not None and sim_id is not None:
            data_dict = _load_field_dict_from_store(store, sim_id, label)
            if data_dict is None:
                continue
            last_key = max(data_dict.keys())
            arr = data_dict[last_key].astype(float)

            dem_masked, transform, nodata = _load_raster(dem_path)
            if nodata is not None:
                arr_masked = np.ma.masked_where(
                    np.isclose(dem_masked.data, float(nodata)), arr,
                )
            else:
                arr_masked = np.ma.masked_where(arr < -9000, arr)

            import geopandas as gpd

            ws_gdf = None
            if geo.watershed_shp is not None:
                ws_gdf = gpd.read_file(str(geo.watershed_shp))

            fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
            ax = _single_axes(axs)
            render_raster_field(
                ax,
                raster_masked=arr_masked,
                transform=transform,
                watershed_gdf=ws_gdf,
                cmap=cmap,
                colorbar_label=cb_label,
            )
            ax.set_title(f"{label.replace('_', ' ').title()} — {run.run_id}", fontsize=10)
            fig.tight_layout()
            finalize_figure(fig, options=options, save_path=output_dir / f"{label}.png")
            continue
        else:
            continue

        # Raster file path available
        raster_masked, transform, nodata = _load_raster(raster_path)

        import geopandas as gpd

        ws_gdf = None
        if geo.watershed_shp is not None:
            ws_gdf = gpd.read_file(str(geo.watershed_shp))

        fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
        ax = _single_axes(axs)
        render_raster_field(
            ax,
            raster_masked=raster_masked,
            transform=transform,
            watershed_gdf=ws_gdf,
            cmap=cmap,
            colorbar_label=cb_label,
        )
        ax.set_title(f"{label.replace('_', ' ').title()} — {run.run_id}", fontsize=10)
        fig.tight_layout()
        finalize_figure(fig, options=options, save_path=output_dir / f"{label}.png")


def _plot_cross_section(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Cross-section from watertable elevation .npy and DEM."""
    dem_path = run.base_raster(geo)
    if dem_path is None:
        return

    wt_dict = _load_npy_dict(run.watertable_elevation_npy)
    if wt_dict is None and store is not None and sim_id is not None:
        wt_dict = _load_field_dict_from_store(store, sim_id, "watertable_elevation")
    if wt_dict is None:
        return

    dem_masked, transform, nodata = _load_raster(dem_path)
    dem_2d = dem_masked.data.astype(float)
    if nodata is not None:
        dem_2d[np.isclose(dem_2d, float(nodata))] = np.nan

    last_key = max(wt_dict.keys())
    wt_2d = wt_dict[last_key].astype(float)
    wt_2d[wt_2d < -9000] = np.nan

    # Take middle column cross section
    col_idx = dem_2d.shape[1] // 2
    dem_section = dem_2d[:, col_idx]
    wt_section = wt_2d[:, col_idx]

    row_spacing = abs(float(transform.e)) if transform.e else 1.0
    x_coords = np.arange(dem_2d.shape[0], dtype=float) * row_spacing

    from hydromodpy.analysis.display.figures.cross_section import plot_cross_section

    plot_cross_section(
        dem_section=dem_section,
        wt_section=wt_section,
        x_coords=x_coords,
        options=options,
        save_path=output_dir / "cross_section.png",
    )


def _plot_hydrography(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
) -> None:
    """Hydrography map — river network shapefile or flow-accumulation drainage."""
    dem_path = run.base_raster(geo)
    if dem_path is None or geo.watershed_shp is None:
        return

    import geopandas as gpd

    streams_gdf = None

    # Prefer vector river network if available
    if geo.river_network_shp is not None:
        streams_gdf = gpd.read_file(geo.river_network_shp)
    elif geo.dem_acc_tif is not None:
        # Derive synthetic stream lines from flow accumulation raster
        streams_gdf = _streams_from_accumulation(geo.dem_acc_tif, geo.watershed_shp)

    if streams_gdf is None or streams_gdf.empty:
        return

    from hydromodpy.analysis.display.figures.maps import plot_hydrography_map

    plot_hydrography_map(
        dem_path=dem_path,
        watershed_shp=geo.watershed_shp,
        streams_gdf=streams_gdf,
        title=run.run_id,
        options=options,
        save_path=output_dir / "hydrography.png",
    )


def _streams_from_accumulation(
    acc_path: Path,
    watershed_shp: Path,
) -> "gpd.GeoDataFrame | None":
    """Derive stream lines from a flow-accumulation raster by thresholding.

    Cells with accumulation above the 90th percentile of positive values
    are vectorised into line segments following the raster grid.
    """
    import geopandas as gpd
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import LineString, shape
    from shapely.ops import linemerge, unary_union

    with rasterio.open(acc_path) as src:
        acc = src.read(1).astype(float)
        transform = src.transform
        crs = src.crs
        nodata = src.nodata

    if nodata is not None:
        acc[np.isclose(acc, float(nodata))] = 0.0
    acc[acc < 0] = 0.0

    positive = acc[acc > 0]
    if positive.size == 0:
        return None

    # Threshold: top 10% of accumulation values
    threshold = float(np.percentile(positive, 90))
    stream_mask = (acc >= threshold).astype(np.uint8)

    if stream_mask.sum() == 0:
        return None

    # Vectorise the stream mask into polygons, then extract centerlines
    # by converting thin raster cells into line segments
    rows, cols = np.where(stream_mask == 1)
    if len(rows) == 0:
        return None

    cell_dx = abs(float(transform.a))
    cell_dy = abs(float(transform.e))

    # Build line segments connecting adjacent stream cells
    segments: list[LineString] = []
    stream_set = set(zip(rows.tolist(), cols.tolist()))

    for r, c in stream_set:
        x0 = transform.c + (c + 0.5) * transform.a + (r + 0.5) * transform.b
        y0 = transform.f + (c + 0.5) * transform.d + (r + 0.5) * transform.e
        # Check 4-connected neighbours (right, down)
        for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            nr, nc = r + dr, c + dc
            if (nr, nc) in stream_set:
                x1 = transform.c + (nc + 0.5) * transform.a + (nr + 0.5) * transform.b
                y1 = transform.f + (nc + 0.5) * transform.d + (nr + 0.5) * transform.e
                segments.append(LineString([(x0, y0), (x1, y1)]))

    if not segments:
        return None

    # Merge connected segments into longer lines
    merged = linemerge(unary_union(segments))
    if merged.is_empty:
        return None

    # Clip to watershed extent
    try:
        ws = gpd.read_file(str(watershed_shp))
        ws_union = ws.geometry.union_all()
        merged = merged.intersection(ws_union)
    except Exception:
        pass

    if merged.is_empty:
        return None

    from shapely.geometry import MultiLineString

    if isinstance(merged, LineString):
        lines = [merged]
    elif isinstance(merged, MultiLineString):
        lines = list(merged.geoms)
    else:
        # GeometryCollection — filter lines only
        lines = [g for g in merged.geoms if isinstance(g, LineString)]

    if not lines:
        return None

    return gpd.GeoDataFrame(geometry=lines, crs=crs)


def _plot_pathlines(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
) -> None:
    """Pathlines map from particle shapefiles."""
    if run.pathlines_weighted_shp is None or run.starting_weighted_shp is None:
        return
    dem_path = run.base_raster(geo)
    if dem_path is None or geo.watershed_shp is None:
        return

    import geopandas as gpd

    pathlines_gdf = gpd.read_file(run.pathlines_weighted_shp)
    endpoints_gdf = gpd.read_file(run.starting_weighted_shp)

    from hydromodpy.analysis.display.figures.maps import plot_pathlines_map

    plot_pathlines_map(
        dem_path=dem_path,
        watershed_shp=geo.watershed_shp,
        pathlines_gdf=pathlines_gdf,
        endpoints_gdf=endpoints_gdf,
        options=options,
        save_path=output_dir / "pathlines.png",
    )


def _plot_budget(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Groundwater budget bar chart from .npy budget files."""
    import matplotlib.pyplot as plt

    _BUDGET_VARIABLE_MAP = {
        "Recharge": "accumulation_flux",
        "GW Flux": "groundwater_flux",
        "GW Storage": "groundwater_storage",
        "Drain Outflow": "outflow_drain",
    }

    budget_items: list[tuple[str, float]] = []
    for label, npy_path in [
        ("Recharge", run.accumulation_flux_npy),
        ("GW Flux", run.groundwater_flux_npy),
        ("GW Storage", run.groundwater_storage_npy),
        ("Drain Outflow", run.outflow_drain_npy),
    ]:
        data = _load_npy_dict(npy_path)
        if data is None and store is not None and sim_id is not None:
            data = _load_field_dict_from_store(
                store, sim_id, _BUDGET_VARIABLE_MAP[label],
            )
        if data is None:
            continue
        last_key = max(data.keys())
        arr = data[last_key].astype(float)
        arr[arr < -9000] = 0.0
        total = float(np.nansum(arr))
        budget_items.append((label, total))

    if not budget_items:
        return

    labels = [b[0] for b in budget_items]
    values = [b[1] for b in budget_items]
    colors = ["dodgerblue", "seagreen", "gold", "tomato"][:len(values)]

    fig, axs = make_figure(figsize=(8, 4), dpi=options.dpi)
    ax = _single_axes(axs)
    bars = ax.bar(labels, values, color=colors, edgecolor="k", alpha=0.8)
    ax.set_ylabel("Volume [m³/d]")
    ax.set_title(f"Groundwater budget — {run.run_id}", fontsize=10)
    ax.grid(True, alpha=0.3, axis="y")

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height(),
            f"{val:.2e}", ha="center", va="bottom", fontsize=7,
        )

    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=output_dir / "budget.png")


# ------------------------------------------------------------------
# Suite functions
# ------------------------------------------------------------------

def plot_posthoc_flow_suite(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Run all enabled flow figures from post-hoc disk data.

    Parameters
    ----------
    store : ResultStore, optional
        When provided, spatial fields are loaded from the store as
        fallback when ``.npy`` files are absent.
    sim_id : str, optional
        Simulation UUID in the store.
    """
    if not options.should_render():
        return

    output_dir = run.postprocess_dir / "_figures"

    if options.flow.is_enabled("dem_map", default=True):
        logger.info("Generating DEM overview: %s", run.run_id)
        _plot_dem_overview(run, geo, options, output_dir)

    if options.flow.is_enabled("watertable_map", default=True):
        logger.info("Generating watertable maps: %s", run.run_id)
        _plot_watertable_maps(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("cross_section", default=True):
        logger.info("Generating cross section: %s", run.run_id)
        _plot_cross_section(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("budget", default=False):
        logger.info("Generating budget chart: %s", run.run_id)
        _plot_budget(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("hydrography", default=True):
        logger.info("Generating hydrography map: %s", run.run_id)
        _plot_hydrography(run, geo, options, output_dir)


def plot_posthoc_particles_suite(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
) -> None:
    """Run particle-tracking figures from post-hoc disk data."""
    if not options.should_render():
        return

    if not options.particles.is_enabled("pathlines", default=False):
        return

    output_dir = run.postprocess_dir / "_figures"
    logger.info("Generating pathlines map: %s", run.run_id)
    _plot_pathlines(run, geo, options, output_dir)


def plot_posthoc_all(
    ctx: PosthocContext,
    options: DisplayOptions,
    *,
    store: Any = None,
) -> list[Path]:
    """Run all post-hoc display suites for every run in *ctx*.

    Parameters
    ----------
    store : ResultStore, optional
        When provided, spatial fields and timeseries are loaded from
        the store as fallback when disk files are absent.

    Returns the list of directories where figures were saved.
    """
    if not options.should_render():
        return []

    figure_dirs: list[Path] = []
    for run in ctx.runs:
        output_dir = run.postprocess_dir / "_figures"
        plot_posthoc_flow_suite(
            run, ctx.geographic, options,
            store=store, sim_id=run.run_id,
        )
        plot_posthoc_particles_suite(run, ctx.geographic, options)
        if output_dir.is_dir():
            figure_dirs.append(output_dir)

    return figure_dirs
