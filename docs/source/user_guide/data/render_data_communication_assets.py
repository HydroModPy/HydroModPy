"""Render communication-oriented figures for the data documentation.

The figures generated here are intentionally documentation assets. They do not
change HydroModPy methods; they make the data layer easier to read by turning
the supported families, sources, local deterministic cases, and recommended
run ladder into inspectable images.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch


HERE = Path(__file__).resolve()
SOURCE_ROOT = HERE.parents[2]
REPO_ROOT = HERE.parents[5]
OUTPUT_DIR = SOURCE_ROOT / "_static" / "user_guide" / "data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class Family:
    name: str
    group: str
    sources: tuple[str, ...]
    shape: str
    diagnostic: str
    downstream: str


FAMILIES: tuple[Family, ...] = (
    Family("dem", "Spatial", ("custom", "ign_bdalti"), "Raster", "DEM + basin", "support"),
    Family(
        "geology",
        "Spatial",
        ("custom", "brgm_1m", "brgm_50k"),
        "Zones",
        "map + legend",
        "zones/K",
    ),
    Family(
        "hydrography",
        "Spatial",
        ("custom", "bdtopage", "osm", "euhydro"),
        "Vector network",
        "river overlay",
        "mesh/drainage",
    ),
    Family("hydrometry", "Observed", ("custom", "hubeau"), "Stations + series", "hydrograph", "calibration"),
    Family("piezometry", "Observed", ("custom", "hubeau"), "Wells + series", "level/depth", "head checks"),
    Family("intermittency", "Observed", ("custom", "hubeau"), "States", "state timeline", "active net"),
    Family("water_quality", "Observed", ("custom", "hubeau"), "Chemistry", "parameter series", "transport"),
    Family("oceanic", "Boundary", ("custom", "shom", "constant"), "Sea level", "stage series", "coast BC"),
    Family("recharge", "Forcing", ("custom", "sim2", "synthetic"), "Grid/series", "forcing curve", "RCH"),
    Family("precipitation", "Forcing", ("custom", "sim2"), "Grid/series", "climate summary", "preprocess"),
    Family("etp", "Forcing", ("custom", "sim2"), "Grid/series", "ETP summary", "EVT"),
    Family("temperature", "Forcing", ("custom", "sim2"), "Grid/series", "climate summary", "preprocess"),
    Family("wind", "Forcing", ("custom", "sim2"), "Grid/series", "climate summary", "preprocess"),
    Family("humidity", "Forcing", ("custom", "sim2"), "Grid/series", "climate summary", "preprocess"),
    Family("radiation", "Forcing", ("custom", "sim2"), "Grid/series", "climate summary", "preprocess"),
    Family("soil_moisture", "Forcing", ("custom", "sim2"), "Grid/series", "soil summary", "diagnostic"),
    Family("runoff", "Forcing", ("custom", "sim2"), "Grid/series", "runoff summary", "balance"),
)


SOURCE_COLUMNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("custom", ("custom",), "#5578A6"),
    ("public geo", ("ign_bdalti", "brgm_1m", "brgm_50k", "bdtopage", "osm", "euhydro"), "#7BAA64"),
    ("Hub'Eau", ("hubeau",), "#C78B48"),
    ("SIM2", ("sim2",), "#6A8EC9"),
    ("SHOM", ("shom",), "#5AA6A6"),
    ("controlled", ("synthetic", "constant"), "#B66A72"),
)


def _setup() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 9,
            "font.family": "DejaVu Sans",
            "axes.edgecolor": "#444444",
            "axes.linewidth": 0.8,
        }
    )


def _save(fig: plt.Figure, name: str) -> Path:
    path = OUTPUT_DIR / name
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _parse_code_sources() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    pattern = re.compile(r'Literal\[(.*?)\]')
    for config in sorted((REPO_ROOT / "hydromodpy" / "data" / "variables").glob("*/config.py")):
        text = config.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "source:" not in line or "Literal[" not in line:
                continue
            match = pattern.search(line)
            if not match:
                continue
            sources = re.findall(r'"([^"]+)"', match.group(1))
            if sources:
                result[config.parent.name] = sources
                break
    return result


def render_source_matrix() -> Path:
    fig, ax = plt.subplots(figsize=(17.0, 8.0))
    ax.set_xlim(-3.0, len(SOURCE_COLUMNS) + 9.2)
    ax.set_ylim(-0.8, len(FAMILIES) + 1.1)
    ax.axis("off")

    ax.text(-2.85, len(FAMILIES) + 0.45, "Data family", weight="bold", fontsize=10)
    ax.text(len(SOURCE_COLUMNS) + 0.15, len(FAMILIES) + 0.45, "Sources", weight="bold", fontsize=10)
    ax.text(len(SOURCE_COLUMNS) + 5.0, len(FAMILIES) + 0.45, "Payload -> first check -> use", weight="bold", fontsize=10)

    for idx, (label, _sources, _color) in enumerate(SOURCE_COLUMNS):
        ax.text(idx + 0.5, len(FAMILIES) + 0.35, label, ha="center", va="bottom", weight="bold")

    group_colors = {"Spatial": "#E7F0E1", "Observed": "#F4E9D8", "Boundary": "#E1F0EF", "Forcing": "#E8EBF5"}

    for row, family in enumerate(FAMILIES):
        y = len(FAMILIES) - row - 0.15
        ax.add_patch(
            FancyBboxPatch(
                (-2.95, y - 0.38),
                len(SOURCE_COLUMNS) + 9.05,
                0.58,
                boxstyle="round,pad=0.02,rounding_size=0.05",
                linewidth=0,
                facecolor=group_colors[family.group],
                alpha=0.85,
            )
        )
        ax.text(-2.75, y - 0.08, family.name, va="center", ha="left", weight="bold")
        ax.text(-1.25, y - 0.08, family.group, va="center", ha="left", color="#555555")
        for idx, (_label, source_names, color) in enumerate(SOURCE_COLUMNS):
            present = [source for source in family.sources if source in source_names]
            if present:
                ax.scatter(idx + 0.5, y - 0.08, s=145, marker="s", color=color, edgecolor="white", linewidth=1.0)
        ax.text(
            len(SOURCE_COLUMNS) + 0.15,
            y - 0.08,
            ", ".join(family.sources),
            va="center",
            ha="left",
            color="#333333",
            fontsize=7.7 if len(family.sources) > 2 else 8.0,
        )
        ax.text(
            len(SOURCE_COLUMNS) + 5.0,
            y - 0.08,
            f"{family.shape} -> {family.diagnostic} -> {family.downstream}",
            va="center",
            ha="left",
            color="#333333",
            fontsize=8.6,
        )

    ax.text(
        -2.85,
        -0.55,
        "Read each row left to right: source choice is only useful after payload shape, visual check, and downstream use are explicit.",
        color="#333333",
    )
    return _save(fig, "data_family_source_matrix.png")


def render_contract_ladder() -> Path:
    fig, ax = plt.subplots(figsize=(12.0, 5.2))
    ax.axis("off")
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.2)

    steps = [
        ("Declare", "[data].types\n[[data.<family>.sources]]", "#5578A6"),
        ("Resolve", "path, API, extent,\nperiod, station ids", "#7BAA64"),
        ("Normalize", "raster, vector,\npoint, time series", "#C78B48"),
        ("Persist", "cache, lockfile,\nhashes, metadata", "#6A8EC9"),
        ("Inspect", "map, legend,\nchronicle, budget", "#5AA6A6"),
        ("Use", "overview, mesh,\nsolver, calibration", "#B66A72"),
    ]

    for idx, (title, body, color) in enumerate(steps):
        x = 0.35 + idx * 1.9
        ax.add_patch(
            FancyBboxPatch(
                (x, 2.0),
                1.55,
                1.4,
                boxstyle="round,pad=0.08,rounding_size=0.07",
                facecolor=color,
                edgecolor="none",
                alpha=0.96,
            )
        )
        ax.text(x + 0.775, 3.06, title, ha="center", va="center", color="white", weight="bold", fontsize=10)
        ax.text(x + 0.775, 2.5, body, ha="center", va="center", color="white", fontsize=8)
        if idx < len(steps) - 1:
            ax.annotate(
                "",
                xy=(x + 1.78, 2.7),
                xytext=(x + 1.58, 2.7),
                arrowprops={"arrowstyle": "->", "color": "#333333", "lw": 1.2},
            )

    ax.text(0.35, 4.45, "The data contract is not the file path", fontsize=15, weight="bold", color="#222222")
    ax.text(
        0.35,
        4.05,
        "A useful data page should show the declaration, the loaded shape, the first visual proof, and the model-facing use.",
        fontsize=10,
        color="#333333",
    )
    ax.text(
        0.35,
        0.9,
        "Documentation target: every supported family should have at least one visible diagnostic and one source-specific example.",
        fontsize=10,
        color="#333333",
    )
    return _save(fig, "data_contract_ladder.png")


def render_run_roadmap() -> Path:
    fig, ax = plt.subplots(figsize=(12.0, 6.0))
    ax.axis("off")
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)

    rows = [
        ("1", "Static inventory", "No run", "source matrix, contract ladder", "Keep docs complete"),
        ("2", "Local data cases", "Seconds", "oceanic, intermittency, custom files", "Explain formats"),
        ("3", "Data overview", "Minutes", "Nancon identity card, time series", "Show real basin inputs"),
        ("4", "Solver illustration", "Minutes+", "water budget, hydrograph, active network", "Connect data to model output"),
        ("5", "New gallery basins", "Case-by-case", "coastal SHOM, OSM/EU-Hydro, provider contrasts", "Cover missing providers"),
    ]
    headers = ["Step", "Run type", "Cost", "Figures to produce", "Documentation purpose"]
    widths = [0.8, 2.2, 1.25, 4.2, 2.9]
    xs = [0.35]
    for width in widths[:-1]:
        xs.append(xs[-1] + width)

    y_top = 4.7
    ax.text(0.35, 5.55, "Run and figure roadmap", fontsize=15, weight="bold", color="#222222")
    ax.text(0.35, 5.20, "Use the cheapest figure that answers the documentation question.", fontsize=10, color="#333333")

    for x, width, header in zip(xs, widths, headers):
        ax.add_patch(FancyBboxPatch((x, y_top - 0.25), width - 0.05, 0.48, boxstyle="round,pad=0.02", facecolor="#333333", edgecolor="none"))
        ax.text(x + 0.08, y_top, header, va="center", ha="left", color="white", weight="bold", fontsize=8.5)

    row_colors = ["#EEF3F8", "#F3F6ED", "#F7EFE4", "#EEF3F8", "#F3F0F7"]
    for ridx, row in enumerate(rows):
        y = y_top - 0.78 - ridx * 0.78
        for cidx, (x, width, text) in enumerate(zip(xs, widths, row)):
            ax.add_patch(FancyBboxPatch((x, y - 0.28), width - 0.05, 0.55, boxstyle="round,pad=0.02", facecolor=row_colors[ridx], edgecolor="white"))
            ax.text(x + 0.08, y, text, va="center", ha="left", color="#222222", fontsize=8.2, wrap=True)

    return _save(fig, "data_run_figure_roadmap.png")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _read_timeseries_csv(
    path: Path,
    *,
    delimiter: str = ",",
    date_column: str = "datetime",
    value_column: str = "value",
    date_format: str | None = None,
) -> tuple[list[datetime], list[float]]:
    with path.open("r", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter=delimiter))

    dates: list[datetime] = []
    values: list[float] = []
    for row in rows:
        raw_date = str(row[date_column]).strip()
        if date_format:
            date = datetime.strptime(raw_date, date_format)
        else:
            date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if date.tzinfo is not None:
                date = date.astimezone(timezone.utc).replace(tzinfo=None)
        dates.append(date)
        values.append(float(row[value_column]))
    return dates, values


def _series_summary(dates: list[datetime], values: list[float]) -> dict[str, object]:
    arr = np.asarray(values, dtype=float)
    return {
        "row_count": int(len(values)),
        "first_timestamp": dates[0].isoformat() if dates else None,
        "last_timestamp": dates[-1].isoformat() if dates else None,
        "min": float(np.nanmin(arr)) if arr.size else None,
        "mean": float(np.nanmean(arr)) if arr.size else None,
        "max": float(np.nanmax(arr)) if arr.size else None,
    }


def _format_projected_axes_km(ax) -> None:
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    formatter = FuncFormatter(lambda value, _pos: f"{value / 1000.0:.0f}")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)
    ax.tick_params(axis="x", labelrotation=25, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")


def render_spatial_local_example() -> tuple[Path, dict[str, object]]:
    import geopandas as gpd
    import rasterio

    dem_path = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_aber.tif"
    hydro_path = REPO_ROOT / "examples" / "data" / "hydrography" / "regional_stream_network.shp"

    with rasterio.open(dem_path) as dataset:
        dem = dataset.read(1, masked=True)
        bounds = dataset.bounds
        dem_crs = dataset.crs
        extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]

    hydro = gpd.read_file(hydro_path)
    if hydro.crs != dem_crs:
        hydro = hydro.to_crs(dem_crs)

    fig, (ax_map, ax_zoom) = plt.subplots(1, 2, figsize=(12.2, 5.2), dpi=140)
    im = ax_map.imshow(dem, extent=extent, origin="upper", cmap="terrain")
    hydro.plot(ax=ax_map, color="#175C7D", linewidth=0.75, alpha=0.75)
    ax_map.set_title("Local spatial stack: DEM + river network", loc="left", weight="bold")
    _format_projected_axes_km(ax_map)
    fig.colorbar(im, ax=ax_map, shrink=0.72, pad=0.02, label="elevation")

    hydro.plot(ax=ax_zoom, color="#175C7D", linewidth=0.85, alpha=0.9)
    ax_zoom.set_title("Loaded hydrography geometries", loc="left", weight="bold")
    _format_projected_axes_km(ax_zoom)
    ax_zoom.set_aspect("equal")
    ax_zoom.text(
        0.02,
        0.02,
        f"{len(hydro)} line features\nCRS {dem_crs}",
        transform=ax_zoom.transAxes,
        ha="left",
        va="bottom",
        fontsize=8,
        color="#333333",
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#DDDDDD", "alpha": 0.9},
    )
    fig.tight_layout()
    summary = {
        "dem_path": str(dem_path.relative_to(REPO_ROOT)),
        "hydrography_path": str(hydro_path.relative_to(REPO_ROOT)),
        "dem_shape": [int(dem.shape[0]), int(dem.shape[1])],
        "hydrography_feature_count": int(len(hydro)),
        "crs": str(dem_crs),
    }
    return _save(fig, "spatial_local_dem_hydrography_example.png"), summary


def render_geology_property_local_example() -> tuple[Path, dict[str, object]]:
    from hydromodpy.data.variables.geology.cases.run_geology_property_case import main as run_geology_case

    output_path = OUTPUT_DIR / "geology_property_brittany_local.png"
    run_geology_case(
        [
            "--geology-config-file",
            "gallery_geology_config_brittany.toml",
            "--field-param-config-file",
            "gallery_field_param_brittany.toml",
            "--output-file",
            str(output_path),
            "--window-km",
            "10",
            "--target-n-cells",
            "400",
            "--cell-samples-per-axis",
            "8",
            "--no-show-plot",
        ]
    )
    summary = {
        "geology_config": "hydromodpy/data/variables/geology/cases/gallery_geology_config_brittany.toml",
        "field_param_config": "hydromodpy/data/variables/geology/cases/gallery_field_param_brittany.toml",
        "window_km": 10,
        "target_n_cells": 400,
    }
    return output_path, summary


def render_forcing_local_example() -> tuple[Path, dict[str, object]]:
    recharge_path = REPO_ROOT / "examples" / "data" / "recharge" / "recharge_custom_NANCON_20000101_20021231_M.csv"
    runoff_path = REPO_ROOT / "examples" / "data" / "runoff" / "runoff_custom_NANCON_20000101_20021231_M.csv"
    recharge_dates, recharge_values = _read_timeseries_csv(recharge_path)
    runoff_dates, runoff_values = _read_timeseries_csv(runoff_path)

    fig, (ax_values, ax_cumulative) = plt.subplots(2, 1, figsize=(10.5, 6.0), sharex=True)
    ax_values.plot(recharge_dates, recharge_values, marker="o", markersize=3.0, color="#2E6F9E", label="recharge")
    ax_values.plot(runoff_dates, runoff_values, marker="o", markersize=3.0, color="#C78B48", label="runoff")
    ax_values.set_title("Local forcing custom case: monthly source values", loc="left", weight="bold")
    ax_values.set_ylabel("source value")
    ax_values.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_values.legend(frameon=False, loc="upper right")

    ax_cumulative.plot(
        recharge_dates,
        np.cumsum(np.asarray(recharge_values, dtype=float)),
        color="#2E6F9E",
        linewidth=2.0,
        label="cumulative recharge",
    )
    ax_cumulative.plot(
        runoff_dates,
        np.cumsum(np.asarray(runoff_values, dtype=float)),
        color="#C78B48",
        linewidth=2.0,
        label="cumulative runoff",
    )
    ax_cumulative.set_title("Coverage and aggregate behaviour before solver use", loc="left", weight="bold")
    ax_cumulative.set_ylabel("cumulative source value")
    ax_cumulative.set_xlabel("date")
    ax_cumulative.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_cumulative.legend(frameon=False, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    summary = {
        "recharge": _series_summary(recharge_dates, recharge_values),
        "runoff": _series_summary(runoff_dates, runoff_values),
    }
    return _save(fig, "forcing_local_recharge_runoff_example.png"), summary


def render_sim2_grid_example() -> tuple[Path, dict[str, object]]:
    import xarray as xr

    recharge_path = REPO_ROOT / "examples" / "data" / "recharge" / "recharge_sim2_5ce2a843_20200101_20201231.nc"
    precip_path = REPO_ROOT / "examples" / "data" / "precipitation" / "precipitation_total_sim2_5347fa22_20000101_20251231.nc"
    temperature_path = REPO_ROOT / "examples" / "data" / "temperature" / "temperature_sim2_5347fa22_20000101_20251231.nc"

    with xr.open_dataset(recharge_path) as recharge_ds:
        recharge = recharge_ds["recharge"].sel(time=slice("2020-01-01", "2020-12-31"))
        recharge_map = recharge.mean(dim="time").values
        recharge_x = recharge_ds["x"].values
        recharge_y = recharge_ds["y"].values
        recharge_summary = {
            "shape": [int(v) for v in recharge.shape],
            "mean": float(recharge.mean().values),
            "max": float(recharge.max().values),
        }

    with xr.open_dataset(precip_path) as precip_ds:
        precip = precip_ds["precipitation_total"].sel(time=slice("2020-01-01", "2020-12-31")).mean(dim=("x", "y"))
        precip_monthly = precip.resample(time="MS").sum()
        precip_summary = {
            "days": int(precip.sizes["time"]),
            "annual_total_mean_grid": float(precip_monthly.sum().values),
        }

    with xr.open_dataset(temperature_path) as temperature_ds:
        temperature = temperature_ds["temperature"].sel(time=slice("2020-01-01", "2020-12-31")).mean(dim=("x", "y"))
        temperature_monthly = temperature.resample(time="MS").mean()
        temperature_summary = {
            "days": int(temperature.sizes["time"]),
            "annual_mean_grid": float(temperature.mean().values),
        }

    fig, (ax_map, ax_cycle) = plt.subplots(1, 2, figsize=(12.0, 4.8), dpi=140)
    im = ax_map.imshow(
        recharge_map,
        origin="lower",
        extent=[float(np.min(recharge_x)), float(np.max(recharge_x)), float(np.min(recharge_y)), float(np.max(recharge_y))],
        cmap="Blues",
        aspect="auto",
    )
    ax_map.set_title("SIM2 local NetCDF: mean recharge grid, 2020", loc="left", weight="bold")
    _format_projected_axes_km(ax_map)
    fig.colorbar(im, ax=ax_map, shrink=0.78, pad=0.02, label="mean recharge")

    months = [datetime.fromisoformat(str(value)[:10]) for value in precip_monthly["time"].values]
    ax_cycle.bar(months, precip_monthly.values, width=20, color="#2E6F9E", alpha=0.75, label="monthly precipitation")
    ax_temp = ax_cycle.twinx()
    ax_temp.plot(months, temperature_monthly.values, color="#C85A54", marker="o", linewidth=1.8, label="monthly temperature")
    ax_cycle.set_title("SIM2 local NetCDF: climate cycle, 2020", loc="left", weight="bold")
    ax_cycle.set_ylabel("precipitation total")
    ax_temp.set_ylabel("temperature mean")
    ax_cycle.grid(True, axis="y", color="#DDDDDD", linewidth=0.7)
    handles, labels = ax_cycle.get_legend_handles_labels()
    handles_2, labels_2 = ax_temp.get_legend_handles_labels()
    ax_cycle.legend(handles + handles_2, labels + labels_2, frameon=False, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    summary = {
        "recharge": recharge_summary,
        "precipitation": precip_summary,
        "temperature": temperature_summary,
    }
    return _save(fig, "sim2_grid_forcing_example.png"), summary


def render_observation_local_examples() -> tuple[Path, dict[str, object]]:
    series = [
        (
            "Hydrometry",
            "Nancon discharge",
            REPO_ROOT / "examples" / "data" / "hydrometry" / "hydrometry_custom_NANCON_19820201_20220125_D.csv",
            "#2E6F9E",
        ),
        (
            "Piezometry",
            "Groundwater level",
            REPO_ROOT / "examples" / "data" / "piezometry" / "piezometry_custom_PIEZO01_19900101_19921231_D.csv",
            "#7BAA64",
        ),
        (
            "Water quality",
            "NO3 concentration",
            REPO_ROOT / "examples" / "data" / "water_quality" / "waterquality_custom_WQ_NO3_19900101_19921231_D.csv",
            "#7A6EA8",
        ),
    ]

    fig, axes = plt.subplots(len(series), 1, figsize=(10.5, 7.0), sharex=False)
    summaries: dict[str, dict[str, object]] = {}
    for ax, (family, label, path, color) in zip(axes, series, strict=True):
        dates, values = _read_timeseries_csv(path)
        summaries[family.lower().replace(" ", "_")] = _series_summary(dates, values)
        selected = [(date, value) for date, value in zip(dates, values, strict=True) if date.year == 1990]
        if not selected:
            selected = list(zip(dates[:365], values[:365], strict=True))
        selected_dates = [date for date, _value in selected]
        selected_values = [value for _date, value in selected]
        ax.plot(selected_dates, selected_values, color=color, linewidth=1.4)
        ax.set_title(f"{family}: {label}", loc="left", weight="bold")
        ax.set_ylabel("value")
        ax.grid(True, color="#DDDDDD", linewidth=0.7)
        ax.text(
            0.01,
            0.86,
            f"{summaries[family.lower().replace(' ', '_')]['row_count']} rows in full file",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="#333333",
        )
    axes[-1].set_xlabel("date")
    fig.suptitle("Local observation chronicles: same visual contract, different semantics", x=0.01, ha="left", weight="bold")
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return _save(fig, "observations_local_timeseries_examples.png"), summaries


def _read_locations(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def render_hubeau_provider_replay() -> tuple[Path, dict[str, object]]:
    providers = [
        (
            "Hydrometry",
            REPO_ROOT / "examples" / "data" / "hydrometry" / "hydrometry_hubeau_LOC.csv",
            REPO_ROOT / "examples" / "data" / "hydrometry" / "hydrometry_hubeau_J709063002_20220101_20220331_D.csv",
            "#2E6F9E",
        ),
        (
            "Piezometry",
            REPO_ROOT / "examples" / "data" / "piezometry" / "piezometry_hubeau_LOC.csv",
            REPO_ROOT / "examples" / "data" / "piezometry" / "piezometry_hubeau_03172X0088_PZ_20220101_20220331_D.csv",
            "#7BAA64",
        ),
        (
            "Water quality",
            REPO_ROOT / "examples" / "data" / "water_quality" / "waterquality_hubeau_LOC.csv",
            REPO_ROOT / "examples" / "data" / "water_quality" / "waterquality_hubeau_04161595_20070110_20240702_irregular.csv",
            "#7A6EA8",
        ),
        (
            "Intermittency",
            REPO_ROOT / "examples" / "data" / "intermittency" / "intermittency_hubeau_LOC.csv",
            REPO_ROOT / "examples" / "data" / "intermittency" / "intermittency_hubeau_J0014011_20000101_20251231_irregular.csv",
            "#C78B48",
        ),
    ]

    fig = plt.figure(figsize=(13.0, 8.4), dpi=140)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.25])
    ax_map = fig.add_subplot(gs[0, 0])
    ax_coverage = fig.add_subplot(gs[0, 1])
    ax_series = fig.add_subplot(gs[1, :])

    summaries: dict[str, dict[str, object]] = {}
    for family, loc_path, series_path, color in providers:
        locs = _read_locations(loc_path)
        xs = [float(row["x"]) for row in locs]
        ys = [float(row["y"]) for row in locs]
        ax_map.scatter(xs, ys, s=46, color=color, label=f"{family} stations", edgecolor="white", linewidth=0.8)
        for row in locs[:4]:
            ax_map.text(float(row["x"]), float(row["y"]), str(row["id"]).split("/")[0], fontsize=7, color="#333333")

        dates, values = _read_timeseries_csv(series_path)
        key = family.lower().replace(" ", "_")
        summaries[key] = {
            "locations": int(len(locs)),
            "series": _series_summary(dates, values),
            "source_file": str(series_path.relative_to(REPO_ROOT)),
        }
        ax_coverage.barh(
            family,
            max(1, len(values)),
            color=color,
            alpha=0.78,
            edgecolor="white",
        )

        if family == "Water quality":
            plot_dates = dates[-60:]
            plot_values = values[-60:]
        else:
            plot_dates = dates[:120]
            plot_values = values[:120]
        scaled = np.asarray(plot_values, dtype=float)
        if scaled.size and float(np.nanmax(scaled) - np.nanmin(scaled)) > 0.0:
            scaled = (scaled - np.nanmin(scaled)) / (np.nanmax(scaled) - np.nanmin(scaled))
        ax_series.plot(plot_dates, scaled, color=color, linewidth=1.7, label=family)

    ax_map.set_title("Hub'Eau replay: discovered station files", loc="left", weight="bold")
    ax_map.set_xlabel("longitude")
    ax_map.set_ylabel("latitude")
    ax_map.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_map.legend(frameon=False, fontsize=8, loc="best")

    ax_coverage.set_title("Chronicle rows in replay files", loc="left", weight="bold")
    ax_coverage.set_xlabel("row count (log scale)")
    ax_coverage.set_xscale("log")
    ax_coverage.grid(True, axis="x", color="#DDDDDD", linewidth=0.7)

    ax_series.set_title("Normalized first-look chronicles by Hub'Eau family", loc="left", weight="bold")
    ax_series.set_ylabel("scaled value")
    ax_series.set_xlabel("date")
    ax_series.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_series.legend(frameon=False, ncols=4, loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout()
    return _save(fig, "hubeau_provider_replay_examples.png"), summaries


def render_shom_provider_replay() -> tuple[Path, dict[str, object]]:
    loc_path = REPO_ROOT / "examples" / "data" / "oceanic" / "oceanic_custom_LOC.csv"
    shom_path = REPO_ROOT / "examples" / "data" / "oceanic" / "sealevel_shom_152_20030101_20030130_H.csv"
    custom_path = REPO_ROOT / "examples" / "data" / "oceanic" / "oceanic_custom_152_20030101_20030130_H.csv"
    locs = _read_locations(loc_path)
    shom_dates, shom_values = _read_timeseries_csv(shom_path, date_column="timestamp")
    custom_dates, custom_values = _read_timeseries_csv(custom_path, date_column="timestamp")

    fig, (ax_map, ax_series) = plt.subplots(1, 2, figsize=(11.8, 4.4), dpi=140)
    for row in locs:
        ax_map.scatter(float(row["x"]), float(row["y"]), s=90, color="#2E6F9E", edgecolor="white", linewidth=1.2)
        ax_map.text(float(row["x"]) + 0.015, float(row["y"]) + 0.015, f"station {row['id']}", fontsize=9)
    ax_map.set_title("SHOM replay: station selected for coastal stage", loc="left", weight="bold")
    ax_map.set_xlabel("longitude")
    ax_map.set_ylabel("latitude")
    ax_map.grid(True, color="#DDDDDD", linewidth=0.7)

    ax_series.plot(shom_dates, shom_values, marker="o", color="#2E6F9E", linewidth=2.0, label="SHOM replay")
    ax_series.plot(custom_dates, custom_values, marker="x", color="#C78B48", linestyle="--", linewidth=1.3, label="custom mirror")
    ax_series.set_title("Sea-level chronicle: provider replay vs custom mirror", loc="left", weight="bold")
    ax_series.set_ylabel("stage (m)")
    ax_series.set_xlabel("timestamp")
    ax_series.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_series.legend(frameon=False, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    summary = {
        "station_count": int(len(locs)),
        "shom": _series_summary(shom_dates, shom_values),
        "custom_mirror": _series_summary(custom_dates, custom_values),
    }
    return _save(fig, "shom_provider_replay_example.png"), summary


def render_hydrography_provider_replay() -> tuple[Path, dict[str, object]]:
    import geopandas as gpd

    regional_path = REPO_ROOT / "examples" / "data" / "hydrography" / "regional_stream_network.shp"
    hydro_dir = REPO_ROOT / "examples" / "data" / "hydrography"
    provider_paths = {
        "BD Topage": hydro_dir / "bdtopage_-1.2451_48.3618_-1.1072_48.4651.gpkg",
        "OSM": hydro_dir / "osm_-1.2451_48.3618_-1.1072_48.4651.gpkg",
        "EU-Hydro": hydro_dir / "euhydro_-1.2451_48.3618_-1.1072_48.4651.gpkg",
    }
    regional = gpd.read_file(regional_path)
    provider_gdfs = {
        name: gpd.read_file(path)
        for name, path in provider_paths.items()
        if path.exists()
    }

    fig, axes = plt.subplots(2, 2, figsize=(12.8, 9.0), dpi=140)
    ax_regional, ax_bdtopage, ax_osm, ax_euhydro = axes.ravel()

    regional.plot(ax=ax_regional, color="#175C7D", linewidth=0.7)
    ax_regional.set_title("Custom replay: regional stream network", loc="left", weight="bold")
    _format_projected_axes_km(ax_regional)
    ax_regional.set_aspect("equal")

    colors = {"BD Topage": "#2E6F9E", "OSM": "#7BAA64", "EU-Hydro": "#C78B48"}
    axes_by_provider = {"BD Topage": ax_bdtopage, "OSM": ax_osm, "EU-Hydro": ax_euhydro}
    for name, ax in axes_by_provider.items():
        path = provider_paths[name]
        gdf = provider_gdfs.get(name)
        if gdf is not None and not gdf.empty:
            gdf.plot(ax=ax, color=colors[name], linewidth=1.1, alpha=0.9)
            ax.set_title(f"{name} replay: Couesnon bbox", loc="left", weight="bold")
            ax.text(
                0.02,
                0.03,
                f"{len(gdf)} line features\nCRS {gdf.crs}",
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                fontsize=8,
                color="#333333",
                bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#DDDDDD", "alpha": 0.9},
            )
        else:
            ax.axis("off")
            ax.text(
                0.5,
                0.5,
                f"No {name} replay file\n{path.name}",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=9,
            )
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.grid(True, color="#DDDDDD", linewidth=0.7)

    fig.tight_layout()
    summary = {
        "regional_feature_count": int(len(regional)),
        "provider_samples": [
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "feature_count": int(len(gdf)),
                "crs": str(gdf.crs),
            }
            for name, path in provider_paths.items()
            if (gdf := provider_gdfs.get(name)) is not None
        ],
    }
    return _save(fig, "hydrography_provider_replay_examples.png"), summary


def _clip_to_bbox_wgs84(gdf, bbox: tuple[float, float, float, float]):
    import geopandas as gpd
    from shapely.geometry import box

    if gdf.empty:
        return gdf
    source = gdf if str(gdf.crs) == "EPSG:4326" else gdf.to_crs("EPSG:4326")
    mask = gpd.GeoDataFrame(geometry=[box(*bbox)], crs="EPSG:4326")
    return gpd.clip(source, mask)


def _line_length_km(gdf) -> float:
    if gdf.empty:
        return 0.0
    projected = gdf.to_crs("EPSG:2154")
    return float(projected.geometry.length.sum() / 1000.0)


def render_hydrography_provider_comparison() -> tuple[Path, dict[str, object]]:
    import geopandas as gpd
    from shapely.geometry import box

    hydro_dir = REPO_ROOT / "examples" / "data" / "hydrography"
    bbox = (-1.2451, 48.3618, -1.1072, 48.4651)
    providers = [
        ("BD Topage", hydro_dir / "bdtopage_-1.2451_48.3618_-1.1072_48.4651.gpkg", "#2E6F9E"),
        ("OSM", hydro_dir / "osm_-1.2451_48.3618_-1.1072_48.4651.gpkg", "#7BAA64"),
        ("EU-Hydro", hydro_dir / "euhydro_-1.2451_48.3618_-1.1072_48.4651.gpkg", "#C78B48"),
    ]
    clipped = {}
    stats = []
    for name, path, color in providers:
        if not path.exists():
            continue
        gdf = gpd.read_file(path)
        gdf_clip = _clip_to_bbox_wgs84(gdf, bbox)
        clipped[name] = (gdf_clip, color)
        stats.append(
            {
                "provider": name,
                "feature_count": int(len(gdf_clip)),
                "length_km": round(_line_length_km(gdf_clip), 3),
                "path": str(path.relative_to(REPO_ROOT)),
            }
        )

    fig = plt.figure(figsize=(13.2, 6.4), dpi=140)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1.0])
    ax_map = fig.add_subplot(gs[0, 0])
    ax_stats = fig.add_subplot(gs[0, 1])

    bbox_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs="EPSG:4326")
    bbox_gdf.boundary.plot(ax=ax_map, color="#333333", linewidth=1.4, linestyle="--")
    for name, (gdf_clip, color) in clipped.items():
        if not gdf_clip.empty:
            gdf_clip.plot(ax=ax_map, color=color, linewidth=1.4, alpha=0.78, label=name)
    ax_map.set_title("Couesnon hydrography provider comparison", loc="left", weight="bold")
    ax_map.set_xlabel("longitude")
    ax_map.set_ylabel("latitude")
    ax_map.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_map.legend(frameon=False, loc="upper right")
    ax_map.set_aspect("equal")

    labels = [row["provider"] for row in stats]
    counts = [row["feature_count"] for row in stats]
    lengths = [row["length_km"] for row in stats]
    y = np.arange(len(stats))
    colors = [dict((name, color) for name, _path, color in providers)[label] for label in labels]
    ax_stats.barh(y - 0.18, counts, height=0.32, color=colors, alpha=0.85, label="features")
    ax_len = ax_stats.twiny()
    ax_len.barh(y + 0.18, lengths, height=0.32, color=colors, alpha=0.42, label="km")
    ax_stats.set_yticks(y)
    ax_stats.set_yticklabels(labels)
    ax_stats.invert_yaxis()
    ax_stats.set_xlabel("feature count in bbox")
    ax_len.set_xlabel("line length in bbox (km)")
    ax_stats.set_title("Density changes by provider", loc="left", weight="bold")
    ax_stats.grid(True, axis="x", color="#DDDDDD", linewidth=0.7)
    if counts:
        ax_stats.set_xlim(0, max(counts) * 1.18)
    if lengths:
        ax_len.set_xlim(0, max(lengths) * 1.18)
    for idx, row in enumerate(stats):
        ax_stats.text(row["feature_count"] + max(counts) * 0.02, idx - 0.18, str(row["feature_count"]), va="center", fontsize=8)
        ax_len.text(row["length_km"] + max(lengths) * 0.02, idx + 0.18, f"{row['length_km']:.1f}", va="center", fontsize=8)

    fig.tight_layout()
    return _save(fig, "hydrography_provider_couesnon_comparison.png"), {
        "bbox_wgs84": list(bbox),
        "stats": stats,
    }


def render_provider_case_ladder() -> Path:
    fig, ax = plt.subplots(figsize=(15.2, 5.4), dpi=140)
    ax.axis("off")
    ax.set_xlim(0, 15.2)
    ax.set_ylim(0, 5.2)

    cards = [
        ("Replay", "Read committed\nprovider files\nand plot contract", "#5578A6"),
        ("Refresh", "Call provider only\nfor intentional\nrefresh runs", "#7BAA64"),
        ("Cache", "Persist raw payload\nunder workspace\n/data", "#C78B48"),
        ("Lock", "Record hashes,\nperiod, provider\nand file identity", "#6A8EC9"),
        ("Compare", "Publish figure\nand source-specific\nnarrative", "#B66A72"),
    ]
    for idx, (title, body, color) in enumerate(cards):
        x = 0.55 + idx * 2.85
        ax.add_patch(
            FancyBboxPatch(
                (x, 1.8),
                2.35,
                1.65,
                boxstyle="round,pad=0.08,rounding_size=0.06",
                facecolor=color,
                edgecolor="none",
                alpha=0.96,
            )
        )
        ax.text(x + 1.175, 3.03, title, ha="center", va="center", color="white", weight="bold", fontsize=11)
        ax.text(x + 1.175, 2.43, body, ha="center", va="center", color="white", fontsize=8.2, linespacing=1.05)
        if idx < len(cards) - 1:
            ax.annotate(
                "",
                xy=(x + 2.62, 2.63),
                xytext=(x + 2.38, 2.63),
                arrowprops={"arrowstyle": "->", "color": "#333333", "lw": 1.2},
            )

    ax.text(0.45, 4.45, "Provider gallery policy", fontsize=15, weight="bold", color="#222222")
    ax.text(
        0.45,
        4.05,
        "Documentation pages should use replayable provider artifacts by default; live downloads belong to intentional refresh runs.",
        fontsize=10,
        color="#333333",
    )
    ax.text(
        0.45,
        0.82,
        "This keeps SHOM, Hub'Eau, SIM2, BD Topage, OSM, and EU-Hydro examples auditable instead of silently changing with provider state.",
        fontsize=10,
        color="#333333",
    )
    return _save(fig, "provider_gallery_policy_ladder.png")


def render_oceanic_example() -> tuple[Path, dict[str, object]]:
    from hydromodpy.data.variables.oceanic.cases.run_oceanic_case import (
        run_oceanic_case_from_toml,
    )

    config = REPO_ROOT / "hydromodpy" / "data" / "variables" / "oceanic" / "cases" / "run_oceanic_config.toml"
    summary = run_oceanic_case_from_toml(config, output_json=OUTPUT_DIR / "oceanic_local_case_summary.json")
    csv_path = REPO_ROOT / "hydromodpy" / "data" / "variables" / "oceanic" / "cases" / "data" / "oceanic_local_sample.csv"
    rows = _read_csv_rows(csv_path)
    dates = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    values = [float(row["value"]) for row in rows]

    fig, ax = plt.subplots(figsize=(8.0, 3.8))
    ax.plot(dates, values, marker="o", color="#2E6F9E", linewidth=2.0)
    ax.axhline(summary["mean_msl_m"], color="#C85A54", linestyle="--", linewidth=1.4, label="mean")
    ax.set_title("Local oceanic custom case: loaded sea-level chronicle", loc="left", weight="bold")
    ax.set_ylabel("stage (m)")
    ax.set_xlabel("timestamp")
    ax.grid(True, color="#DDDDDD", linewidth=0.7)
    ax.legend(frameon=False, loc="upper right")
    ax.text(
        0.01,
        0.02,
        f"{summary['row_count']} records, mean={summary['mean_msl_m']} m",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8,
        color="#333333",
    )
    fig.autofmt_xdate()
    return _save(fig, "oceanic_local_stage_example.png"), summary


def render_intermittency_example() -> tuple[Path, dict[str, object]]:
    from hydromodpy.data.variables.intermittency.cases.run_intermittency_case import (
        run_intermittency_case_from_toml,
    )

    config = REPO_ROOT / "hydromodpy" / "data" / "variables" / "intermittency" / "cases" / "run_intermittency_config.toml"
    summary = run_intermittency_case_from_toml(config, output_json=OUTPUT_DIR / "intermittency_local_case_summary.json")
    data_dir = REPO_ROOT / "hydromodpy" / "data" / "variables" / "intermittency" / "cases" / "data"
    station_files = sorted(data_dir.glob("intermittency_custom_ONDE*_irregular.csv"))

    fig, (ax_timeline, ax_hist) = plt.subplots(1, 2, figsize=(11.5, 4.2), gridspec_kw={"width_ratios": [2.6, 1.0]})
    colors = ["#2E6F9E", "#7BAA64", "#C78B48"]
    all_values: list[int] = []
    for idx, path in enumerate(station_files):
        station = path.name.split("_")[2]
        rows = _read_csv_rows(path)
        dates = [datetime.fromisoformat(row["datetime"]) for row in rows]
        values = [int(row["value"]) for row in rows]
        all_values.extend(values)
        ax_timeline.scatter(dates, values, s=28, color=colors[idx % len(colors)], label=station, alpha=0.9)
        ax_timeline.plot(dates, values, color=colors[idx % len(colors)], linewidth=0.7, alpha=0.45)

    ax_timeline.set_title("Local intermittency custom case: state timeline", loc="left", weight="bold")
    ax_timeline.set_ylabel("state code")
    ax_timeline.set_xlabel("observation date")
    ax_timeline.set_yticks([1, 2, 3, 4, 5])
    ax_timeline.grid(True, color="#DDDDDD", linewidth=0.7)
    ax_timeline.legend(frameon=False, ncols=3, loc="upper right")

    bins = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
    ax_hist.hist(all_values, bins=bins, color="#7A6EA8", edgecolor="white")
    ax_hist.set_title("State counts", weight="bold")
    ax_hist.set_xlabel("code")
    ax_hist.set_ylabel("count")
    ax_hist.set_xticks([1, 2, 3, 4, 5])
    ax_hist.grid(True, axis="y", color="#DDDDDD", linewidth=0.7)

    fig.autofmt_xdate()
    return _save(fig, "intermittency_local_state_example.png"), summary


def main() -> int:
    _setup()
    outputs = {
        "source_matrix": str(render_source_matrix().relative_to(SOURCE_ROOT)),
        "contract_ladder": str(render_contract_ladder().relative_to(SOURCE_ROOT)),
        "run_roadmap": str(render_run_roadmap().relative_to(SOURCE_ROOT)),
    }
    spatial_path, spatial_summary = render_spatial_local_example()
    geology_path, geology_summary = render_geology_property_local_example()
    forcing_path, forcing_summary = render_forcing_local_example()
    sim2_path, sim2_summary = render_sim2_grid_example()
    observations_path, observations_summary = render_observation_local_examples()
    provider_policy_path = render_provider_case_ladder()
    hubeau_provider_path, hubeau_provider_summary = render_hubeau_provider_replay()
    shom_provider_path, shom_provider_summary = render_shom_provider_replay()
    hydrography_provider_path, hydrography_provider_summary = render_hydrography_provider_replay()
    hydrography_comparison_path, hydrography_comparison_summary = render_hydrography_provider_comparison()
    oceanic_path, oceanic_summary = render_oceanic_example()
    intermittency_path, intermittency_summary = render_intermittency_example()
    outputs["spatial_local_dem_hydrography"] = str(spatial_path.relative_to(SOURCE_ROOT))
    outputs["geology_property_local"] = str(geology_path.relative_to(SOURCE_ROOT))
    outputs["forcing_local_recharge_runoff"] = str(forcing_path.relative_to(SOURCE_ROOT))
    outputs["sim2_grid_forcing"] = str(sim2_path.relative_to(SOURCE_ROOT))
    outputs["observations_local_timeseries"] = str(observations_path.relative_to(SOURCE_ROOT))
    outputs["provider_gallery_policy"] = str(provider_policy_path.relative_to(SOURCE_ROOT))
    outputs["hubeau_provider_replay"] = str(hubeau_provider_path.relative_to(SOURCE_ROOT))
    outputs["shom_provider_replay"] = str(shom_provider_path.relative_to(SOURCE_ROOT))
    outputs["hydrography_provider_replay"] = str(hydrography_provider_path.relative_to(SOURCE_ROOT))
    outputs["hydrography_provider_comparison"] = str(hydrography_comparison_path.relative_to(SOURCE_ROOT))
    outputs["oceanic_local_stage"] = str(oceanic_path.relative_to(SOURCE_ROOT))
    outputs["intermittency_local_state"] = str(intermittency_path.relative_to(SOURCE_ROOT))

    summary = {
        "outputs": outputs,
        "families": [family.__dict__ for family in FAMILIES],
        "code_sources": _parse_code_sources(),
        "spatial_case": spatial_summary,
        "geology_case": geology_summary,
        "forcing_case": forcing_summary,
        "sim2_case": sim2_summary,
        "observation_cases": observations_summary,
        "provider_replay_cases": {
            "hubeau": hubeau_provider_summary,
            "shom": shom_provider_summary,
            "hydrography": hydrography_provider_summary,
            "hydrography_comparison": hydrography_comparison_summary,
        },
        "oceanic_case": oceanic_summary,
        "intermittency_case": intermittency_summary,
    }
    summary_path = OUTPUT_DIR / "data_communication_assets_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), "outputs": outputs}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
