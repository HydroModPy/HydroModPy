"""Orchestrate PNG generation for the data-overview report.

Each enabled panel produces one standalone PNG file in the overview output
directory.  Panel rendering is delegated to the generic functions in
:mod:`hydromodpy.analysis.display.figures`.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.launchers.data_overview import DataOverviewState


def generate_overview_report(state: DataOverviewState) -> list[Path]:
    """Generate individual PNGs for each enabled panel.

    Returns the list of created file paths.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from hydromodpy.analysis.display.figures.maps import (
        render_dem_map,
        render_geology_map,
        render_hydrography_map,
    )
    from hydromodpy.analysis.display.figures.tables import (
        render_stats_card,
        render_station_inventory,
    )
    from hydromodpy.analysis.display.figures.timeseries import (
        _monthly_mean_from_fields,
        _monthly_mean_from_records,
        render_climatic_summary,
        render_discharge,
        render_intermittency,
        render_piezometry,
        render_water_quality,
    )
    from hydromodpy.analysis.display.report.summary import compute_overview_summary

    panels_cfg = state.cfg.overview.panels
    output_dir = _resolve_output_dir(state)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    summary = compute_overview_summary(state)

    ld = state.loaded_data
    dg = state.domain_geographic
    dem_path = dg.watershed_box_buff_dem if dg else None
    watershed_shp = dg.watershed_shp if dg else None
    title = summary.watershed_name

    # ---- Map panels -------------------------------------------------------
    if panels_cfg.map_dem and dem_path and watershed_shp:
        # Convert domain objects to generic types
        streams_gdf = _load_streams_gdf(ld.hydrography)
        station_points = _build_station_points(ld)
        path = _render_panel(
            output_dir / "map_dem.png",
            figsize=(6, 6),
            render_fn=render_dem_map,
            dem_path=dem_path,
            watershed_shp=watershed_shp,
            streams_gdf=streams_gdf,
            station_points=station_points,
            title=title,
        )
        paths.append(path)

    if panels_cfg.map_geology and dem_path and watershed_shp and ld.geology is not None:
        streams_gdf = _load_streams_gdf(ld.hydrography)
        geology_rgba, geology_bounds, legend_entries = _prepare_geology(ld.geology)
        geology_gdf = _load_geology_gdf(ld.geology) if geology_rgba is None else None
        path = _render_panel(
            output_dir / "map_geology.png",
            figsize=(6, 6),
            render_fn=render_geology_map,
            dem_path=dem_path,
            watershed_shp=watershed_shp,
            geology_rgba=geology_rgba,
            geology_bounds=geology_bounds,
            geology_gdf=geology_gdf,
            legend_entries=legend_entries,
            streams_gdf=streams_gdf,
            title=f"{title} \u2014 Geology",
        )
        paths.append(path)

    if panels_cfg.map_hydrography and dem_path and watershed_shp:
        streams_gdf = _load_streams_gdf(ld.hydrography)
        outlet_xy = None
        if dg and dg.x_outlet is not None and dg.y_outlet is not None:
            outlet_xy = (dg.x_outlet, dg.y_outlet)
        path = _render_panel(
            output_dir / "map_hydrography.png",
            figsize=(6, 6),
            render_fn=render_hydrography_map,
            dem_path=dem_path,
            watershed_shp=watershed_shp,
            streams_gdf=streams_gdf,
            outlet_xy=outlet_xy,
            title=f"{title} \u2014 Hydrography",
        )
        paths.append(path)

    # ---- Time series panels -----------------------------------------------
    if panels_cfg.timeseries_discharge:
        discharge_records = _filter_discharge_records(ld.hydrometry)
        obs_df = _records_to_discharge_df(discharge_records)
        path = _render_panel(
            output_dir / "timeseries_discharge.png",
            figsize=(10, 4),
            render_fn=render_discharge,
            observed_df=obs_df,
        )
        paths.append(path)

    if panels_cfg.timeseries_piezometry:
        piezo_records = ld.piezometry.points if ld.piezometry else None
        obs_df = _records_to_piezometry_df(piezo_records)
        path = _render_panel(
            output_dir / "timeseries_piezometry.png",
            figsize=(10, 4),
            render_fn=render_piezometry,
            observed_df=obs_df,
        )
        paths.append(path)

    if panels_cfg.climatic_summary:
        precip_records = ld.precipitation.points if ld.precipitation and ld.precipitation.has_points else None
        etp_records = ld.etp.points if ld.etp and ld.etp.has_points else None
        monthly_precip = _monthly_mean_from_records(precip_records) if precip_records else None
        if monthly_precip is None and ld.precipitation is not None:
            monthly_precip = _monthly_mean_from_fields(ld.precipitation)
        monthly_etp = _monthly_mean_from_records(etp_records) if etp_records else None
        if monthly_etp is None and ld.etp is not None:
            monthly_etp = _monthly_mean_from_fields(ld.etp)
        path = _render_panel(
            output_dir / "climatic_summary.png",
            figsize=(8, 4),
            render_fn=render_climatic_summary,
            monthly_precip=monthly_precip,
            monthly_etp=monthly_etp,
        )
        paths.append(path)

    if panels_cfg.timeseries_intermittency:
        intermittency_records = (
            ld.intermittency.points
            if ld.intermittency and ld.intermittency.has_points
            else None
        )
        records_df = _records_to_intermittency_df(intermittency_records)
        path = _render_intermittency_panel(
            output_dir / "timeseries_intermittency.png",
            records_df=records_df,
        )
        paths.append(path)

    if panels_cfg.timeseries_water_quality:
        wq_records = (
            ld.water_quality.points
            if ld.water_quality and ld.water_quality.has_points
            else None
        )
        records_df = _records_to_water_quality_df(wq_records)
        path = _render_panel(
            output_dir / "timeseries_water_quality.png",
            figsize=(10, 4),
            render_fn=render_water_quality,
            records_df=records_df,
        )
        paths.append(path)

    # ---- Stats panels -----------------------------------------------------
    if panels_cfg.stats_card:
        path = _render_panel(
            output_dir / "stats_card.png",
            figsize=(6, 5),
            render_fn=render_stats_card,
            summary=summary,
        )
        paths.append(path)

    if panels_cfg.station_inventory:
        inventory = _build_station_inventory(state)
        path = _render_panel(
            output_dir / "station_inventory.png",
            figsize=(10, max(3, 0.4 * len(inventory) + 1)),
            render_fn=render_station_inventory,
            inventory=inventory,
        )
        paths.append(path)

    return paths


