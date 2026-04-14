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
import shutil
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.analysis.display.common import (
    ensure_dir,
    finalize_figure,
    load_field_dict_from_store,
    make_figure,
    plot_common_flow_spatial_outputs,
    _single_axes,
)
from hydromodpy.analysis.display.display_config import DisplayOptions
from hydromodpy.analysis.display.flow_payloads import (
    build_flow_cumulative_payload,
    build_flow_spatial_payload_from_run,
)
from hydromodpy.analysis.display.posthoc import GeographicArtifacts, PosthocContext, RunArtifacts
from hydromodpy.analysis.display.figures.flow_synthesis import (
    plot_flow_recharge_discharge_cumulative,
)

logger = logging.getLogger(__name__)


def _get_watershed_gdf(geo):
    """Get watershed GeoDataFrame from store or file, None on failure."""
    try:
        return geo.read_feature("watershed")
    except (KeyError, Exception):
        pass
    if getattr(geo, "watershed_shp", None) is not None:
        import geopandas as gpd
        return gpd.read_file(str(geo.watershed_shp))
    return None


def _load_raster(path=None, *, geo=None, name="watershed_dem"):
    """Load a raster and return (masked_array, transform, nodata).

    Uses the store via *geo.read_raster(name)* as the primary source.
    Only uses *path* for solver-specific rasters (grid template) that
    are not geographic data.
    Returns ``(None, None, None)`` when unavailable.
    """
    from rasterio.transform import Affine

    data = None
    nodata_val = None
    transform = None

    # Primary: store via GeographicArtifacts
    if geo is not None:
        try:
            arr, meta = geo.read_raster(name)
            data = arr.astype(float)
            nodata_val = meta.get("nodata", -99999.0)
            t = meta.get("transform", (1, 0, 0, 0, -1, 0))
            transform = Affine(*t[:6]) if not isinstance(t, Affine) else t
        except (KeyError, Exception):
            pass

    # Solver-specific rasters (grid template) still on disk
    if data is None and path is not None:
        p = Path(path)
        if p.exists():
            import rasterio
            with rasterio.open(p) as src:
                data = src.read(1).astype(float)
                nodata_val = src.nodata
                transform = src.transform

    if data is None:
        return None, None, None

    if nodata_val is not None:
        mask = np.isclose(data, float(nodata_val))
    else:
        mask = data < -9000
    masked = np.ma.masked_where(mask, data)
    return masked, transform, nodata_val


def _copy_latest_native_mesh_figures(
    run: RunArtifacts,
    output_dir: Path,
    *,
    mapping: list[tuple[str, str]],
) -> list[Path]:
    """Copy solver-native mesh PNGs into the standard posthoc figure folder."""
    native_dir = run.native_mesh_figure_dir
    if native_dir is None:
        return []
    copied: list[Path] = []
    ensure_dir(output_dir)
    for pattern, target_name in mapping:
        candidates = sorted(native_dir.glob(pattern))
        if not candidates:
            continue
        source = candidates[-1]
        target = output_dir / target_name
        shutil.copyfile(source, target)
        copied.append(target)
    return copied


def _load_simulated_timeseries(run: RunArtifacts) -> pd.DataFrame | None:
    """Load the common simulated timeseries CSV when present."""
    path = run.simulated_timeseries_csv
    if path is None or not path.exists():
        return None
    return pd.read_csv(path, sep=";", index_col=0, parse_dates=True)


# ------------------------------------------------------------------
# Individual figure generators
# ------------------------------------------------------------------

def _render_dem_on_ax(ax, dem_masked, transform, ws_gdf=None, basemap=False):
    """Render DEM raster + watershed contour on an Axes from in-memory data."""
    from rasterio.plot import show as rio_show
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    rio_show(dem_masked, ax=ax, transform=transform, cmap="terrain",
             alpha=0.75, zorder=2, aspect="auto")

    if ws_gdf is not None:
        ws_gdf.plot(ax=ax, lw=1.5, zorder=4, edgecolor="k", facecolor="None")
        if basemap:
            try:
                import contextily as cx
                cx.add_basemap(ax, crs=ws_gdf.crs, zorder=0, alpha=0.4)
            except Exception:
                pass

    ax.set_aspect("equal")
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)

    valid = dem_masked.compressed()
    if valid.size > 0:
        vmin_f, vmax_f = float(valid.min()), float(valid.max())
        sm = cm.ScalarMappable(
            cmap="terrain", norm=mcolors.Normalize(vmin=vmin_f, vmax=vmax_f),
        )
        sm.set_array([])
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.05)
        ax.figure.colorbar(sm, cax=cax, orientation="vertical")


