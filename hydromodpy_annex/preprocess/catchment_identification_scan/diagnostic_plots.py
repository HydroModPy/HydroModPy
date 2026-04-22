"""Diagnostic plotting utilities for catchment-identification workflow."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from matplotlib import colormaps, colors
from matplotlib import pyplot as plt


def _read_raster_for_plot(path: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Read one raster for plotting and return masked array + extent."""
    with rasterio.open(path) as src:
        values = src.read(1).astype(float)
        nodata = src.nodata
        bounds = src.bounds
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= ~np.isclose(values, float(nodata), equal_nan=False)
    display = np.where(valid, values, np.nan)
    extent = (bounds.left, bounds.right, bounds.bottom, bounds.top)
    return display, extent


def _build_basin_plot_frame(basins: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Build one plotting frame with stable color index and text labels."""
    plot_frame = basins.copy().reset_index(drop=True)
    plot_frame["plot_code"] = np.arange(1, len(plot_frame) + 1, dtype=int)
    if "area_km2" in plot_frame.columns:
        plot_frame["basin_area_km2"] = np.asarray(plot_frame["area_km2"], dtype=float)
    else:
        plot_frame["basin_area_km2"] = (
            np.asarray(plot_frame.geometry.area, dtype=float) / 1_000_000.0
        )
    if "outlet_id" in plot_frame.columns:
        plot_frame["plot_label"] = plot_frame["outlet_id"].astype(int).astype(str)
    elif "basin_id" in plot_frame.columns:
        plot_frame["plot_label"] = plot_frame["basin_id"].astype(int).astype(str)
    else:
        plot_frame["plot_label"] = plot_frame["plot_code"].astype(str)
    return plot_frame


def _build_area_norm(values: np.ndarray) -> colors.Normalize | None:
    """Build normalization object for basin-area color mapping."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    vmin = float(np.nanmin(finite))
    vmax = float(np.nanmax(finite))
    if np.isclose(vmin, vmax):
        vmax = vmin + 1.0e-6
    return colors.Normalize(vmin=vmin, vmax=vmax)


def export_diagnostic_figures(
    *,
    figures_dir: Path,
    dem_corrected_path: Path,
    d8_accumulation_path: Path,
    basins: gpd.GeoDataFrame,
    outlets_selected: gpd.GeoDataFrame,
    outlets_candidates: gpd.GeoDataFrame,
    stream_mask: np.ndarray,
    candidate_outlet_mask: np.ndarray,
    threshold_area_km2: float,
) -> dict[str, str]:
    """Save diagnostic figures used for manual QA of catchment extraction."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    basins_plot = _build_basin_plot_frame(basins) if not basins.empty else basins
    area_norm = (
        _build_area_norm(np.asarray(basins_plot["basin_area_km2"], dtype=float))
        if not basins_plot.empty
        else None
    )
    area_cmap = colormaps["plasma"]

    dem, dem_extent = _read_raster_for_plot(dem_corrected_path)
    fig, ax = plt.subplots(1, 1, figsize=(10.5, 7.6), dpi=130)
    im = ax.imshow(dem, extent=dem_extent, origin="upper", cmap="terrain", zorder=1)
    cbar_dem = fig.colorbar(im, ax=ax, fraction=0.042, pad=0.015)
    cbar_dem.set_label("Elevation [m]")
    cbar_dem.ax.tick_params(labelsize=8)
    if not basins_plot.empty:
        basins_plot.plot(
            ax=ax,
            column="basin_area_km2",
            cmap=area_cmap,
            vmin=(float(area_norm.vmin) if area_norm is not None else None),
            vmax=(float(area_norm.vmax) if area_norm is not None else None),
            alpha=0.36,
            linewidth=0.0,
            zorder=3,
        )
        basins_plot.boundary.plot(ax=ax, color="black", linewidth=0.7, zorder=4)
        if area_norm is not None:
            sm = plt.cm.ScalarMappable(norm=area_norm, cmap=area_cmap)
            sm.set_array([])
            cbar_area = fig.colorbar(sm, ax=ax, fraction=0.042, pad=0.10)
            cbar_area.set_label("Basin area [km2]")
            cbar_area.ax.tick_params(labelsize=8)
    if not outlets_candidates.empty:
        outlets_candidates.plot(
            ax=ax, color="#ffbf00", markersize=12, marker="o", zorder=5, label="Candidates"
        )
    if not outlets_selected.empty:
        outlets_selected.plot(
            ax=ax, color="#d62728", markersize=20, marker="^", zorder=6, label="Selected outlets"
        )
    ax.set_title(
        f"Catchment overview (basin color = area) | basins={len(basins)} | selected_outlets={len(outlets_selected)}"
    )
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    handles, labels = ax.get_legend_handles_labels()
    if handles and labels:
        ax.legend(handles=handles, labels=labels, loc="lower left", framealpha=0.9)
    fig.tight_layout(pad=0.5)
    spatial_path = figures_dir / "01_spatial_overview.png"
    fig.savefig(spatial_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    paths["spatial_overview"] = str(spatial_path)

    accumulation_cells, acc_extent = _read_raster_for_plot(d8_accumulation_path)
    accumulation_log10 = np.where(accumulation_cells > 0.0, np.log10(accumulation_cells), np.nan)
    fig, ax = plt.subplots(1, 1, figsize=(10.5, 7.6), dpi=130)
    im = ax.imshow(accumulation_log10, extent=acc_extent, origin="upper", cmap="viridis")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.015)
    cbar.set_label("log10(accumulation cells)")
    if stream_mask.shape == accumulation_log10.shape:
        stream_overlay = np.where(stream_mask, 1.0, np.nan)
        ax.imshow(
            stream_overlay,
            extent=acc_extent,
            origin="upper",
            cmap="Blues",
            alpha=0.35,
            vmin=0.0,
            vmax=1.0,
        )
    if candidate_outlet_mask.shape == accumulation_log10.shape:
        candidate_overlay = np.where(candidate_outlet_mask, 1.0, np.nan)
        ax.imshow(
            candidate_overlay,
            extent=acc_extent,
            origin="upper",
            cmap="Reds",
            alpha=0.45,
            vmin=0.0,
            vmax=1.0,
        )
    if not outlets_selected.empty:
        outlets_selected.plot(ax=ax, color="#ff7f0e", markersize=22, marker="^", zorder=7)
    ax.set_title("Accumulation threshold diagnostics (streams + border candidates)")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.tight_layout(pad=0.5)
    acc_path = figures_dir / "02_accumulation_threshold.png"
    fig.savefig(acc_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    paths["accumulation_threshold"] = str(acc_path)

    fig, ax = plt.subplots(1, 1, figsize=(8.6, 6.4), dpi=130)
    if not outlets_selected.empty:
        x_vals = np.asarray(outlets_selected["accumulation_area_km2"], dtype=float)
        y_vals = np.asarray(outlets_selected["basin_area_km2"], dtype=float)
        valid = np.isfinite(x_vals) & np.isfinite(y_vals) & (x_vals > 0.0) & (y_vals > 0.0)
        x_plot = x_vals[valid]
        y_plot = y_vals[valid]
        ax.scatter(
            x_plot,
            y_plot,
            s=28.0,
            alpha=0.9,
            color="#1f77b4",
            edgecolor="black",
            linewidth=0.35,
        )
        max_xy = float(max(np.max(x_plot), np.max(y_plot))) if x_plot.size else 1.0
        ax.plot([0.0, max_xy], [0.0, max_xy], color="black", linestyle="--", linewidth=1.0)
        ax.axvline(float(threshold_area_km2), color="#d62728", linestyle=":", linewidth=1.0)
        ax.axhline(float(threshold_area_km2), color="#d62728", linestyle=":", linewidth=1.0)
    else:
        ax.text(
            0.5,
            0.5,
            "No selected outlets available",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    ax.set_title("Outlet accumulation area vs delineated basin area")
    ax.set_xlabel("Accumulation area at outlet [km2]")
    ax.set_ylabel("Delineated basin area [km2]")
    ax.grid(alpha=0.2, linestyle="--")
    fig.tight_layout(pad=0.5)
    scatter_path = figures_dir / "03_area_consistency_scatter.png"
    fig.savefig(scatter_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    paths["area_consistency_scatter"] = str(scatter_path)

    fig, ax = plt.subplots(1, 1, figsize=(8.6, 6.4), dpi=130)
    area_values = np.asarray(basins["area_km2"], dtype=float) if not basins.empty else np.array([])
    valid_area = area_values[np.isfinite(area_values)]
    if valid_area.size:
        bins = max(8, min(40, int(np.ceil(np.sqrt(valid_area.size) * 2.0))))
        ax.hist(valid_area, bins=bins, color="#4c78a8", edgecolor="black", alpha=0.85)
    else:
        ax.text(
            0.5,
            0.5,
            "No basin area to display",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    ax.axvline(float(threshold_area_km2), color="#d62728", linestyle="--", linewidth=1.25)
    ax.set_title("Basin area distribution")
    ax.set_xlabel("Basin area [km2]")
    ax.set_ylabel("Count")
    ax.grid(axis="y", alpha=0.2, linestyle="--")
    fig.tight_layout(pad=0.5)
    hist_path = figures_dir / "04_basin_area_histogram.png"
    fig.savefig(hist_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    paths["basin_area_histogram"] = str(hist_path)

    fig, ax = plt.subplots(1, 1, figsize=(11.2, 8.2), dpi=140)
    im_bg = ax.imshow(dem, extent=dem_extent, origin="upper", cmap="terrain", alpha=0.58, zorder=1)
    cbar_dem = fig.colorbar(im_bg, ax=ax, fraction=0.040, pad=0.015)
    cbar_dem.set_label("Elevation [m]")
    cbar_dem.ax.tick_params(labelsize=8)
    if not basins_plot.empty:
        basins_plot.plot(
            ax=ax,
            column="basin_area_km2",
            cmap=area_cmap,
            vmin=(float(area_norm.vmin) if area_norm is not None else None),
            vmax=(float(area_norm.vmax) if area_norm is not None else None),
            alpha=0.72,
            linewidth=0.85,
            edgecolor="#222222",
            zorder=3,
        )
        if area_norm is not None:
            sm = plt.cm.ScalarMappable(norm=area_norm, cmap=area_cmap)
            sm.set_array([])
            cbar_area = fig.colorbar(sm, ax=ax, fraction=0.040, pad=0.10)
            cbar_area.set_label("Basin area [km2]")
            cbar_area.ax.tick_params(labelsize=8)
    if not outlets_selected.empty:
        outlets_selected.plot(
            ax=ax,
            color="black",
            markersize=20,
            marker="^",
            zorder=6,
            label="Selected outlets",
        )
    ax.set_title("Catchment map (basin color = area)")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    handles, labels = ax.get_legend_handles_labels()
    if handles and labels:
        ax.legend(handles=handles, labels=labels, loc="lower left", framealpha=0.9)
    fig.tight_layout(pad=0.5)
    id_map_path = figures_dir / "05_basin_identification_map.png"
    fig.savefig(id_map_path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    paths["basin_identification_map"] = str(id_map_path)

    return paths