# ---------------------------------------------------------------------------
# Helpers — output dir & panel rendering
# ---------------------------------------------------------------------------

def _resolve_output_dir(state: DataOverviewState) -> Path:
    """Return the overview figures output directory."""
    if state.workspace is not None and hasattr(state.workspace, "paths"):
        return state.workspace.paths.figures_folder / "overview"
    if state.workspace is not None:
        return Path(state.workspace.figure_folder) / "overview"
    return Path("overview_report")


def _render_panel(
    save_path: Path,
    *,
    figsize: tuple[float, float],
    render_fn,
    **kwargs,
) -> Path:
    """Create a figure, call the render function, save, close."""
    import matplotlib.pyplot as plt

    from hydromodpy.analysis.display.common import _single_axes, make_figure

    fig, axs = make_figure(figsize=figsize, dpi=300)
    ax = _single_axes(axs)
    try:
        render_fn(ax, **kwargs)
        fig.tight_layout()
        fig.savefig(str(save_path), dpi=300, bbox_inches="tight", transparent=False)
    finally:
        plt.close(fig)
    return save_path


def _render_intermittency_panel(
    save_path: Path,
    *,
    records_df: "Any" = None,
) -> Path:
    """Create compact multi-subplot intermittency figure."""
    import matplotlib.pyplot as plt
    import numpy as np

    from hydromodpy.analysis.display.common import make_figure
    from hydromodpy.analysis.display.figures.timeseries import (
        _intermittency_legend_handles,
        render_intermittency,
    )

    n_stations = (
        records_df["station_id"].nunique()
        if records_df is not None and not records_df.empty
        else 1
    )
    figsize = (7, max(1.6, 1.6 * n_stations + 0.4))
    fig, axs = make_figure(
        nrows=max(1, n_stations), ncols=1, figsize=figsize, dpi=300,
        sharex=3, hspace=2.0,
    )

    try:
        axes_flat = list(np.asarray(axs).flat) if n_stations > 1 else [axs]
        if records_df is None or records_df.empty:
            for a in axes_flat:
                render_intermittency(a, records_df=records_df)
        else:
            stations = list(records_df["station_id"].unique())
            for ax, sid in zip(axes_flat, stations):
                render_intermittency(ax, records_df=records_df, station_id=sid)

        fig.legend(
            handles=_intermittency_legend_handles(),
            loc="bottom", ncol=5, fontsize=7,
            frameon=False, handletextpad=0.3, columnspacing=1.0,
        )
        fig.savefig(str(save_path), dpi=300, bbox_inches="tight", transparent=False)
    finally:
        plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# Helpers — domain-to-generic conversions
# ---------------------------------------------------------------------------

def _load_streams_gdf(hydrography):
    """Load streams GeoDataFrame from a HydrographyResult."""
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


def _build_station_points(ld) -> list[dict] | None:
    """Convert PointRecord station locations to generic dicts."""
    points: list[dict] = []

    # Piezometry
    piezo = ld.piezometry
    if piezo:
        for rec in piezo.points:
            if rec.location is not None:
                points.append({
                    "x": rec.location.x, "y": rec.location.y,
                    "label": rec.station_id,
                    "marker": "^", "color": "blue", "group": "Piezometers",
                })

    # Hydrometry
    hydro = ld.hydrometry
    if hydro:
        for rec in hydro.points:
            if rec.location is not None:
                points.append({
                    "x": rec.location.x, "y": rec.location.y,
                    "label": rec.station_id,
                    "marker": "o", "color": "white", "group": "Hydrometric stations",
                })

    # Intermittency
    intm = ld.intermittency
    if intm and intm.has_points:
        for rec in intm.points:
            if rec.location is not None:
                points.append({
                    "x": rec.location.x, "y": rec.location.y,
                    "label": rec.station_id,
                    "marker": "s", "color": "grey", "group": "Intermittency",
                })

    return points or None