def _plot_dem_overview(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
) -> None:
    """DEM overview map with watershed contour."""
    dem_masked, transform, nodata = _load_raster(geo=geo)
    ws_gdf = _get_watershed_gdf(geo)
    if dem_masked is None or ws_gdf is None:
        return

    fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
    ax = _single_axes(axs)
    _render_dem_on_ax(ax, dem_masked, transform, ws_gdf,
                      basemap=options.flow.is_enabled("basemap", default=False))
    ax.set_title(run.run_id, fontsize=10)
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=output_dir / "dem_overview.png")


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
    dem_masked, transform, nodata = _load_raster(geo=geo)
    if dem_masked is None:
        return

    from hydromodpy.analysis.display.figures.spatial import render_raster_field

    for label, cmap, cb_label in [
        ("watertable_depth", "Blues", "WT depth [m]"),
        ("watertable_elevation", "terrain", "WT elevation [m]"),
        ("seepage_areas", "Reds", "Seepage [0/1]"),
    ]:
        # Load array from catalog.
        data_dict = None
        if store is not None and sim_id is not None:
            data_dict = load_field_dict_from_store(store, sim_id, label)
        if data_dict is not None:
            last_key = max(data_dict.keys())
            arr = data_dict[last_key].astype(float)

            dem_masked, transform, nodata = _load_raster(geo=geo)
            # Reshape flat store array to match 2D DEM grid.
            if arr.ndim == 1 and dem_masked.ndim == 2:
                try:
                    arr = arr.reshape(dem_masked.shape)
                except ValueError:
                    # Multi-layer: take top layer then reshape.
                    n_cells_2d = dem_masked.shape[0] * dem_masked.shape[1]
                    arr = arr[:n_cells_2d].reshape(dem_masked.shape)
            elif arr.ndim == 2:
                # (n_layers, n_cells) — take top layer.
                arr = arr[0]
                if arr.size == dem_masked.size:
                    arr = arr.reshape(dem_masked.shape)

            if nodata is not None:
                arr_masked = np.ma.masked_where(
                    np.isclose(dem_masked.data, float(nodata)), arr,
                )
            else:
                arr_masked = np.ma.masked_where(arr < -9000, arr)

            import geopandas as gpd

            ws_gdf = None
            if _get_watershed_gdf(geo) is not None:
                ws_gdf = geo.read_feature("watershed")

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


