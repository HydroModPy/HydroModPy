"""Panel rendering functions for the overview report.

Each ``render_*`` function takes a matplotlib ``Axes``, the theme and the data it needs
already converted to generic types (paths, DataFrames, GeoDataFrames). This
keeps the rendering decoupled from any state dataclass.

This is the one part of ``display`` that reads raw files (rasters and shapefiles named
by the state), because no run exists yet. A panel that misses its data draws an explicit
empty state rather than failing.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.axes import Axes

from hydromodpy.display import static
from hydromodpy.display.overview.summary import OverviewSummary
from hydromodpy.display.theme import Theme

# ---------------------------------------------------------------------------
# Map panels
# ---------------------------------------------------------------------------


def render_dem_map(
    ax: Axes,
    *,
    theme: Theme,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    outlet_xy: tuple[float, float] | None = None,
    stream_label: str = "Network",
    title: str = "",
) -> Axes:
    """Render a DEM raster with optional watershed outline, outlet and stations."""
    extent, crs = _draw_relief(ax, theme, dem_path)
    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp, theme)
        _proxy(ax, theme, "outline", "Catchment")
    if streams_gdf is not None and not streams_gdf.empty:
        streams_gdf.plot(ax=ax, color=theme.roles["network_on_relief"], linewidth=0.8)
        if stream_label:
            _proxy(ax, theme, "network_on_relief", stream_label)
    if station_points:
        _plot_station_points(ax, theme, station_points, target_crs=crs, extent=extent)
    _draw_outlet(ax, theme, outlet_xy, "Outlet")
    return _finish_map(ax, theme, extent, crs, title or "DEM")


def render_regional_context_map(
    ax: Axes,
    *,
    theme: Theme,
    regional_dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
) -> Axes:
    """Render a regional DEM context with the watershed footprint and stations."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    watershed_gdf = _read_watershed_gdf(watershed_shp)
    with rasterio.open(regional_dem_path) as src:
        raster_crs = src.crs
        if watershed_gdf is not None and raster_crs is not None:
            watershed_gdf = _to_crs_safely(watershed_gdf, raster_crs)
        bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        window = from_bounds(*bounds, transform=src.transform)
        height = max(1, int(round(window.height)))
        width = max(1, int(round(window.width)))
        scale = min(1.0, 1000.0 / max(height, width))
        out_shape = (max(1, int(height * scale)), max(1, int(width * scale)))
        data = src.read(
            1,
            window=window,
            masked=True,
            out_shape=out_shape,
            resampling=Resampling.bilinear,
        )

    extent = (bounds[0], bounds[2], bounds[1], bounds[3])
    _relief(ax, theme, data, extent)
    _proxy(ax, theme, "outline", "Catchment")
    if watershed_gdf is not None and not watershed_gdf.empty:
        watershed_gdf.boundary.plot(
            ax=ax, color=theme.roles["outline"], linewidth=theme.data_line_width, zorder=6
        )
    if streams_gdf is not None and not streams_gdf.empty:
        streams_gdf = _to_crs_safely(streams_gdf, raster_crs)
        streams_gdf.plot(ax=ax, color=theme.roles["network_on_relief"], linewidth=0.85, zorder=7)
        _proxy(ax, theme, "network_on_relief", "Observed network")
    _draw_outlet(ax, theme, outlet_xy, "Site")
    if station_points:
        _plot_station_points(ax, theme, station_points, target_crs=raster_crs, extent=extent)
    return _finish_map(ax, theme, extent, raster_crs, title or "Regional setting")


def render_hydrography_map(
    ax: Axes,
    *,
    theme: Theme,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    outlet_xy: tuple[float, float] | None = None,
    stream_label: str = "Hydrographic network",
    title: str = "",
) -> Axes:
    """Render a hydrography map: relief background, streams, outlet."""
    return render_dem_map(
        ax,
        theme=theme,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        streams_gdf=streams_gdf,
        outlet_xy=outlet_xy,
        stream_label=stream_label,
        title=title or "Hydrography",
    )


