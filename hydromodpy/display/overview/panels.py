"""Panel rendering functions for the overview report.

Each ``render_*`` function takes a matplotlib ``Axes`` and the data it needs
already converted to generic types (paths, DataFrames, GeoDataFrames). This
keeps the rendering decoupled from any state dataclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

from hydromodpy.display.overview.summary import OverviewSummary
from hydromodpy.display.style import place_legend

_FONT_SCALE = 1.25


def _font(size: float) -> float:
    return size * _FONT_SCALE


_MAP_LABEL_SIZE = _font(11)
_MAP_TICK_SIZE = _font(10)
_MAP_TITLE_SIZE = _font(13)
_MAP_LEGEND_SIZE = _font(10)
_MAP_COLORBAR_LABEL_SIZE = _font(10)
_MAP_COLORBAR_TICK_SIZE = _font(9)


# ---------------------------------------------------------------------------
# Map panels
# ---------------------------------------------------------------------------


def render_dem_map(
    ax: Axes,
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    outlet_xy: tuple[float, float] | None = None,
    relative_ticks: bool = False,
    stream_label: str = "Reseau",
    title: str = "",
) -> Axes:
    """Render a DEM raster with optional watershed outline, outlet and stations."""
    import rasterio
    from matplotlib.lines import Line2D

    with rasterio.open(dem_path) as src:
        data = src.read(1, masked=True)
        extent = (
            src.bounds.left,
            src.bounds.right,
            src.bounds.bottom,
            src.bounds.top,
        )

    im = ax.imshow(
        data,
        cmap="terrain",
        extent=extent,
        origin="upper",
    )
    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label(
        "Elevation (m)", fontsize=_MAP_COLORBAR_LABEL_SIZE if relative_ticks else _font(8)
    )
    cbar.ax.tick_params(labelsize=_MAP_COLORBAR_TICK_SIZE if relative_ticks else _font(7))

    handles = []
    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp)
        handles.append(Line2D([0], [0], color="black", linewidth=1.2, label="Bassin versant"))

    if streams_gdf is not None and not streams_gdf.empty:
        # The 'terrain' colormap renders valley bottoms in blue, which would
        # camouflage a steelblue stream layer; use a high-contrast colour
        # that stands out against the entire elevation palette.
        streams_gdf.plot(ax=ax, color="navy", linewidth=0.8, alpha=0.95)
        if stream_label:
            handles.append(Line2D([0], [0], color="navy", linewidth=1.2, label=stream_label))

    if station_points:
        target_crs = _read_raster_crs(dem_path)
        _plot_station_points(ax, station_points, target_crs=target_crs, extent=extent)

    if outlet_xy is not None:
        ax.plot(
            outlet_xy[0],
            outlet_xy[1],
            marker="*",
            markersize=12,
            color="crimson",
            markeredgecolor="black",
            zorder=10,
        )
        handles.append(
            Line2D(
                [0],
                [0],
                marker="*",
                color="crimson",
                markeredgecolor="black",
                linewidth=0,
                markersize=12,
                label="Exutoire",
            )
        )

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "DEM", fontsize=_MAP_TITLE_SIZE if relative_ticks else _font(10))
    if relative_ticks:
        _apply_relative_ticks(ax, extent)
    else:
        ax.set_xlabel("X (m)", fontsize=_font(8))
        ax.set_ylabel("Y (m)", fontsize=_font(8))
        ax.tick_params(labelsize=_font(7))
    _map_legend(
        ax,
        handles + ax.get_legend_handles_labels()[0],
        fontsize=_MAP_LEGEND_SIZE if relative_ticks else _font(7),
    )
    return ax


def render_regional_context_map(
    ax: Axes,
    *,
    regional_dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
) -> Axes:
    """Render a regional DEM context with the watershed footprint and stations."""
    import rasterio
    from matplotlib.lines import Line2D
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    watershed_gdf = _read_watershed_gdf(watershed_shp)
    with rasterio.open(regional_dem_path) as src:
        raster_crs = src.crs
        if watershed_gdf is not None and raster_crs is not None:
            watershed_gdf = _to_crs_safely(watershed_gdf, raster_crs)
        context_bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        window = from_bounds(*context_bounds, transform=src.transform)
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

    extent = (
        context_bounds[0],
        context_bounds[2],
        context_bounds[1],
        context_bounds[3],
    )
    im = ax.imshow(data, cmap="terrain", extent=extent, origin="upper")
    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Elevation (m)", fontsize=_MAP_COLORBAR_LABEL_SIZE)
    cbar.ax.tick_params(labelsize=_MAP_COLORBAR_TICK_SIZE)

    handles = [
        Line2D([0], [0], color="black", linewidth=1.6, label="Bassin versant"),
    ]
    if watershed_gdf is not None and not watershed_gdf.empty:
        watershed_gdf.boundary.plot(ax=ax, color="black", linewidth=1.6, zorder=6)

    if streams_gdf is not None and not streams_gdf.empty:
        streams_gdf = _to_crs_safely(streams_gdf, raster_crs)
        streams_gdf.plot(ax=ax, color="navy", linewidth=0.85, alpha=0.95, zorder=7)
        handles.append(Line2D([0], [0], color="navy", linewidth=1.2, label="Reseau observe"))

    if outlet_xy is not None:
        ax.plot(
            outlet_xy[0],
            outlet_xy[1],
            marker="*",
            markersize=12,
            color="crimson",
            markeredgecolor="black",
            zorder=10,
        )
        handles.append(
            Line2D(
                [0],
                [0],
                marker="*",
                color="crimson",
                markeredgecolor="black",
                linewidth=0,
                markersize=12,
                label="Site",
            )
        )

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "Situation regionale", fontsize=_MAP_TITLE_SIZE)
    _apply_relative_ticks(ax, extent)
    if station_points:
        _plot_station_points(ax, station_points, target_crs=raster_crs, extent=extent)
        handles += ax.get_legend_handles_labels()[0]
    _map_legend(ax, handles, fontsize=_MAP_LEGEND_SIZE)
    return ax


def render_hydrography_map(
    ax: Axes,
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    outlet_xy: tuple[float, float] | None = None,
    relative_ticks: bool = False,
    stream_label: str = "Reseau hydrographique",
    title: str = "",
) -> Axes:
    """Render a hydrography map - hillshade background, streams, outlet."""
    return render_dem_map(
        ax,
        dem_path=dem_path,
        watershed_shp=watershed_shp,
        streams_gdf=streams_gdf,
        station_points=None,
        outlet_xy=outlet_xy,
        relative_ticks=relative_ticks,
        stream_label=stream_label,
        title=title or "Hydrographie",
    )


def render_geology_map(
    ax: Axes,
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    geology_gdf=None,
    relative_ticks: bool = False,
    title: str = "",
) -> Axes:
    """Render a lithology map from a geology GeoDataFrame clipped to the bbox."""
    import rasterio

    with rasterio.open(dem_path) as src:
        data = src.read(1, masked=True)
        extent = (
            src.bounds.left,
            src.bounds.right,
            src.bounds.bottom,
            src.bounds.top,
        )

    im = ax.imshow(
        data,
        cmap="terrain",
        extent=extent,
        origin="upper",
    )
    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label(
        "Elevation (m)", fontsize=_MAP_COLORBAR_LABEL_SIZE if relative_ticks else _font(8)
    )
    cbar.ax.tick_params(labelsize=_MAP_COLORBAR_TICK_SIZE if relative_ticks else _font(7))

    if geology_gdf is not None and not geology_gdf.empty:
        code_field = _pick_field(
            geology_gdf,
            ("CODE_LEG", "code_leg", "litho", "LITHO", "LITH"),
        )
        if code_field:
            geology_gdf.plot(
                ax=ax,
                column=code_field,
                categorical=True,
                legend=True,
                alpha=0.55,
                edgecolor="none",
                legend_kwds={
                    "loc": "center left",
                    "bbox_to_anchor": (1.02, 0.5),
                    "fontsize": _MAP_LEGEND_SIZE if relative_ticks else _font(7),
                    "title": code_field,
                    "title_fontsize": _MAP_LABEL_SIZE if relative_ticks else _font(8),
                },
            )
        else:
            geology_gdf.plot(ax=ax, alpha=0.5, edgecolor="none")

    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "Geologie", fontsize=_MAP_TITLE_SIZE if relative_ticks else _font(10))
    if relative_ticks:
        _apply_relative_ticks(ax, extent)
    else:
        ax.set_xlabel("X (m)", fontsize=_font(8))
        ax.set_ylabel("Y (m)", fontsize=_font(8))
        ax.tick_params(labelsize=_font(7))
    return ax


# ---------------------------------------------------------------------------
# Time-series panels
# ---------------------------------------------------------------------------


def render_timeseries_multi(
    ax: Axes,
    *,
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
        Optional bounds applied via :meth:`Axes.set_xlim` so the panel honours
        the requested time window even when the underlying records span a
        wider period.
    hlines
        Optional list of horizontal reference lines, each described by a dict
        with keys ``y`` (float), ``label`` (str), and optional ``color`` /
        ``linestyle``. Used to overlay e.g. the piezometer surface altitude.
    """
    if df is None or df.empty:
        ax.text(
            0.5,
            0.5,
            "No records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=_font(9),
            color="grey",
        )
        ax.set_title(title, fontsize=_font(10))
        return ax

    plotted = 0
    for station in df.columns:
        serie = df[station].dropna()
        if serie.empty:
            continue
        ax.plot(serie.index, serie.values, linewidth=0.6, alpha=0.8, label=station)
        plotted += 1

    if hlines:
        for line in hlines:
            y = line.get("y")
            if y is None:
                continue
            ax.axhline(
                float(y),
                color=line.get("color", "darkred"),
                linestyle=line.get("linestyle", "--"),
                linewidth=0.8,
                alpha=0.85,
                label=line.get("label"),
            )

    if date_start is not None or date_end is not None:
        import pandas as pd

        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)

    ax.set_title(title, fontsize=_font(10))
    ax.set_ylabel(f"{ylabel} ({unit})" if unit else ylabel, fontsize=_font(8))
    ax.set_xlabel("Date", fontsize=_font(8))
    ax.grid(True, ls=":", lw=0.4, alpha=0.6)
    ax.tick_params(labelsize=_font(7))
    legend_entries = plotted + (len(hlines) if hlines else 0)
    if 0 < legend_entries <= 12:
        place_legend(ax, fontsize=_font(6), ncol=min(3, legend_entries))
    if plotted == 0:
        ax.text(
            0.5,
            0.5,
            "No valid records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=_font(9),
            color="grey",
        )
    return ax