def _plot_composite_wtd_seepage(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Composite map: water-table depth + seepage + pathlines."""
    dem_masked, transform, nodata = _load_raster(geo=geo)
    if dem_masked is None:
        return

    wtd_dict = None
    seepage_dict = None
    if store is not None and sim_id is not None:
        wtd_dict = load_field_dict_from_store(store, sim_id, "watertable_depth")
        seepage_dict = load_field_dict_from_store(store, sim_id, "seepage_areas")
    if wtd_dict is None:
        return

    last_key = max(wtd_dict.keys())
    wtd_arr = wtd_dict[last_key].astype(float)

    # Reshape flat store array to 2D DEM grid
    if wtd_arr.ndim == 1 and dem_masked.ndim == 2:
        try:
            wtd_arr = wtd_arr.reshape(dem_masked.shape)
        except ValueError:
            wtd_arr = wtd_arr[: dem_masked.size].reshape(dem_masked.shape)
    elif wtd_arr.ndim == 2:
        wtd_arr = wtd_arr[0]
        if wtd_arr.size == dem_masked.size:
            wtd_arr = wtd_arr.reshape(dem_masked.shape)

    if nodata is not None:
        wtd_masked = np.ma.masked_where(np.isclose(dem_masked.data, float(nodata)), wtd_arr)
    else:
        wtd_masked = np.ma.masked_where(wtd_arr < -9000, wtd_arr)

    seepage_masked = None
    if seepage_dict is not None:
        seep_arr = seepage_dict[max(seepage_dict.keys())].astype(float)
        if seep_arr.ndim == 1 and dem_masked.ndim == 2:
            try:
                seep_arr = seep_arr.reshape(dem_masked.shape)
            except ValueError:
                seep_arr = seep_arr[: dem_masked.size].reshape(dem_masked.shape)
        elif seep_arr.ndim == 2:
            seep_arr = seep_arr[0]
            if seep_arr.size == dem_masked.size:
                seep_arr = seep_arr.reshape(dem_masked.shape)
        if nodata is not None:
            seepage_masked = np.ma.masked_where(np.isclose(dem_masked.data, float(nodata)), seep_arr)
        else:
            seepage_masked = np.ma.masked_where(seep_arr < -9000, seep_arr)

    import geopandas as gpd

    ws_gdf = None
    if _get_watershed_gdf(geo) is not None:
        ws_gdf = geo.read_feature("watershed")

    pathlines_gdf = None
    if run.pathlines_weighted_shp is not None and run.pathlines_weighted_shp.exists():
        pathlines_gdf = gpd.read_file(str(run.pathlines_weighted_shp))

    cfg_col = options.flow.flags.get("cross_section_column")
    cross_col = cfg_col if cfg_col is not None else dem_masked.shape[1] // 2

    from hydromodpy.analysis.display.figures.spatial import plot_seepage_pathlines_wtd

    plot_seepage_pathlines_wtd(
        wtd_masked=wtd_masked,
        transform=transform,
        seepage_masked=seepage_masked,
        watershed_gdf=ws_gdf,
        pathlines_gdf=pathlines_gdf,
        cross_section_col=cross_col,
        title="Seepage fed by pathlines and map of water table depth [m]",
        options=options,
        save_path=output_dir / "composite_seepage_wtd.png",
        figsize=(8, 5),
    )


def _plot_cross_section(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Cross-section from watertable elevation and DEM."""
    dem_masked, transform, nodata = _load_raster(geo=geo)
    if dem_masked is None:
        return

    wt_dict = None
    if store is not None and sim_id is not None:
        wt_dict = load_field_dict_from_store(store, sim_id, "watertable_elevation")
    if wt_dict is None:
        return

    dem_2d = dem_masked.data.astype(float)
    if nodata is not None:
        dem_2d[np.isclose(dem_2d, float(nodata))] = np.nan

    last_key = max(wt_dict.keys())
    wt_2d = wt_dict[last_key].astype(float)
    # Reshape flat store array to match DEM grid.
    if wt_2d.ndim == 1 and dem_2d.ndim == 2:
        try:
            wt_2d = wt_2d.reshape(dem_2d.shape)
        except ValueError:
            wt_2d = wt_2d[:dem_2d.size].reshape(dem_2d.shape)
    elif wt_2d.ndim == 2 and wt_2d.shape != dem_2d.shape:
        wt_2d = wt_2d[0]
        if wt_2d.size == dem_2d.size:
            wt_2d = wt_2d.reshape(dem_2d.shape)
    wt_2d[~np.isfinite(wt_2d)] = np.nan

    # Column cross section (N-S direction, matching legacy)
    cfg_col = options.flow.flags.get("cross_section_column")
    col_idx = cfg_col if cfg_col is not None else dem_2d.shape[1] // 2
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
    """Hydrography map — river network from store or flow-accumulation."""
    dem_masked, transform, nodata = _load_raster(geo=geo)
    ws_gdf = _get_watershed_gdf(geo)
    if dem_masked is None or ws_gdf is None:
        return

    streams_gdf = None

    # Prefer vector river network from store
    try:
        streams_gdf = geo.read_feature("river_network")
    except (KeyError, Exception):
        pass

    # Fallback: derive from flow-accumulation raster in store
    if streams_gdf is None:
        try:
            acc_arr, acc_meta = geo.read_raster("dem_acc")
            streams_gdf = _streams_from_accumulation_array(
                acc_arr, acc_meta, ws_gdf,
            )
        except (KeyError, Exception):
            pass

    if streams_gdf is None or streams_gdf.empty:
        return

    fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
    ax = _single_axes(axs)
    _render_dem_on_ax(ax, dem_masked, transform, ws_gdf)
    streams_gdf.plot(ax=ax, lw=1.5, color="navy", zorder=5)
    ax.set_title(f"Hydrography — {run.run_id}", fontsize=10)
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=output_dir / "hydrography.png")


