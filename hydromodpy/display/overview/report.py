"""Orchestrate PNG generation for the data-overview report.

Each enabled panel in ``[overview.panels]`` produces one standalone PNG in
the workspace ``figures/overview/`` directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.display.overview.panels import (
    render_climatic_summary,
    render_dem_map,
    render_geology_map,
    render_hydrography_map,
    render_intermittency,
    render_station_inventory,
    render_stats_card,
    render_timeseries_multi,
    render_water_quality,
)
from hydromodpy.display.overview.summary import compute_overview_summary

logger = get_logger(__name__)

if TYPE_CHECKING:
    from hydromodpy.core.contracts.overview import DataOverviewState


def generate_overview_report(state: DataOverviewState) -> list[Path]:
    """Generate one PNG per enabled panel and return their paths."""
    import matplotlib

    matplotlib.use("Agg")

    if state.cfg.overview is None:
        logger.info("[overview] No [overview] section - skipping report generation.")
        return []

    panels_cfg = state.cfg.overview.panels
    output_dir = _resolve_output_dir(state)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = compute_overview_summary(state)
    ld = state.loaded_data
    dg = state.domain_geographic

    dem_path = getattr(dg, "watershed_box_buff_dem", None) if dg else None
    watershed_shp = getattr(dg, "watershed_shp", None) if dg else None
    streams_gdf = _load_streams_gdf(ld.hydrography)
    title = summary.watershed_name or "Watershed"
    overview_cfg = state.cfg.overview
    date_start = getattr(overview_cfg, "date_start", None)
    date_end = getattr(overview_cfg, "date_end", None)

    paths: list[Path] = []

    if panels_cfg.map_dem and dem_path:
        station_points = _build_station_points(ld)
        paths.append(
            _render_panel(
                output_dir / "map_dem.png",
                figsize=(7, 6),
                render_fn=render_dem_map,
                dem_path=str(dem_path),
                watershed_shp=str(watershed_shp) if watershed_shp else None,
                streams_gdf=streams_gdf,
                station_points=station_points,
                title=f"{title} - DEM",
            )
        )

    if panels_cfg.map_geology and dem_path and ld.geology is not None:
        geology_gdf = _load_geology_gdf(ld.geology)
        paths.append(
            _render_panel(
                output_dir / "map_geology.png",
                figsize=(9, 6),
                render_fn=render_geology_map,
                dem_path=str(dem_path),
                watershed_shp=str(watershed_shp) if watershed_shp else None,
                geology_gdf=geology_gdf,
                title=f"{title} - Geology",
            )
        )

    if panels_cfg.map_hydrography and dem_path:
        outlet_xy = None
        if dg and dg.x_outlet is not None and dg.y_outlet is not None:
            outlet_xy = (float(dg.x_outlet), float(dg.y_outlet))
        paths.append(
            _render_panel(
                output_dir / "map_hydrography.png",
                figsize=(7, 6),
                render_fn=render_hydrography_map,
                dem_path=str(dem_path),
                watershed_shp=str(watershed_shp) if watershed_shp else None,
                streams_gdf=streams_gdf,
                outlet_xy=outlet_xy,
                title=f"{title} - Hydrography",
            )
        )

    if panels_cfg.timeseries_discharge:
        obs_df = _records_to_timeseries_df(
            _filter_discharge_records(ld.hydrometry),
        )
        paths.append(
            _render_panel(
                output_dir / "timeseries_discharge.png",
                figsize=(10, 4),
                render_fn=render_timeseries_multi,
                df=obs_df,
                ylabel="Discharge",
                unit="m³/s",
                title=f"{title} - Observed discharge",
                date_start=date_start,
                date_end=date_end,
            )
        )

    if panels_cfg.timeseries_piezometry:
        piezo_records = ld.piezometry.points if ld.piezometry else None
        obs_df = _records_to_timeseries_df(piezo_records)
        piezo_hlines = _piezo_altitude_hlines(piezo_records)
        paths.append(
            _render_panel(
                output_dir / "timeseries_piezometry.png",
                figsize=(10, 4),
                render_fn=render_timeseries_multi,
                df=obs_df,
                ylabel="Piezometric level",
                unit="m",
                title=f"{title} - Piezometry",
                date_start=date_start,
                date_end=date_end,
                hlines=piezo_hlines,
            )
        )

    if panels_cfg.timeseries_intermittency:
        onde_records = ld.intermittency.points if ld.intermittency else None
        onde_df = _records_to_timeseries_df(onde_records)
        paths.append(
            _render_panel(
                output_dir / "timeseries_intermittency.png",
                figsize=(10, 4),
                render_fn=render_intermittency,
                df=onde_df,
                title=f"{title} - ONDE flow state",
                date_start=date_start,
                date_end=date_end,
            )
        )

    if panels_cfg.timeseries_water_quality:
        wq_records = ld.water_quality.points if ld.water_quality else None
        series_by_param = _wq_series_by_parameter(wq_records)
        paths.append(
            _render_panel(
                output_dir / "timeseries_water_quality.png",
                figsize=(10, 4),
                render_fn=render_water_quality,
                series_by_param=series_by_param,
                title=f"{title} - Water quality",
                date_start=date_start,
                date_end=date_end,
            )
        )

    if panels_cfg.climatic_summary:
        monthly_precip = _monthly_mean_from_result(ld.precipitation)
        monthly_etp = _monthly_mean_from_result(ld.etp)
        paths.append(
            _render_panel(
                output_dir / "climatic_summary.png",
                figsize=(8, 4),
                render_fn=render_climatic_summary,
                monthly_precip=monthly_precip,
                monthly_etp=monthly_etp,
                title=f"{title} - Monthly climatology",
            )
        )

    if panels_cfg.stats_card:
        paths.append(
            _render_panel(
                output_dir / "stats_card.png",
                figsize=(6, 5),
                render_fn=render_stats_card,
                summary=summary,
            )
        )

    if panels_cfg.station_inventory:
        inventory = _build_station_inventory(state)
        paths.append(
            _render_panel(
                output_dir / "station_inventory.png",
                figsize=(10, max(3, 0.35 * len(inventory) + 1)),
                render_fn=render_station_inventory,
                inventory=inventory,
            )
        )

    logger.info("[overview] Generated %d panel(s) in %s", len(paths), output_dir)
    return paths


# ---------------------------------------------------------------------------
# Helpers - output dir, figure plumbing
# ---------------------------------------------------------------------------


def _resolve_output_dir(state: DataOverviewState) -> Path:
    """Return the overview figures output directory."""
    if state.workspace is not None and hasattr(state.workspace, "paths"):
        return state.workspace.paths.figures_folder / "overview"
    if state.workspace is not None:
        return Path(getattr(state.workspace, "figure_folder", "figures")) / "overview"
    return Path("overview_report")


def _render_panel(save_path: Path, *, figsize: tuple[float, float], render_fn, **kwargs) -> Path:
    """Create a figure, call the render function, save, close."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize, dpi=200, constrained_layout=True)
    try:
        render_fn(ax, **kwargs)
        fig.savefig(save_path, dpi=200, bbox_inches="tight")
    finally:
        plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# Helpers - domain-to-generic conversions