def render_geology_map(
    ax: Axes,
    *,
    theme: Theme,
    dem_path: str,
    watershed_shp: str | None = None,
    geology_gdf=None,
    title: str = "",
) -> Axes:
    """Render a lithology map from a geology GeoDataFrame clipped to the bbox."""
    from matplotlib.patches import Patch

    extent, crs = _draw_relief(ax, theme, dem_path)
    if geology_gdf is not None and not geology_gdf.empty:
        field = _pick_field(geology_gdf, ("CODE_LEG", "code_leg", "litho", "LITHO", "LITH"))
        if field is None:
            geology_gdf.plot(ax=ax, alpha=0.5, edgecolor="none")
        else:
            codes = sorted(geology_gdf[field].dropna().astype(str).unique())
            colors = theme.class_colors(len(codes))
            handles = []
            for i, code in enumerate(codes):
                color = colors[i]
                rows = geology_gdf[geology_gdf[field].astype(str) == code]
                rows.plot(ax=ax, color=color, alpha=0.55, edgecolor="none")
                handles.append(Patch(facecolor=color, alpha=0.55, label=code))
            legend = ax.figure.legend(
                handles=handles,
                loc="outside center right",
                title="\n".join(filter(None, (field, theme.sharing_note(len(codes))))),
                ncols=1 + len(handles) // 25,
                frameon=False,
                prop={"family": theme.family, "size": theme.small},
            )
            for text in legend.get_texts() + [legend.get_title()]:
                text.set(family=theme.family, size=theme.small, color=theme.ink)
    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp, theme)
    return _finish_map(ax, theme, extent, crs, title or "Geology", legend=False)


# ---------------------------------------------------------------------------
# Time-series panels
# ---------------------------------------------------------------------------


def render_timeseries_multi(
    ax: Axes,
    *,
    theme: Theme,
    df,
    ylabel: str,
    title: str,
    unit: str = "",
    date_start=None,
    date_end=None,
    hlines: list[dict] | None = None,
) -> Axes:
    """Render a multi-station time series panel (one line per column).

    Parameters
    ----------
    date_start, date_end
        Optional bounds applied via :meth:`Axes.set_xlim` so the panel honors
        the requested time window even when the underlying records span a
        wider period.
    hlines
        Optional list of horizontal reference lines, each described by a dict
        with keys ``y`` (float), ``label`` (str), and optional ``color`` /
        ``linestyle``. Used to overlay e.g. the piezometer surface altitude.
    """
    ax.set_title(title)
    if df is None or df.empty:
        return _no_records(ax, theme)

    colors = theme.class_colors(len(df.columns))
    plotted = 0
    for station in df.columns:
        serie = df[station].dropna()
        if serie.empty:
            continue
        ax.plot(
            serie.index,
            serie.values,
            color=colors[plotted],
            linewidth=theme.data_line_width,
            label=station,
        )
        plotted += 1

    for line in hlines or ():
        y = line.get("y")
        if y is None:
            continue
        ax.axhline(
            float(y),
            color=line.get("color", theme.roles["observed"]),
            linestyle=line.get("linestyle", "--"),
            linewidth=theme.data_line_width,
            label=line.get("label"),
        )

    if date_start is not None or date_end is not None:
        import pandas as pd

        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)

    ax.set_ylabel(f"{ylabel} ({unit})" if unit else ylabel)
    static.style_axes(ax, theme, dates=True)
    legend_entries = plotted + (len(hlines) if hlines else 0)
    if 0 < legend_entries <= 12:
        static.legend(ax, theme)
    if plotted == 0:
        static.note(ax, "No valid records", theme)
    return ax


# ONDE flow states, 1 = dry to 5 = visible flow, colored as in HydroModPy v1.
_ONDE_STATES = (
    (1, "Dry", "#800000"),
    (2, "Invisible", "#ff9800"),
    (3, "Low", "#7aff7d"),
    (4, "Acceptable", "#007dff"),
    (5, "Visible", "#000080"),
)
_WQ_GAP_DAYS = 120
_WQ_LEGEND_MAX = 12