# ONDE flow states, 1 = dry to 5 = visible flow, coloured as in HydroModPy v1.
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
    df,
    title: str,
    date_start=None,
    date_end=None,
    station_names: dict[str, str] | None = None,
) -> list[Axes]:
    """Render ONDE flow states, one strip per station.

    Each observation is a coloured tick on the row of its flow state. The
    given axes is split into one stacked axes per station, sharing time.
    """
    stations = [] if df is None else [c for c in df.columns if not df[c].dropna().empty]
    if not stations:
        _no_records(ax, title)
        return [ax]

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
            s=_font(110),
            linewidths=_font(1.6),
        )
        sub.set_yticks([code for code, _label, _color in _ONDE_STATES])
        sub.set_yticklabels([label for _code, label, _color in _ONDE_STATES], fontsize=_font(8))
        sub.set_ylim(0.5, 5.5)
        name = names.get(station)
        sub.set_title(f"{station} - {name}" if name else station, fontsize=_font(9))
        _time_axis(sub, date_start, date_end, last=sub is axes[-1])
    axes[0].figure.suptitle(title, fontsize=_font(11))
    return axes


def render_water_quality(
    ax: Axes,
    *,
    series_by_param: dict,
    title: str,
    date_start=None,
    date_end=None,
    units: dict[str, str] | None = None,
    station_names: dict[str, str] | None = None,
) -> list[Axes]:
    """Render water-quality analyses, one strip per parameter.

    ``series_by_param`` maps parameter name to a dict of station_id -> Series.
    A station keeps one colour on every strip. Analyses more than
    ``_WQ_GAP_DAYS`` apart are not joined, so a gap in sampling stays a gap.
    """
    params = [p for p, by_station in series_by_param.items() if by_station]
    if not params:
        _no_records(ax, title)
        return [ax]

    from matplotlib import colormaps

    stations = sorted({sid for p in params for sid in series_by_param[p]})
    cmap = colormaps["tab10" if len(stations) <= 10 else "tab20"]
    colors = {sid: cmap(i % cmap.N) for i, sid in enumerate(stations)}
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
                linewidth=1.0,
                alpha=0.9,
                marker="o",
                markersize=3.5,
                label=_station_label(sid, names.get(sid)),
            )
        unit = units.get(param)
        sub.set_ylabel(f"{param} ({unit})" if unit else param, fontsize=_font(8))
        sub.tick_params(axis="y", labelsize=_font(7))
        sub.grid(True, axis="y", ls=":", lw=0.4, alpha=0.6)
        _time_axis(sub, date_start, date_end, last=sub is axes[-1])

    if len(stations) == 1:
        axes[0].set_title(_station_label(stations[0], names.get(stations[0])), fontsize=_font(9))
    elif len(stations) <= _WQ_LEGEND_MAX:
        axes[0].legend(
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            fontsize=_font(6.5),
            frameon=False,
            title=f"{len(stations)} station(s)",
            title_fontsize=_font(7),
        )
    axes[0].figure.suptitle(title, fontsize=_font(11))
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


