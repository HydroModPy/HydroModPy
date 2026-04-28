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
    title: str = "",
) -> Axes:
    """Render a DEM raster with optional watershed outline and station markers."""
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
    cbar.set_label("Elevation (m)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp)

    if streams_gdf is not None and not streams_gdf.empty:
        # The 'terrain' colormap renders valley bottoms in blue, which would
        # camouflage a steelblue stream layer; use a high-contrast colour
        # that stands out against the entire elevation palette.
        streams_gdf.plot(ax=ax, color="navy", linewidth=0.8, alpha=0.95)

    if station_points:
        target_crs = _read_raster_crs(dem_path)
        _plot_station_points(ax, station_points, target_crs=target_crs)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "DEM", fontsize=10)
    ax.set_xlabel("X (m)", fontsize=8)
    ax.set_ylabel("Y (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    return ax


def render_hydrography_map(
    ax: Axes,
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
) -> Axes:
    """Render a hydrography map - hillshade background, streams, outlet."""
    import rasterio

    with rasterio.open(dem_path) as src:
        data = src.read(1, masked=True)
        extent = (
            src.bounds.left,
            src.bounds.right,
            src.bounds.bottom,
            src.bounds.top,
        )

    ax.imshow(
        data,
        cmap="Greys_r",
        extent=extent,
        origin="upper",
        alpha=0.55,
    )

    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp)

    if streams_gdf is not None and not streams_gdf.empty:
        lw_field = _pick_field(
            streams_gdf,
            ("STRAHLER", "strahler", "strahler_order", "order"),
        )
        # Sources like BD TOPAGE leave Strahler order empty for many tributaries
        # and reserve it for EU-Hydro-tagged reaches. Falling back to per-row
        # `linewidth=NaN` made those reaches invisible. Compute a clean width
        # column with a visible default (Strahler 1) when the order is missing.
        if lw_field is not None:
            import pandas as pd

            order = pd.to_numeric(streams_gdf[lw_field], errors="coerce").fillna(1.0)
            widths = 0.4 + 0.4 * order.clip(lower=1.0)
            for (_, row), width in zip(streams_gdf.iterrows(), widths, strict=False):
                streams_gdf.iloc[[row.name]].plot(
                    ax=ax,
                    color="steelblue",
                    linewidth=float(width),
                )
        else:
            streams_gdf.plot(ax=ax, color="steelblue", linewidth=0.8)

    if outlet_xy is not None:
        ax.plot(
            outlet_xy[0],
            outlet_xy[1],
            marker="*",
            markersize=12,
            color="crimson",
            markeredgecolor="black",
            zorder=10,
            label="Outlet",
        )
        ax.legend(loc="lower right", fontsize=7)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "Hydrography", fontsize=10)
    ax.set_xlabel("X (m)", fontsize=8)
    ax.set_ylabel("Y (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    return ax


def render_geology_map(
    ax: Axes,
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    geology_gdf=None,
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

    ax.imshow(
        data,
        cmap="Greys_r",
        extent=extent,
        origin="upper",
        alpha=0.45,
    )

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
                    "fontsize": 6,
                    "title": code_field,
                    "title_fontsize": 7,
                },
            )
        else:
            geology_gdf.plot(ax=ax, alpha=0.5, edgecolor="none")

    if watershed_shp:
        _plot_watershed_outline(ax, watershed_shp)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "Geology", fontsize=10)
    ax.set_xlabel("X (m)", fontsize=8)
    ax.set_ylabel("Y (m)", fontsize=8)
    ax.tick_params(labelsize=7)
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
            fontsize=9,
            color="grey",
        )
        ax.set_title(title, fontsize=10)
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

    ax.set_title(title, fontsize=10)
    ax.set_ylabel(f"{ylabel} ({unit})" if unit else ylabel, fontsize=8)
    ax.set_xlabel("Date", fontsize=8)
    ax.grid(True, ls=":", lw=0.4, alpha=0.6)
    ax.tick_params(labelsize=7)
    legend_entries = plotted + (len(hlines) if hlines else 0)
    if 0 < legend_entries <= 12:
        ax.legend(fontsize=6, loc="best", ncol=min(3, legend_entries))
    if plotted == 0:
        ax.text(
            0.5,
            0.5,
            "No valid records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color="grey",
        )
    return ax


def render_intermittency(
    ax: Axes,
    *,
    df,
    title: str,
    date_start=None,
    date_end=None,
) -> Axes:
    """Render ONDE flow-state observations as a step plot per station.

    The ordinal flow code (1 = dry, 5 = visible flow) is plotted with
    discrete y-axis ticks. Sparse observations (Hub'Eau ONDE is monthly at
    best) are connected with steps to ease readability.
    """
    if df is None or df.empty:
        ax.text(
            0.5,
            0.5,
            "No records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color="grey",
        )
        ax.set_title(title, fontsize=10)
        return ax

    plotted = 0
    for station in df.columns:
        serie = df[station].dropna()
        if serie.empty:
            continue
        ax.step(
            serie.index,
            serie.values,
            where="post",
            linewidth=0.9,
            alpha=0.85,
            marker="o",
            markersize=3,
            label=station,
        )
        plotted += 1

    if date_start is not None or date_end is not None:
        import pandas as pd

        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)

    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(
        ["1: Dry", "2: Non-visible", "3: Weak", "4: Acceptable", "5: Visible"],
        fontsize=7,
    )
    ax.set_ylim(0.5, 5.5)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Date", fontsize=8)
    ax.grid(True, ls=":", lw=0.4, alpha=0.6)
    ax.tick_params(axis="x", labelsize=7)
    if 0 < plotted <= 10:
        ax.legend(fontsize=6, loc="best", ncol=min(3, plotted))
    if plotted == 0:
        ax.text(
            0.5,
            0.5,
            "No valid records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color="grey",
        )
    return ax