def _streams_from_accumulation_array(
    acc: np.ndarray,
    meta: dict,
    ws_gdf: "gpd.GeoDataFrame | None" = None,
) -> "gpd.GeoDataFrame | None":
    """Derive stream lines from a flow-accumulation array by thresholding.

    Works with in-memory arrays from the store (no file paths needed).
    """
    import geopandas as gpd
    from rasterio.transform import Affine
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge, unary_union

    acc = acc.astype(float).copy()
    nodata = meta.get("nodata")
    t = meta.get("transform", (1, 0, 0, 0, -1, 0))
    transform = Affine(*t[:6]) if not isinstance(t, Affine) else t
    crs = meta.get("crs")

    if nodata is not None:
        acc[np.isclose(acc, float(nodata))] = 0.0
    acc[acc < 0] = 0.0

    positive = acc[acc > 0]
    if positive.size == 0:
        return None

    threshold = float(np.percentile(positive, 90))
    stream_mask = (acc >= threshold).astype(np.uint8)
    if stream_mask.sum() == 0:
        return None

    rows, cols = np.where(stream_mask == 1)
    if len(rows) == 0:
        return None

    segments: list[LineString] = []
    stream_set = set(zip(rows.tolist(), cols.tolist()))

    for r, c in stream_set:
        x0 = transform.c + (c + 0.5) * transform.a + (r + 0.5) * transform.b
        y0 = transform.f + (c + 0.5) * transform.d + (r + 0.5) * transform.e
        for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            nr, nc = r + dr, c + dc
            if (nr, nc) in stream_set:
                x1 = transform.c + (nc + 0.5) * transform.a + (nr + 0.5) * transform.b
                y1 = transform.f + (nc + 0.5) * transform.d + (nr + 0.5) * transform.e
                segments.append(LineString([(x0, y0), (x1, y1)]))

    if not segments:
        return None

    merged = linemerge(unary_union(segments))
    if merged.is_empty:
        return None

    if ws_gdf is not None:
        try:
            ws_union = ws_gdf.geometry.union_all()
            merged = merged.intersection(ws_union)
        except Exception:
            pass

    if merged.is_empty:
        return None

    if isinstance(merged, LineString):
        lines = [merged]
    elif isinstance(merged, MultiLineString):
        lines = list(merged.geoms)
    else:
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
    dem_masked, transform, nodata = _load_raster(geo=geo)
    ws_gdf = _get_watershed_gdf(geo)
    if dem_masked is None or ws_gdf is None:
        return

    import geopandas as gpd

    pathlines_gdf = gpd.read_file(run.pathlines_weighted_shp)
    endpoints_gdf = gpd.read_file(run.starting_weighted_shp)

    fig, axs = make_figure(figsize=(7, 6), dpi=options.dpi)
    ax = _single_axes(axs)
    _render_dem_on_ax(ax, dem_masked, transform, ws_gdf)
    pathlines_gdf.plot(ax=ax, lw=0.5, color="blue", alpha=0.5, zorder=5)
    endpoints_gdf.plot(ax=ax, markersize=5, color="red", zorder=6)
    ax.set_title(f"Pathlines — {run.run_id}", fontsize=10)
    fig.tight_layout()
    finalize_figure(fig, options=options, save_path=output_dir / "pathlines.png")