def _time_axis(ax: Axes, date_start, date_end, *, last: bool) -> None:
    """Year ticks, one vertical line per year, labels on the bottom strip only."""
    import matplotlib.dates as mdates
    import pandas as pd

    if date_start is not None or date_end is not None:
        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)
    lo, hi = (mdates.num2date(v) for v in ax.get_xlim())
    step = max(1, round((hi.year - lo.year) / 8))
    ax.xaxis.set_major_locator(mdates.YearLocator(step))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax.grid(True, axis="x", which="major", color="0.75", lw=0.8)
    ax.tick_params(axis="x", labelsize=_font(7.5), labelbottom=last)


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


def _no_records(ax: Axes, title: str) -> None:
    ax.text(
        0.5,
        0.5,
        "No records",
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=_font(9),
        color="grey",
    )
    ax.set_title(title, fontsize=_font(10))


def render_climatic_summary(
    ax: Axes,
    *,
    monthly_precip,
    monthly_etp,
    title: str = "Monthly climatology",
) -> Axes:
    """Render mean monthly precipitation and ETP bars side by side."""
    months = np.arange(1, 13)
    width = 0.4
    plotted = 0

    if monthly_precip is not None and len(monthly_precip) == 12:
        ax.bar(
            months - width / 2,
            monthly_precip,
            width,
            color="steelblue",
            alpha=0.85,
            label="Precipitation",
        )
        plotted += 1
    if monthly_etp is not None and len(monthly_etp) == 12:
        ax.bar(
            months + width / 2,
            monthly_etp,
            width,
            color="darkorange",
            alpha=0.85,
            label="ETP",
        )
        plotted += 1

    ax.set_xticks(months)
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax.set_title(title, fontsize=_font(10))
    ax.set_ylabel("Moyenne (mm)", fontsize=_font(8))
    ax.grid(True, ls=":", lw=0.4, axis="y", alpha=0.6)
    ax.tick_params(labelsize=_font(7))
    if plotted > 0:
        place_legend(ax, fontsize=_font(7))
    else:
        ax.text(
            0.5,
            0.5,
            "Aucune donnee climatique",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=_font(9),
            color="grey",
        )
    return ax