def render_intermittency(
    ax: Axes,
    *,
    theme: Theme,
    df,
    title: str,
    date_start=None,
    date_end=None,
    station_names: dict[str, str] | None = None,
) -> list[Axes]:
    """Render ONDE flow states, one strip per station.

    Each observation is a colored tick on the row of its flow state. The
    given axes is split into one stacked axes per station, sharing time.
    """
    stations = [] if df is None else [c for c in df.columns if not df[c].dropna().empty]
    if not stations:
        ax.set_title(title)
        return [_no_records(ax, theme)]

    axes = _split_rows(ax, len(stations))
    colors = {code: color for code, _label, color in _ONDE_STATES}
    names = station_names or {}
    for sub, station in zip(axes, stations, strict=True):
        serie = df[station].dropna().round().clip(1, 5)
        sub.scatter(
            serie.index,
            serie.values,
            c=[colors[int(v)] for v in serie.values],
            marker="|",
            s=60,
            linewidths=1.2,
        )
        name = names.get(station)
        sub.set_title(f"{station} - {name}" if name else station)
        _time_axis(sub, theme, date_start, date_end, last=sub is axes[-1])
        sub.set_yticks([code for code, _label, _color in _ONDE_STATES])
        sub.set_yticklabels([label for _code, label, _color in _ONDE_STATES])
        sub.set_ylim(0.5, 5.5)
    _suptitle(axes[0], theme, title)
    return axes


def render_water_quality(
    ax: Axes,
    *,
    theme: Theme,
    series_by_param: dict,
    title: str,
    date_start=None,
    date_end=None,
    units: dict[str, str] | None = None,
    station_names: dict[str, str] | None = None,
) -> list[Axes]:
    """Render water-quality analyses, one strip per parameter.

    ``series_by_param`` maps parameter name to a dict of station_id -> Series.
    A station keeps one color on every strip. Analyses more than
    ``_WQ_GAP_DAYS`` apart are not joined, so a gap in sampling stays a gap.
    """
    params = [p for p, by_station in series_by_param.items() if by_station]
    if not params:
        ax.set_title(title)
        return [_no_records(ax, theme)]

    stations = sorted({sid for p in params for sid in series_by_param[p]})
    colors = dict(zip(stations, theme.class_colors(len(stations)), strict=True))
    names = station_names or {}
    units = units or {}

    axes = _split_rows(ax, len(params))
    for sub, param in zip(axes, params, strict=True):
        for sid, serie in series_by_param[param].items():
            serie = serie.dropna().sort_index()
            if serie.empty:
                continue
            sub.plot(
                _break_gaps(serie, _WQ_GAP_DAYS),
                color=colors[sid],
                linewidth=theme.data_line_width,
                marker="o",
                markersize=3,
                label=_station_label(sid, names.get(sid)),
            )
        unit = units.get(param)
        sub.set_ylabel(f"{param} ({unit})" if unit else param)
        if len(stations) == 1 and sub is axes[0]:
            sub.set_title(_station_label(stations[0], names.get(stations[0])))
        _time_axis(sub, theme, date_start, date_end, last=sub is axes[-1])
        sub.grid(
            True, axis="y", color=theme.ink, alpha=theme.grid_alpha, linewidth=theme.grid_width
        )

    if 1 < len(stations) <= _WQ_LEGEND_MAX:
        static.legend(axes[0], theme)
    _suptitle(axes[0], theme, title)
    return axes


def _split_rows(ax: Axes, n: int) -> list[Axes]:
    """Replace ``ax`` by ``n`` stacked axes sharing the x axis."""
    if n == 1:
        return [ax]
    fig = ax.figure
    grid = ax.get_subplotspec().subgridspec(n, 1)
    ax.remove()
    first = fig.add_subplot(grid[0])
    return [first] + [fig.add_subplot(grid[i], sharex=first) for i in range(1, n)]


def _suptitle(ax: Axes, theme: Theme, title: str) -> None:
    ax.figure.suptitle(title, **{**static.text_style(theme), "size": theme.title_size})