# ---------------------------------------------------------------------------


def _load_streams_gdf(hydrography):
    if hydrography is None:
        return None
    streams_path = getattr(hydrography, "streams", None)
    if streams_path is None:
        return None
    try:
        import geopandas as gpd

        return gpd.read_file(streams_path)
    except Exception:
        return None


def _load_geology_gdf(geology):
    """Try to load a geology GeoDataFrame from the field's source, if available."""
    # GeologyField typically carries encoded raster rather than a GeoDataFrame;
    # try a couple of common attributes that may point back to the vector source.
    for attr in ("geol_file", "source_path", "vector_source"):
        path = getattr(geology, attr, None)
        if path:
            try:
                import geopandas as gpd

                return gpd.read_file(str(path))
            except Exception:
                continue
    return None


def _filter_discharge_records(hydrometry_lr) -> list | None:
    if hydrometry_lr is None:
        return None
    discharge = [r for r in hydrometry_lr.points if r.variable in ("discharge", "streamflow")]
    return discharge or None


def _records_to_timeseries_df(records):
    """Convert a list of PointRecord to a wide DataFrame (index=datetime, cols=station_id)."""
    if not records:
        return None
    import pandas as pd

    frames: dict[str, Any] = {}
    for rec in records:
        if rec.data is None or rec.data.empty:
            continue
        df = rec.data.copy().set_index("datetime").sort_index()
        if "value" not in df.columns:
            continue
        frames[rec.station_id] = df["value"]
    return pd.DataFrame(frames) if frames else None


def _piezo_altitude_hlines(records) -> list[dict] | None:
    """Build horizontal-line specs for the piezometer surface altitudes.

    Hub'Eau exposes ``altitude_station`` (ground level in metres NGF) in the
    station metadata, attached to ``location.metadata['altitude']``. We turn
    that into one dashed reference line per station so the piezometric chart
    immediately shows the depth of the watertable below the surface.
    """
    if not records:
        return None
    palette = ["darkred", "saddlebrown", "darkolivegreen", "indigo"]
    hlines: list[dict] = []
    for idx, rec in enumerate(records):
        loc = rec.location
        if loc is None:
            continue
        altitude = loc.metadata.get("altitude") if isinstance(loc.metadata, dict) else None
        if altitude is None:
            continue
        try:
            alt_value = float(altitude)
        except (TypeError, ValueError):
            continue
        hlines.append(
            {
                "y": alt_value,
                "label": f"{rec.station_id} ground ({alt_value:.1f} m)",
                "color": palette[idx % len(palette)],
                "linestyle": "--",
            }
        )
    return hlines or None


def _wq_series_by_parameter(records) -> dict:
    """Group water-quality PointRecords by parameter -> {station_id: Series}."""
    if not records:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.data is None or rec.data.empty:
            continue
        df = rec.data.copy().set_index("datetime").sort_index()
        if "value" not in df.columns:
            continue
        param = str(rec.variable or "value")
        out.setdefault(param, {})[rec.station_id] = df["value"]
    out = {k: v for k, v in out.items() if v}
    return out


