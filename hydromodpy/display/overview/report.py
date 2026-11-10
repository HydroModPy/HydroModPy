"""Orchestrate artifact generation for the data-overview report.

The report produces canonical block figures, legacy panel PNGs and a static
HTML page under the workspace output root.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.display.overview.location import (
    overview_figures_dir,
    overview_run_dir_of,
    review_pages_enabled,
)
from hydromodpy.display.overview.panels import (
    render_climatic_summary,
    render_dem_map,
    render_geology_map,
    render_hydrography_map,
    render_intermittency,
    render_regional_context_map,
    render_station_inventory,
    render_stats_card,
    render_timeseries_multi,
    render_water_quality,
)
from hydromodpy.display.overview.summary import (
    compute_overview_summary,
    hydrography_vector_path,
    outlet_xy,
    regional_context_title,
    station_inventory,
)
from hydromodpy.display.overview.web import (
    write_overview_review_web_reports,
    write_overview_web_report,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from hydromodpy.core.contracts.overview import DataOverviewState


def generate_overview_report(state: DataOverviewState) -> list[Path]:
    """Generate overview report artifacts and return their paths."""
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
    title = summary.watershed_name or "Catchment"
    overview_cfg = state.cfg.overview
    regional_dem_path = _regional_dem_path(state, dg, fallback=dem_path)
    regional_title = regional_context_title(
        getattr(overview_cfg, "regional_context_label", None), (regional_dem_path,)
    )
    date_start = getattr(overview_cfg, "date_start", None)
    date_end = getattr(overview_cfg, "date_end", None)

    paths: list[Path] = []
    station_points = _build_station_points(ld)

    if regional_dem_path and watershed_shp:
        paths.append(
            _render_panel(
                output_dir / "map_regional_context.png",
                figsize=(8, 6.4),
                render_fn=render_regional_context_map,
                regional_dem_path=str(regional_dem_path),
                watershed_shp=str(watershed_shp),
                streams_gdf=None,
                station_points=station_points,
                outlet_xy=outlet_xy(dg),
                title=regional_title,
            )
        )

    if panels_cfg.map_dem and dem_path:
        paths.append(
            _render_panel(
                output_dir / "map_dem.png",
                figsize=(7, 6),
                render_fn=render_dem_map,
                dem_path=str(dem_path),
                watershed_shp=str(watershed_shp) if watershed_shp else None,
                streams_gdf=streams_gdf,
                station_points=station_points,
                outlet_xy=outlet_xy(dg),
                relative_ticks=True,
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
                relative_ticks=True,
                title="Catchment geology",
            )
        )

    if panels_cfg.map_hydrography and dem_path:
        paths.append(
            _render_panel(
                output_dir / "map_hydrography.png",
                figsize=(7, 6),
                render_fn=render_hydrography_map,
                dem_path=str(dem_path),
                watershed_shp=str(watershed_shp) if watershed_shp else None,
                streams_gdf=streams_gdf,
                outlet_xy=outlet_xy(dg),
                relative_ticks=True,
                stream_label="BD Topage",
                title="BD Topage hydrographic network",
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
        n_rows = 1 if onde_df is None else len(onde_df.columns)
        paths.append(
            _render_panel(
                output_dir / "timeseries_intermittency.png",
                figsize=(9, 0.9 + 1.9 * n_rows),
                render_fn=render_intermittency,
                df=onde_df,
                title=f"{title} - ONDE flow state",
                date_start=date_start,
                date_end=date_end,
                station_names=_station_names(onde_records, "station_name"),
            )
        )

    if panels_cfg.timeseries_water_quality:
        wq_records = ld.water_quality.points if ld.water_quality else None
        series_by_param = _wq_series_by_parameter(wq_records)
        paths.append(
            _render_panel(
                output_dir / "timeseries_water_quality.png",
                figsize=(10, 0.9 + 2.6 * max(1, len(series_by_param))),
                render_fn=render_water_quality,
                series_by_param=series_by_param,
                title=f"{title} - Water quality",
                date_start=date_start,
                date_end=date_end,
                units={str(r.variable): r.unit for r in wq_records or () if r.unit},
                station_names=_station_names(wq_records, "name"),
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
        inventory = station_inventory(state)
        paths.append(
            _render_panel(
                output_dir / "station_inventory.png",
                figsize=(10, max(3, 0.35 * len(inventory) + 1)),
                render_fn=render_station_inventory,
                inventory=inventory,
            )
        )

    write_overview_web_report(state, figure_paths=paths)
    if review_pages_enabled():
        write_overview_review_web_reports(state, figure_paths=paths)

    logger.info("[overview] Generated %d panel artifact(s) in %s", len(paths), output_dir)
    return paths


# ---------------------------------------------------------------------------
# Helpers - output dir, figure plumbing
# ---------------------------------------------------------------------------


def _resolve_output_dir(state: DataOverviewState) -> Path:
    """Return the panels folder of the overview: ``runs/<overview>/figures/``."""
    return overview_figures_dir(overview_run_dir_of(state))


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


def _regional_dem_path(state: DataOverviewState, dg, *, fallback) -> Path | None:
    dem_source_path = None
    dem_cfg = getattr(getattr(state.cfg, "data", None), "dem", None)
    if dem_cfg and getattr(dem_cfg, "sources", None):
        first = dem_cfg.sources[0]
        dem_source_path = getattr(first, "path", None)
    candidates = [
        getattr(dg, "regional_dem_path", None) if dg else None,
        getattr(state, "dem_path", None),
        getattr(getattr(state, "geographic", None), "dem_path", None),
        dem_source_path,
        getattr(getattr(state.cfg, "geographic", None), "dem_init_path", None),
        fallback,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------------------
# Helpers - domain-to-generic conversions
# ---------------------------------------------------------------------------


def _load_streams_gdf(hydrography):
    if hydrography is None:
        return None
    streams_path = hydrography_vector_path(hydrography)
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

    Hub'Eau exposes ``altitude_station`` (ground level in meters NGF) in the
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


def _station_names(records, key: str) -> dict[str, str]:
    """Map station_id to the station name held under ``key`` in its location."""
    names: dict[str, str] = {}
    for rec in records or ():
        name = (getattr(rec.location, "metadata", None) or {}).get(key)
        if name:
            names[rec.station_id] = str(name)
    return names


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