def _time_axis(ax: Axes, theme: Theme, date_start, date_end, *, last: bool) -> None:
    """Year ticks, one vertical line per year, labels on the bottom strip only."""
    import matplotlib.dates as mdates
    import pandas as pd

    if date_start is not None or date_end is not None:
        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)
    static.style_axes(ax, theme, grid=False)
    lo, hi = (mdates.num2date(v) for v in ax.get_xlim())
    step = max(1, round((hi.year - lo.year) / 8))
    ax.xaxis.set_major_locator(mdates.YearLocator(step))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax.grid(True, axis="x", which="major", color=theme.ink, alpha=theme.grid_alpha)
    ax.tick_params(axis="x", labelbottom=last)


def _break_gaps(serie, max_gap_days: int):
    """Insert NaN between two values further apart than ``max_gap_days``."""
    import pandas as pd

    times = serie.index.values.astype("datetime64[s]")
    gaps = np.diff(times) > np.timedelta64(max_gap_days, "D")
    if not gaps.any():
        return serie
    breaks = pd.DatetimeIndex(times[1:][gaps] - np.timedelta64(1, "D"))
    return pd.concat([serie, pd.Series(np.nan, index=breaks)]).sort_index()


def _station_label(station_id: str, name: str | None) -> str:
    if not name or name == station_id:
        return station_id
    short = name if len(name) <= 30 else name[:29] + "…"
    return f"{station_id} {short}"


def _no_records(ax: Axes, theme: Theme, text: str = "No records") -> Axes:
    static.style_axes(ax, theme)
    static.note(ax, text, theme)
    return ax


def render_climatic_summary(
    ax: Axes,
    *,
    theme: Theme,
    monthly_precip,
    monthly_etp,
    title: str = "Monthly climatology",
) -> Axes:
    """Render mean monthly precipitation and ETP bars side by side."""
    months = np.arange(1, 13)
    width = 0.4
    plotted = 0

    if monthly_precip is not None and len(monthly_precip) == 12:
        color = theme.roles["inflow"]
        ax.bar(months - width / 2, monthly_precip, width, color=color, label="Precipitation")
        plotted += 1
    if monthly_etp is not None and len(monthly_etp) == 12:
        color = theme.roles["evapotranspiration"]
        ax.bar(months + width / 2, monthly_etp, width, color=color, label="ETP")
        plotted += 1

    ax.set_title(title)
    ax.set_ylabel("Mean (mm)")
    static.style_axes(ax, theme)
    ax.xaxis.grid(False)
    ax.set_xticks(months)
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    if plotted > 0:
        static.legend(ax, theme)
    else:
        static.note(ax, "No climate data", theme)
    return ax


# ---------------------------------------------------------------------------
# Table / summary panels
# ---------------------------------------------------------------------------


def render_stats_card(ax: Axes, *, theme: Theme, summary: OverviewSummary) -> Axes:
    """Render the key watershed metrics as a two-column table."""
    ax.set_axis_off()

    rows: list[tuple[str, str]] = [
        ("Name", summary.watershed_name or "-"),
        (
            "Area",
            f"{summary.catchment_area_km2:.2f} km²"
            if summary.catchment_area_km2 is not None
            else "-",
        ),
        ("Period", f"{summary.date_start} -> {summary.date_end}"),
        ("Stream reaches", str(summary.n_streams)),
        ("Hydrometry stations", str(summary.n_hydrometry)),
        ("Piezometry stations", str(summary.n_piezometry)),
        ("Intermittency (ONDE)", str(summary.n_intermittency)),
        ("Water-quality stations", str(summary.n_water_quality)),
    ]

    table = ax.table(
        cellText=[[k, v] for k, v in rows],
        loc="center",
        colWidths=[0.55, 0.45],
        cellLoc="left",
    )
    table.scale(1.0, 1.5)
    _theme_table(table, theme, theme.size)
    for i, _ in enumerate(rows):
        table[(i, 0)].set_text_props(fontweight="bold")
    _table_title(ax, theme, f"Identity - {summary.watershed_name or 'Catchment'}")
    return ax