# ---------------------------------------------------------------------------
# Table / summary panels
# ---------------------------------------------------------------------------


def render_stats_card(ax: Axes, *, summary: OverviewSummary) -> Axes:
    """Render the key watershed metrics as a two-column table."""
    ax.set_axis_off()

    rows: list[tuple[str, str]] = [
        ("Nom", summary.watershed_name or "-"),
        (
            "Surface",
            f"{summary.catchment_area_km2:.2f} km²"
            if summary.catchment_area_km2 is not None
            else "-",
        ),
        ("Periode", f"{summary.date_start} -> {summary.date_end}"),
        ("Troncons hydrographiques", str(summary.n_streams)),
        ("Stations hydrometrie", str(summary.n_hydrometry)),
        ("Stations piezometrie", str(summary.n_piezometry)),
        ("Intermittence (ONDE)", str(summary.n_intermittency)),
        ("Stations qualite eau", str(summary.n_water_quality)),
    ]

    table = ax.table(
        cellText=[[k, v] for k, v in rows],
        loc="center",
        colWidths=[0.55, 0.45],
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(_font(9))
    table.scale(1.0, 1.5)
    for i, _ in enumerate(rows):
        table[(i, 0)].set_text_props(fontweight="bold")
    ax.set_title(
        f"Identite - {summary.watershed_name or 'Bassin'}",
        fontsize=_font(11),
        fontweight="bold",
    )
    return ax


def render_station_inventory(ax: Axes, *, inventory: list[dict]) -> Axes:
    """Render a flat table listing every station (type, id, coords, period)."""
    ax.set_axis_off()

    if not inventory:
        ax.text(
            0.5,
            0.5,
            "No stations loaded",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=_font(9),
            color="grey",
        )
        return ax

    headers = ["Type", "ID", "X", "Y", "Debut", "Fin"]
    rows = [
        [
            str(s["type"]),
            str(s["id"]),
            f"{s['x']:.1f}",
            f"{s['y']:.1f}",
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
    table.auto_set_font_size(False)
    table.set_fontsize(_font(7))
    table.scale(1.0, 1.25)
    for j in range(len(headers)):
        table[(0, j)].set_text_props(fontweight="bold")
        table[(0, j)].set_facecolor("#e8e8e8")
    ax.set_title(f"Station inventory - {len(inventory)} stations", fontsize=_font(10))
    return ax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_legend(ax, handles: list, *, fontsize: float) -> None:
    """Draw the map legend under the axes, so it never hides the map.

    Three columns, or two when a label is long enough to make the legend
    wider than the map.
    """
    if not handles:
        return
    longest = max(len(str(h.get_label())) for h in handles)
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=min(len(handles), 2 if longest > 20 else 3),
        fontsize=fontsize,
        frameon=False,
        markerscale=0.9,
        handlelength=1.6,
        columnspacing=1.4,
    )


def _apply_relative_ticks(ax, extent: tuple[float, float, float, float]) -> None:
    """Display map coordinates relative to the lower-left extent corner."""
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    xmin, _, ymin, _ = extent
    locator_kw = {"nbins": 4, "integer": False, "prune": "both", "steps": [1, 2, 5, 10]}
    ax.xaxis.set_major_locator(MaxNLocator(**locator_kw))
    ax.yaxis.set_major_locator(MaxNLocator(**locator_kw))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{(value - xmin) / 1000:.1f}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{(value - ymin) / 1000:.1f}"))
    ax.set_xlabel("X relatif (km)", fontsize=_MAP_LABEL_SIZE)
    ax.set_ylabel("Y relatif (km)", fontsize=_MAP_LABEL_SIZE)
    ax.tick_params(labelsize=_MAP_TICK_SIZE)


def _plot_watershed_outline(ax, watershed_shp) -> None:
    try:
        import geopandas as gpd

        gdf = gpd.read_file(watershed_shp)
        gdf.boundary.plot(ax=ax, color="black", linewidth=1.2)
    except Exception:
        pass


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


def _plot_station_points(ax, points: list[dict], target_crs=None, extent=None) -> None:
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
            c=first.get("color", "red"),
            edgecolor="black",
            linewidth=0.5,
            s=36,
            zorder=8,
            label=label,
        )


def _off_map_hint(xs: list[float], ys: list[float], extent) -> str:
    """Distance and compass direction of the nearest point from the map centre."""
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


def _read_raster_crs(path: str):
    """Return the CRS of a raster file, or None on failure."""
    try:
        import rasterio

        with rasterio.open(path) as src:
            return src.crs
    except Exception:
        return None


def _pick_field(gdf, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in gdf.columns:
            return name
    return None