def _prepare_geology(geology) -> tuple[np.ndarray | None, tuple | None, list[dict] | None]:
    """Convert a geology object to RGBA array + bounds + legend entries.

    Returns ``(None, None, None)`` when the object has no encoded raster.
    """
    import matplotlib.colors as mcolors

    encoded = getattr(geology, "encoded_codes", None)
    encoded_to_zone = getattr(geology, "encoded_to_zone", None)
    geol_transform = getattr(geology, "transform", None)

    if encoded is None or not encoded_to_zone or geol_transform is None:
        return None, None, None

    from rasterio.transform import array_bounds

    zone_ids = sorted(encoded_to_zone.keys())
    base_colors = [
        "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
        "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
        "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
        "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    ]
    zone_colors = {zid: base_colors[i % len(base_colors)] for i, zid in enumerate(zone_ids)}

    rgba = np.zeros((*encoded.shape, 4), dtype=np.float32)
    for zid, color in zone_colors.items():
        mask = encoded == zid
        rgb = mcolors.to_rgba(color)
        for c in range(4):
            rgba[mask, c] = rgb[c]
    rgba[..., 3] = np.where(encoded > 0, 0.55, 0.0)

    geol_bounds = array_bounds(encoded.shape[0], encoded.shape[1], geol_transform)

    legend_entries = [
        {"label": str(encoded_to_zone[zid]).upper(), "color": zone_colors[zid], "alpha": 0.55}
        for zid in zone_ids
    ]
    return rgba, geol_bounds, legend_entries


def _load_geology_gdf(geology):
    """Load a geology GeoDataFrame from the legacy geol_file path."""
    geol_path = getattr(geology, "geol_file", None)
    if geol_path is None:
        return None
    try:
        import geopandas as gpd
        return gpd.read_file(geol_path)
    except Exception:
        return None


def _filter_discharge_records(hydrometry_lr) -> list | None:
    """Extract discharge-type PointRecords from a hydrometry LoadResult."""
    if hydrometry_lr is None:
        return None
    records = []
    for r in hydrometry_lr.points:
        if r.variable in ("discharge", "streamflow"):
            records.append(r)
    return records or None


def _records_to_discharge_df(records) -> "Any":
    """Convert PointRecords to a DataFrame suitable for render_discharge."""
    if not records:
        return None
    import pandas as pd

    frames = {}
    for rec in records:
        df = rec.data.copy().set_index("datetime").sort_index()
        frames[rec.station_id] = df["value"]
    return pd.DataFrame(frames) if frames else None


def _records_to_piezometry_df(records) -> "Any":
    """Convert PointRecords to a DataFrame suitable for render_piezometry."""
    if not records:
        return None
    import pandas as pd

    frames = {}
    for rec in records:
        df = rec.data.copy().set_index("datetime").sort_index()
        frames[rec.station_id] = df["value"]
    return pd.DataFrame(frames) if frames else None


def _records_to_intermittency_df(records) -> "Any":
    """Convert PointRecords to a flat DataFrame [datetime, station_id, value]."""
    if not records:
        return None
    import pandas as pd

    rows = []
    for rec in records:
        df = rec.data.copy()
        df = df[["datetime", "value"]].copy()
        df["station_id"] = rec.station_id
        rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else None


def _records_to_water_quality_df(records) -> "Any":
    """Convert PointRecords to [datetime, variable, value, unit, source_unit]."""
    if not records:
        return None
    import pandas as pd

    rows = []
    for rec in records:
        df = rec.data.copy()
        df = df[["datetime", "value"]].copy()
        df["variable"] = rec.variable
        df["unit"] = rec.unit or ""
        df["source_unit"] = rec.source_unit or ""
        rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else None


def _build_station_inventory(state: DataOverviewState) -> list[dict[str, Any]]:
    """Build a flat list of station dicts for the inventory table."""
    inventory: list[dict[str, Any]] = []
    ld = state.loaded_data

    for var_name, attr_name in [
        ("Hydrometry", "hydrometry"),
        ("Piezometry", "piezometry"),
        ("Intermittency", "intermittency"),
    ]:
        lr = getattr(ld, attr_name, None)
        if lr is None:
            continue
        for rec in lr.points:
            loc = rec.location
            inventory.append({
                "type": var_name,
                "id": rec.station_id,
                "x": loc.x if loc else 0,
                "y": loc.y if loc else 0,
                "start": str(rec.date_start.date()) if rec.date_start else "",
                "end": str(rec.date_end.date()) if rec.date_end else "",
            })
    return inventory