def render_station_inventory(ax: Axes, *, theme: Theme, inventory: list[dict]) -> Axes:
    """Render a flat table listing every station (type, id, coords, period)."""
    ax.set_axis_off()

    if not inventory:
        static.note(ax, "No stations loaded", theme)
        return ax

    headers = ["Type", "ID", "X", "Y", "Start", "End"]
    rows = [
        [
            str(s["type"]),
            str(s["id"]),
            f"{s['x'] or 0.0:.1f}",
            f"{s['y'] or 0.0:.1f}",
            str(s["start"]),
            str(s["end"]),
        ]
        for s in inventory
    ]

    table = ax.table(
        cellText=rows,
        colLabels=headers,
        loc="center",
        cellLoc="left",
        colWidths=[0.15, 0.28, 0.12, 0.12, 0.15, 0.15],
    )
    table.scale(1.0, 1.25)
    _theme_table(table, theme, theme.small)
    for j in range(len(headers)):
        table[(0, j)].set_text_props(fontweight="bold")
        table[(0, j)].set_facecolor(theme.roles["no_data"])
    _table_title(ax, theme, f"Station inventory - {len(inventory)} stations")
    return ax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _theme_table(table, theme: Theme, size: float) -> None:
    """Give every cell the face, ink, edge and font of the theme."""
    table.auto_set_font_size(False)
    table.set_fontsize(size)
    for cell in table.get_celld().values():
        cell.set_facecolor(theme.face)
        cell.set_edgecolor(theme.muted)
        cell.set_linewidth(theme.line_width)
        cell.get_text().set(family=theme.family, color=theme.ink, size=size)


def _table_title(ax: Axes, theme: Theme, text: str) -> None:
    ax.set_title(
        text,
        family=theme.family,
        size=theme.title_size,
        color=theme.ink,
        fontweight="bold",
        pad=theme.title_pad,
    )


def _crs_label(crs) -> str:
    """Short name of a CRS for the axis labels."""
    epsg = crs.to_epsg() if crs is not None else None
    if epsg == 2154:
        return "Lambert-93"
    return f"EPSG:{epsg}" if epsg else "map units"


def _read_dem(path: str):
    """Return the masked first band, its extent (left, right, bottom, top) and its CRS."""
    import rasterio

    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
        return data, extent, src.crs


def _relief(ax: Axes, theme: Theme, data, extent) -> None:
    """Draw the elevation raster with its colorbar."""
    im = ax.imshow(data, cmap=theme.quantity_ramps["elevation"], extent=extent, origin="upper")
    static.colorbar(ax.figure, im, ax, theme, label="Elevation (m)")


def _draw_relief(ax: Axes, theme: Theme, dem_path: str):
    data, extent, crs = _read_dem(dem_path)
    _relief(ax, theme, data, extent)
    return extent, crs


def _finish_map(ax: Axes, theme: Theme, extent, crs, title: str, *, legend: bool = True) -> Axes:
    """Title, frame, limits in km and the legend of what was drawn."""
    ax.set_title(title)
    left, right, bottom, top = extent
    static.map_axes(ax, theme, extent=(left, bottom, right, top), crs=_crs_label(crs))
    if legend and ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)
    return ax


def _proxy(ax: Axes, theme: Theme, role: str, label: str) -> None:
    """Add a legend entry for a layer that draws no labelled artist."""
    ax.plot([], [], **static.line_style(theme, role), label=label)


def _draw_outlet(ax: Axes, theme: Theme, outlet_xy, label: str) -> None:
    if outlet_xy is None:
        return
    ax.plot(
        outlet_xy[0],
        outlet_xy[1],
        marker="*",
        markersize=10,
        linestyle="none",
        color=theme.roles["outlet"],
        markeredgecolor=theme.ink,
        markeredgewidth=theme.line_width,
        zorder=10,
        label=label,
    )


def _plot_watershed_outline(ax, watershed_shp, theme: Theme) -> None:
    gdf = _read_watershed_gdf(watershed_shp)
    if gdf is not None:
        gdf.boundary.plot(ax=ax, color=theme.roles["outline"], linewidth=theme.data_line_width)