def _monthly_mean_from_result(lr) -> np.ndarray | None:
    """Return a 12-element array with mean monthly values across all stations / fields."""
    if lr is None:
        return None
    if getattr(lr, "has_points", False):
        monthly = _monthly_mean_from_points(lr.points)
        if monthly is not None:
            return monthly
    if getattr(lr, "has_fields", False):
        return _monthly_mean_from_fields(lr.fields)
    return None


def _monthly_mean_from_points(records) -> np.ndarray | None:
    import pandas as pd

    monthly_vals: list[pd.Series] = []
    for rec in records:
        if rec.data is None or rec.data.empty:
            continue
        df = rec.data.copy().set_index("datetime").sort_index()
        if "value" not in df.columns:
            continue
        monthly = df["value"].groupby(df.index.month).mean()
        monthly_vals.append(monthly)
    if not monthly_vals:
        return None
    joined = pd.concat(monthly_vals, axis=1).mean(axis=1)
    out = np.full(12, np.nan, dtype=float)
    for month, val in joined.items():
        if 1 <= int(month) <= 12:
            out[int(month) - 1] = float(val)
    return None if np.all(np.isnan(out)) else out


def _monthly_mean_from_fields(fields) -> np.ndarray | None:
    """Compute monthly climatology averaged over space for xarray-backed fields."""
    try:
        import xarray as xr  # noqa: F401
    except ImportError:
        return None

    out = np.full(12, np.nan, dtype=float)
    samples = np.zeros(12, dtype=int)
    for rec in fields:
        try:
            ds = rec.dataset
        except Exception:
            continue
        data_var = _pick_first_data_var(ds)
        if data_var is None:
            continue
        da = ds[data_var]
        time_dim = _pick_time_dim(da)
        if time_dim is None:
            continue
        spatial_dims = [d for d in da.dims if d != time_dim]
        if spatial_dims:
            da = da.mean(dim=spatial_dims, skipna=True)
        try:
            monthly = da.groupby(f"{time_dim}.month").mean().to_pandas()
        except Exception:
            continue
        for month, val in monthly.items():
            idx = int(month) - 1
            if 0 <= idx < 12 and not np.isnan(float(val)):
                if samples[idx] == 0:
                    out[idx] = float(val)
                else:
                    out[idx] = (out[idx] * samples[idx] + float(val)) / (samples[idx] + 1)
                samples[idx] += 1
    return None if np.all(np.isnan(out)) else out


def _pick_first_data_var(ds) -> str | None:
    for name in ("value", "precipitation", "precip", "etp", "pet"):
        if name in ds.data_vars:
            return name
    data_vars = list(ds.data_vars)
    return data_vars[0] if data_vars else None


def _pick_time_dim(da) -> str | None:
    for candidate in ("time", "date", "datetime", "t"):
        if candidate in da.dims:
            return candidate
    return None


def _build_station_points(ld) -> list[dict] | None:
    """Convert PointRecord station locations to generic dicts for map overlays."""
    points: list[dict] = []
    configs = [
        ("hydrometry", "o", "white", "Hydrometry"),
        ("piezometry", "^", "skyblue", "Piezometry"),
        ("intermittency", "s", "lightgrey", "Intermittency"),
        ("water_quality", "D", "khaki", "Water quality"),
    ]
    for attr, marker, color, group in configs:
        lr = getattr(ld, attr, None)
        if lr is None:
            continue
        for rec in lr.points:
            loc = rec.location
            if loc is None or loc.x is None or loc.y is None:
                continue
            points.append(
                {
                    "x": float(loc.x),
                    "y": float(loc.y),
                    "crs": loc.crs,
                    "label": rec.station_id,
                    "marker": marker,
                    "color": color,
                    "group": group,
                }
            )
    return points or None


def _build_station_inventory(state: DataOverviewState) -> list[dict[str, Any]]:
    """Build a flat list of station dicts for the inventory table.

    Stations are deduped by ``(type, station_id)`` so that variables like
    water_quality - which emit one PointRecord per (station, parameter) -
    don't blow up the inventory into thousands of rows. Period is the
    union of all per-parameter records for that station.
    """
    ld = state.loaded_data
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for label, attr in [
        ("Hydrometry", "hydrometry"),
        ("Piezometry", "piezometry"),
        ("Intermittency", "intermittency"),
        ("Water quality", "water_quality"),
    ]:
        lr = getattr(ld, attr, None)
        if lr is None:
            continue
        for rec in lr.points:
            key = (label, rec.station_id)
            loc = rec.location
            start = str(rec.date_start.date()) if rec.date_start else ""
            end = str(rec.date_end.date()) if rec.date_end else ""
            if key not in seen:
                seen[key] = {
                    "type": label,
                    "id": rec.station_id,
                    "x": loc.x if loc else 0.0,
                    "y": loc.y if loc else 0.0,
                    "start": start,
                    "end": end,
                }
                continue
            existing = seen[key]
            if start and (not existing["start"] or start < existing["start"]):
                existing["start"] = start
            if end and (not existing["end"] or end > existing["end"]):
                existing["end"] = end
    return list(seen.values())