def _plot_budget(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Groundwater budget bar chart from catalog fields."""
    import matplotlib.pyplot as plt

    _BUDGET_VARIABLE_MAP = {
        "Recharge": "accumulation_flux",
        "GW Flux": "groundwater_flux",
        "GW Storage": "groundwater_storage",
        "Drain Outflow": "outflow_drain",
    }

    budget_items: list[tuple[str, float]] = []
    for label in ["Recharge", "GW Flux", "GW Storage", "Drain Outflow"]:
        data = None
        if store is not None and sim_id is not None:
            data = load_field_dict_from_store(
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


def _plot_timeseries_summary(
    run: RunArtifacts,
    geo: GeographicArtifacts,
    options: DisplayOptions,
    output_dir: Path,
    *,
    store: Any = None,
    sim_id: str | None = None,
) -> None:
    """Recharge + outflow drain step plots with optional well pumping bars.

    Reproduces the legacy time series figure from example_00.
    """
    if store is None or sim_id is None:
        return

    import pandas as pd
    from hydromodpy.analysis.display.figures.timeseries import plot_discharge

    recharge_ts = None
    outflow_ts = None
    well_ts = None
    # Use forcing recharge (input, 1 value per stress period),
    # not budget recharge (≈ drain at equilibrium).
    try:
        recharge_ts = store.query_timeseries(sim_id, "_catchment", "recharge_forcing")
    except KeyError:
        try:
            recharge_ts = store.query_timeseries(sim_id, "_catchment", "recharge_budget")
        except KeyError:
            pass
    try:
        outflow_ts = store.query_timeseries(sim_id, "_catchment", "outflow_drain")
    except KeyError:
        pass
    try:
        well_ts = store.query_timeseries(sim_id, "_catchment", "well_pumping")
        # Deduplicate (aggregation may run multiple times per sim)
        if well_ts is not None and well_ts.index.has_duplicates:
            well_ts = well_ts.groupby(level=0).first()
    except KeyError:
        pass

    if recharge_ts is None and outflow_ts is None:
        return

    # Convert volumetric budget (m³/d per cell) to mm/month like legacy:
    # rate = budget_value / cell_area; mm/month = rate * 30 * 1000
    cell_area = None
    _, transform, _ = _load_raster(None, geo=geo)
    if transform is not None:
        cell_area = abs(transform.a * transform.e)
    if cell_area is None or cell_area == 0:
        cell_area = 1.0
    factor = 30.0 * 1000.0 / cell_area  # m³/d per cell → mm/month

    rch_scaled = recharge_ts * factor if recharge_ts is not None else None
    out_scaled = outflow_ts * factor if outflow_ts is not None else None

    # Resample substeps to 1 value per stress period.
    # For outflow: take the LAST substep of each period (snapshot, like legacy).
    # For wells: take the min (most negative pumping).
    def _to_monthly(ts, agg="last"):
        """Resample substep timeseries to monthly values."""
        if ts is None:
            return None
        if ts.index.has_duplicates:
            ts = ts.groupby(level=0).first()
        if isinstance(ts.index, pd.DatetimeIndex) and len(ts) > 12:
            resampled = ts.resample("MS")
            if agg == "last":
                return resampled.last()
            elif agg == "min":
                return resampled.min()
            else:
                return resampled.mean()
        return ts

    rch_plot = _to_monthly(rch_scaled, agg="last")  # forcing is constant → last=first=mean
    out_plot = _to_monthly(out_scaled, agg="mean")   # drain mean over all substeps

    well_plot = _to_monthly(well_ts, agg="min") if well_ts is not None else None

    plot_discharge(
        simulated_series=out_plot,
        recharge_series=rch_plot,
        well_fluxes=well_plot,
        model_label=run.run_id,
        ylabel="Output flow results [mm/month]",
        options=options,
        save_path=output_dir / "timeseries_summary.png",
        figsize=(8, 5),
    )


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
    output_dir: Path | None = None,
) -> None:
    """Run all enabled flow figures from post-hoc disk data.

    Parameters
    ----------
    store : SimulationCatalog, optional
        When provided, spatial fields and timeseries are loaded from
        the catalog.
    sim_id : str, optional
        Simulation UUID in the catalog.
    """
    if not options.should_render():
        return

    if output_dir is None:
        output_dir = run.run_dir / "figures" / run.run_id

    spatial_payload = build_flow_spatial_payload_from_run(run)
    cumulative_payload = build_flow_cumulative_payload(
        _load_simulated_timeseries(run),
        run_id=run.run_id,
    )
    rendered_common_spatial = plot_common_flow_spatial_outputs(
        spatial_payload,
        options=options,
        output_dir=output_dir,
    )
    if cumulative_payload is not None and options.flow.is_enabled(
        "recharge_discharge_cumulative",
        default=True,
    ):
        plot_flow_recharge_discharge_cumulative(
            payload=cumulative_payload,
            options=options,
            save_path=output_dir / "recharge_discharge_cumulative.png",
        )

    _copy_latest_native_mesh_figures(
        run,
        output_dir,
        mapping=[
            ("flow_support_overview.png", "flow_support_overview.png"),
        ],
    )
    if not rendered_common_spatial:
        _copy_latest_native_mesh_figures(
            run,
            output_dir,
            mapping=[
                ("flow_watertable_depth_t(*).png", "watertable_depth.png"),
                ("flow_watertable_elevation_t(*).png", "watertable_elevation.png"),
                ("flow_seepage_areas_t(*).png", "seepage_areas.png"),
                ("flow_outflow_drain_t(*).png", "outflow_drain.png"),
                ("flow_accumulation_flux_t(*).png", "accumulation_flux.png"),
            ],
        )

    if options.flow.is_enabled("dem_map", default=True):
        logger.info("Generating DEM overview: %s", run.run_id)
        _plot_dem_overview(run, geo, options, output_dir)

    if options.flow.is_enabled("watertable_map", default=True):
        logger.info("Generating watertable maps: %s", run.run_id)
        _plot_watertable_maps(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("composite_seepage_wtd", default=True):
        logger.info("Generating composite seepage+WTD: %s", run.run_id)
        _plot_composite_wtd_seepage(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("cross_section", default=True):
        logger.info("Generating cross section: %s", run.run_id)
        _plot_cross_section(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("budget", default=False):
        logger.info("Generating budget chart: %s", run.run_id)
        _plot_budget(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("hydrography", default=True):
        logger.info("Generating hydrography map: %s", run.run_id)
        _plot_hydrography(run, geo, options, output_dir)

    if store is not None and sim_id is not None:
        logger.info("Generating timeseries summary: %s", run.run_id)
        _plot_timeseries_summary(run, geo, options, output_dir, store=store, sim_id=sim_id)

    if options.flow.is_enabled("drainage_density", default=True) and store is not None and sim_id is not None:
        from hydromodpy.analysis.display.figures.timeseries import plot_drainage_density
        try:
            total = store.query_timeseries(sim_id, "_catchment", "total_areas")
            perenn = None
            try:
                perenn = store.query_timeseries(sim_id, "_catchment", "perenn_areas")
            except KeyError:
                pass
            logger.info("Generating drainage density: %s", run.run_id)
            plot_drainage_density(
                total_drainage_pct=total,
                perennial_drainage_pct=perenn,
                title=run.run_id,
                options=options,
                save_path=output_dir / "drainage_density.png",
            )
        except KeyError:
            pass

    if options.flow.is_enabled("persistency_map", default=True) and store is not None and sim_id is not None:
        pi_dict = load_field_dict_from_store(store, sim_id, "persistency_index")
        if pi_dict is not None:
            dem_masked, transform, nodata = _load_raster(geo=geo)
            if dem_masked is not None:
                from hydromodpy.analysis.display.figures.spatial import plot_raster_field
                dem_data = np.asarray(dem_masked, dtype=float)
                last_key = max(pi_dict.keys())
                pi = pi_dict[last_key].astype(float)
                if pi.ndim == 1 and dem_data.ndim == 2:
                    pi = pi.reshape(dem_data.shape)
                mask = np.isclose(dem_data, float(nodata)) if nodata else dem_data < -9000
                pi_masked = np.ma.masked_where(mask, pi)
                import geopandas as gpd
                ws_gdf = _get_watershed_gdf(geo)
                logger.info("Generating persistency map: %s", run.run_id)
                plot_raster_field(
                    raster_masked=pi_masked,
                    transform=transform,
                    watershed_gdf=ws_gdf,
                    cmap="jet",
                    colorbar_label="Persistency index [-]",
                    options=options,
                    save_path=output_dir / "persistency_map.png",
                )


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

    output_dir = run.run_dir / "_figures"
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
    store : SimulationCatalog, optional
        When provided, spatial fields and timeseries are loaded from
        the catalog.

    Returns the list of directories where figures were saved.
    """
    if not options.should_render():
        return []

    # Resolve the sim_id from the store (UUID, not run name).
    sim_id = None
    if store is not None:
        try:
            sims = store.list_simulations()
            if not sims.empty:
                sim_id = str(sims.iloc[-1]["sim_id"])
        except Exception:
            pass

    # Use sim_id short (first 8 chars) for the figure folder name.
    sim_label = sim_id[:8] if sim_id else "unknown"

    figure_dirs: list[Path] = []
    for run in ctx.runs:
        output_dir = ctx.project_dir / "figures" / sim_label
        plot_posthoc_flow_suite(
            run, ctx.geographic, options,
            store=store, sim_id=sim_id,
            output_dir=output_dir,
        )
        plot_posthoc_particles_suite(run, ctx.geographic, options)
        if output_dir.is_dir():
            figure_dirs.append(output_dir)

    return figure_dirs