def render_water_quality(
    ax: Axes,
    *,
    series_by_param: dict,
    title: str,
    date_start=None,
    date_end=None,
) -> Axes:
    """Render water-quality observations grouped by parameter.

    ``series_by_param`` maps parameter name to a dict of station_id -> Series.
    Each parameter is plotted on its own twin y-axis (up to 3 parameters);
    additional parameters are folded into the leftmost axis. The dataset is
    typically sparse (a few analyses per year), so points are emphasised.
    """
    import pandas as pd  # noqa: F401  (only needed for date conversion below)

    if not series_by_param:
        ax.text(
            0.5,
            0.5,
            "No records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color="grey",
        )
        ax.set_title(title, fontsize=10)
        return ax

    palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    plotted = 0
    for color_idx, (param, station_series) in enumerate(series_by_param.items()):
        color = palette[color_idx % len(palette)]
        for station, serie in station_series.items():
            if serie.empty:
                continue
            ax.plot(
                serie.index,
                serie.values,
                linewidth=0.6,
                alpha=0.7,
                color=color,
                marker="o",
                markersize=3,
                label=f"{param} ({station})",
            )
            plotted += 1

    if date_start is not None or date_end is not None:
        lo = pd.to_datetime(date_start) if date_start is not None else None
        hi = pd.to_datetime(date_end) if date_end is not None else None
        ax.set_xlim(lo, hi)

    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Date", fontsize=8)
    ax.set_ylabel("Concentration / value", fontsize=8)
    ax.grid(True, ls=":", lw=0.4, alpha=0.6)
    ax.tick_params(labelsize=7)
    if 0 < plotted <= 10:
        ax.legend(fontsize=6, loc="best", ncol=min(2, plotted))
    if plotted == 0:
        ax.text(
            0.5,
            0.5,
            "No valid records",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
            color="grey",
        )
    return ax


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
    ax.set_title(title, fontsize=10)
    ax.set_ylabel("Mean (mm)", fontsize=8)
    ax.grid(True, ls=":", lw=0.4, axis="y", alpha=0.6)
    ax.tick_params(labelsize=7)
    if plotted > 0:
        ax.legend(fontsize=7, loc="best")
    else:
        ax.text(
            0.5,
            0.5,
            "No climatic data",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=9,
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
        ("Name", summary.watershed_name or "-"),
        (
            "Area",
            f"{summary.catchment_area_km2:.2f} km²"
            if summary.catchment_area_km2 is not None
            else "-",
        ),
        (
            "Outlet",
            f"({summary.outlet_xy[0]:.1f}, {summary.outlet_xy[1]:.1f})"
            if summary.outlet_xy is not None
            else "-",
        ),
        ("Period", f"{summary.date_start} → {summary.date_end}"),
        ("Streams", str(summary.n_streams)),
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
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.5)
    for i, _ in enumerate(rows):
        table[(i, 0)].set_text_props(fontweight="bold")
    ax.set_title(
        f"Identity - {summary.watershed_name or 'Watershed'}",
        fontsize=11,
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
            fontsize=9,
            color="grey",
        )
        return ax

    headers = ["Type", "ID", "X", "Y", "Start", "End"]
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
    table.set_fontsize(7)
    table.scale(1.0, 1.25)
    for j in range(len(headers)):
        table[(0, j)].set_text_props(fontweight="bold")
        table[(0, j)].set_facecolor("#e8e8e8")
    ax.set_title(f"Station inventory - {len(inventory)} stations", fontsize=10)
    return ax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plot_watershed_outline(ax, watershed_shp) -> None:
    try:
        import geopandas as gpd

        gdf = gpd.read_file(watershed_shp)
        gdf.boundary.plot(ax=ax, color="black", linewidth=1.2)
    except Exception:
        pass


def _plot_station_points(ax, points: list[dict], target_crs=None) -> None:
    """Scatter station markers, reprojecting their coords to ``target_crs``.

    Hub'Eau locations come in EPSG:4326 (lon/lat) while map panels render in
    the project CRS (typically EPSG:2154). Without reprojection the markers
    would land far outside the visible bbox and only the legend would show.
    """
    groups: dict[str, list[dict]] = {}
    for pt in points:
        groups.setdefault(pt.get("group", "stations"), []).append(pt)
    for group, items in groups.items():
        xs, ys = _reproject_points_xy(items, target_crs)
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
            label=group,
        )
    if groups:
        ax.legend(loc="upper right", fontsize=7, markerscale=0.8)


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
