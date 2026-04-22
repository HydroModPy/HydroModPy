"""Panel rendering functions for the overview report.

Each ``render_*`` function takes a matplotlib ``Axes`` and the data it needs
already converted to generic types (paths, DataFrames, GeoDataFrames). This
keeps the rendering decoupled from any state dataclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.display.overview.summary import OverviewSummary


# ---------------------------------------------------------------------------
# Map panels
# ---------------------------------------------------------------------------


def render_dem_map(
    ax: "Axes",
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    station_points: list[dict] | None = None,
    title: str = "",
) -> "Axes":
    """Render a DEM raster with optional watershed outline and station markers."""
    import rasterio
    from rasterio.plot import show as rio_show

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
        streams_gdf.plot(ax=ax, color="steelblue", linewidth=0.6, alpha=0.8)

    if station_points:
        _plot_station_points(ax, station_points)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title or "DEM", fontsize=10)
    ax.set_xlabel("X (m)", fontsize=8)
    ax.set_ylabel("Y (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    return ax


def render_hydrography_map(
    ax: "Axes",
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    streams_gdf=None,
    outlet_xy: tuple[float, float] | None = None,
    title: str = "",
) -> "Axes":
    """Render a hydrography map — hillshade background, streams, outlet."""
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
        if lw_field is not None:
            for _, row in streams_gdf.iterrows():
                w = 0.4 + 0.4 * float(row.get(lw_field, 1) or 1)
                streams_gdf.iloc[[row.name]].plot(
                    ax=ax,
                    color="steelblue",
                    linewidth=w,
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
    ax: "Axes",
    *,
    dem_path: str,
    watershed_shp: str | None = None,
    geology_gdf=None,
    title: str = "",
) -> "Axes":
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
    ax: "Axes",
    *,
    df,
    ylabel: str,
    title: str,
    unit: str = "",
) -> "Axes":
    """Render a multi-station time series panel (one line per column)."""
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

    ax.set_title(title, fontsize=10)
    ax.set_ylabel(f"{ylabel} ({unit})" if unit else ylabel, fontsize=8)
    ax.set_xlabel("Date", fontsize=8)
    ax.grid(True, ls=":", lw=0.4, alpha=0.6)
    ax.tick_params(labelsize=7)
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


def render_climatic_summary(
    ax: "Axes",
    *,
    monthly_precip,
    monthly_etp,
    title: str = "Monthly climatology",
) -> "Axes":
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


def render_stats_card(ax: "Axes", *, summary: "OverviewSummary") -> "Axes":
    """Render the key watershed metrics as a two-column table."""
    ax.set_axis_off()

    rows: list[tuple[str, str]] = [
        ("Name", summary.watershed_name or "—"),
        (
            "Area",
            f"{summary.catchment_area_km2:.2f} km²"
            if summary.catchment_area_km2 is not None
            else "—",
        ),
        (
            "Outlet",
            f"({summary.outlet_xy[0]:.1f}, {summary.outlet_xy[1]:.1f})"
            if summary.outlet_xy is not None
            else "—",
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
        f"Identity — {summary.watershed_name or 'Watershed'}",
        fontsize=11,
        fontweight="bold",
    )
    return ax


def render_station_inventory(ax: "Axes", *, inventory: list[dict]) -> "Axes":
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
    ax.set_title(f"Station inventory — {len(inventory)} stations", fontsize=10)
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


def _plot_station_points(ax, points: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for pt in points:
        groups.setdefault(pt.get("group", "stations"), []).append(pt)
    for group, items in groups.items():
        xs = [p["x"] for p in items]
        ys = [p["y"] for p in items]
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


def _pick_field(gdf, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in gdf.columns:
            return name
    return None