def _read_watershed_gdf(watershed_shp):
    if not watershed_shp:
        return None
    try:
        import geopandas as gpd

        gdf = gpd.read_file(watershed_shp)
        if gdf.empty:
            return None
        return gdf
    except Exception:
        return None


def _to_crs_safely(gdf, target_crs):
    if gdf is None or target_crs is None:
        return gdf
    try:
        if gdf.crs is not None and str(gdf.crs) != str(target_crs):
            return gdf.to_crs(target_crs)
    except Exception:
        return gdf
    return gdf


def _plot_station_points(
    ax, theme: Theme, points: list[dict], target_crs=None, extent=None
) -> None:
    """Scatter station markers, reprojecting their coords to ``target_crs``.

    Hub'Eau locations come in EPSG:4326 (lon/lat) while map panels render in
    the project CRS (typically EPSG:2154). Without reprojection the markers
    would land far outside the visible bbox and only the legend would show.
    A station outside ``extent`` (left, right, bottom, top) is not drawn. A
    group with no station inside keeps its legend entry, which says how far
    and in which direction its nearest station lies. The caller draws the
    legend.
    """
    groups: dict[str, list[dict]] = {}
    for pt in points:
        groups.setdefault(pt.get("group", "stations"), []).append(pt)
    for group, items in groups.items():
        xs, ys = _reproject_points_xy(items, target_crs)
        label = group
        if extent is not None:
            left, right, bottom, top = extent
            inside = [
                (x, y)
                for x, y in zip(xs, ys, strict=True)
                if left <= x <= right and bottom <= y <= top
            ]
            if not inside and xs:
                label = f"{group} ({_off_map_hint(xs, ys, extent)})"
            xs, ys = [x for x, _y in inside], [y for _x, y in inside]
        first = items[0]
        ax.scatter(
            xs,
            ys,
            marker=first.get("marker", "o"),
            c=first.get("color", theme.roles["station"]),
            edgecolor=theme.ink,
            linewidth=theme.line_width,
            s=30,
            zorder=8,
            label=label,
        )


def _off_map_hint(xs: list[float], ys: list[float], extent) -> str:
    """Distance and compass direction of the nearest point from the map center."""
    left, right, bottom, top = extent
    cx, cy = (left + right) / 2.0, (bottom + top) / 2.0
    dx, dy = min(
        ((x - cx, y - cy) for x, y in zip(xs, ys, strict=True)),
        key=lambda d: d[0] ** 2 + d[1] ** 2,
    )
    bearing = np.degrees(np.arctan2(dx, dy)) % 360.0
    direction = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int(round(bearing / 45.0)) % 8]
    return f"off map, {np.hypot(dx, dy) / 1000.0:.0f} km {direction}"


def _reproject_points_xy(items: list[dict], target_crs) -> tuple[list[float], list[float]]:
    """Reproject ``items`` (each with ``x``, ``y``, optional ``crs``) to ``target_crs``."""
    if target_crs is None:
        return [p["x"] for p in items], [p["y"] for p in items]
    try:
        from pyproj import Transformer
    except ImportError:
        return [p["x"] for p in items], [p["y"] for p in items]

    cache: dict[str, Any] = {}
    xs: list[float] = []
    ys: list[float] = []
    target_str = str(target_crs)
    for p in items:
        src_crs = p.get("crs") or "EPSG:4326"
        src_str = str(src_crs)
        if src_str == target_str:
            xs.append(float(p["x"]))
            ys.append(float(p["y"]))
            continue
        transformer = cache.get(src_str)
        if transformer is None:
            try:
                transformer = Transformer.from_crs(src_str, target_str, always_xy=True)
            except Exception:
                xs.append(float(p["x"]))
                ys.append(float(p["y"]))
                continue
            cache[src_str] = transformer
        x2, y2 = transformer.transform(float(p["x"]), float(p["y"]))
        xs.append(x2)
        ys.append(y2)
    return xs, ys


def _pick_field(gdf, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in gdf.columns:
            return name
    return None
