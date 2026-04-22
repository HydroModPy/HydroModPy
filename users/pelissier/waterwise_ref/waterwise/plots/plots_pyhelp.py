from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import geopandas as gpd
import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box

from waterwise.plots.plots_common import (
    RasterRef,
    compute_hillshade,
    ensure_dir,
    ensure_parent_dir,
    extent_from_transform,
    save_figure,
    save_stack_pngs,
)

sys.path.append(str(Path('C:/Users/Pelissierm/Hydromodpy')))

from hydromodpy.pyhelp.output import HelpOutput

COMPONENTS = {
    "rechg": ("Recharge", "mm"),
    "runoff": ("Runoff", "mm"),
    "evapo": ("Evapotranspiration", "mm"),
    "precip": ("Precipitation", "mm"),
}


def load_monthly_climatology(out_path):
    out_path = Path(out_path)

    with h5py.File(out_path, "r") as h5:
        g = h5["data"]

        cid = g["cid"][:]
        cid = [c.decode() if isinstance(c, bytes) else str(c) for c in cid]

        precip = g["precip"][:]
        runoff = g["runoff"][:]
        evapo = g["evapo"][:]
        rechg = g["rechg"][:]

    precip = precip.mean(axis=1)
    runoff = runoff.mean(axis=1)
    evapo = evapo.mean(axis=1)
    rechg = rechg.mean(axis=1)

    rows = []
    for i, c in enumerate(cid):
        for m in range(12):
            rows.append({
                "cid": c,
                "month": m + 1,
                "precip": precip[i, m],
                "runoff": runoff[i, m],
                "evapo": evapo[i, m],
                "rechg": rechg[i, m],
            })
    return pd.DataFrame(rows)


def load_area_yearly(out_path):
    out_path = Path(out_path)

    with h5py.File(out_path, "r") as h5:
        g = h5["data"]
        years = g["years"][:]
        precip = g["precip"][:]
        runoff = g["runoff"][:]
        evapo = g["evapo"][:]
        rechg = g["rechg"][:]

    precip = precip.sum(axis=2)
    runoff = runoff.sum(axis=2)
    evapo = evapo.sum(axis=2)
    rechg = rechg.sum(axis=2)

    return pd.DataFrame({
        "year": years,
        "precip": precip.mean(axis=0),
        "runoff": runoff.mean(axis=0),
        "evapo": evapo.mean(axis=0),
        "rechg": rechg.mean(axis=0),
    })


def _linear_trend_per_decade(years, values):
    x = years.astype(float)
    y = values.astype(float)
    a, b = np.polyfit(x, y, 1)
    return float(a * 10.0), (a * x + b)


def _get_component_title_unit(component):
    return COMPONENTS[component]


def _format_period_label(year_from, year_to):
    if np.isfinite(year_from) and np.isfinite(year_to):
        return f"{int(year_from)}-{int(year_to)}"
    return None


def _csv_points_to_raster(csv_path, value_col, lat_col="lat_dd", lon_col="lon_dd", target_crs="EPSG:3035", snap_m=10.0, agg="mean"):
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)

    for c in (lat_col, lon_col, value_col):
        if c not in df.columns:
            raise ValueError(f"Column '{c}' not found in {csv_path.name}")

    d = df[[lat_col, lon_col, value_col]].copy()
    d[lat_col] = pd.to_numeric(d[lat_col], errors="coerce")
    d[lon_col] = pd.to_numeric(d[lon_col], errors="coerce")
    d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
    d = d.dropna(subset=[lat_col, lon_col, value_col])

    t = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    x, y = t.transform(d[lon_col].to_numpy(dtype=float), d[lat_col].to_numpy(dtype=float))
    d["x"] = x
    d["y"] = y

    if snap_m and snap_m > 0:
        d["x"] = (d["x"] / snap_m).round() * snap_m
        d["y"] = (d["y"] / snap_m).round() * snap_m

    if agg == "mean":
        g = d.groupby(["x", "y"], as_index=False)[value_col].mean()
    elif agg == "median":
        g = d.groupby(["x", "y"], as_index=False)[value_col].median()
    elif agg == "first":
        g = d.drop_duplicates(subset=["x", "y"], keep="first")
    else:
        raise ValueError("agg must be one of {'mean','median','first'}")

    xs = np.sort(g["x"].unique())
    ys = np.sort(g["y"].unique())
    if xs.size < 2 or ys.size < 2:
        raise ValueError("Not enough unique x/y values to build a grid.")

    dx = float(np.median(np.diff(xs)))
    dy = float(np.median(np.diff(ys)))

    xmin = float(xs.min() - dx / 2.0)
    xmax = float(xs.max() + dx / 2.0)
    ymin = float(ys.min() - dy / 2.0)
    ymax = float(ys.max() + dy / 2.0)

    ncol = xs.size
    nrow = ys.size
    arr = np.full((nrow, ncol), np.nan, dtype=np.float32)

    y_to_i = {float(v): i for i, v in enumerate(ys[::-1])}
    x_to_j = {float(v): j for j, v in enumerate(xs)}

    for _, r in g.iterrows():
        i = y_to_i[float(r["y"])]
        j = x_to_j[float(r["x"])]
        arr[i, j] = float(r[value_col])

    transform = from_origin(xmin, ymax, dx, dy)
    extent = (xmin, xmax, ymin, ymax)
    return arr, extent, transform, target_crs


def plot_trend_and_mean(data, component, save_path, year_from=-np.inf, year_to=np.inf):
    title, unit = _get_component_title_unit(component)

    if isinstance(data, (str, Path)):
        with h5py.File(Path(data), "r") as h5:
            g = h5["data"]
            years = np.asarray(g["years"][:], dtype=float)
            arr = np.asarray(g[component][:], dtype=float)

        if arr.ndim == 3:
            y = arr.sum(axis=2).mean(axis=0)
        elif arr.ndim == 2:
            y = arr.mean(axis=0)
        else:
            raise ValueError(f"Unexpected shape for '{component}': {arr.shape}")
    else:
        if "year" not in data.columns:
            raise ValueError("df_area_yearly must contain a 'year' column")
        years = pd.to_numeric(data["year"], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(data[component], errors="coerce").to_numpy(dtype=float)

    mask = np.isfinite(years) & np.isfinite(y) & (years >= year_from) & (years <= year_to)
    years = years[mask].astype(int)
    y = y[mask]

    if years.size == 0:
        raise ValueError(f"No valid data for '{component}' in selected period: {year_from}-{year_to}")

    mean_val = float(np.mean(y))
    trend_decade, y_fit = _linear_trend_per_decade(years, y)

    period_label = _format_period_label(year_from, year_to)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(years, y, marker="o", label=f"Annual {title.lower()}")
    ax.axhline(mean_val, linestyle="--", label=f"Mean = {mean_val:.1f} {unit}/yr")
    ax.plot(years, y_fit, linestyle="--", label=f"Trend = {trend_decade:.2f} {unit}/decade")
    if period_label is None:
        ax.set_title(f"{title}: mean and linear trend")
    else:
        ax.set_title(f"{title}: mean and linear trend ({period_label})")
    ax.set_xlabel("Year")
    ax.set_ylabel(f"{title} ({unit}/year)")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    ax.ticklabel_format(style="plain", axis="x", useOffset=False)
    return save_figure(fig, save_path, dpi=150)


def plot_intermonthly(data, component, save_path, year_from=-np.inf, year_to=np.inf, ymax: float = None):
    title, unit = _get_component_title_unit(component)

    if not isinstance(data, (str, Path)):
        raise ValueError("plot_intermonthly now expects a .out file")

    out_path = Path(data)
    with h5py.File(out_path, "r") as h5:
        arr = h5["data"][component][:]
        years = h5["data"]["years"][:].astype(int)

    mask_years = (years >= year_from) & (years <= year_to)
    if not np.any(mask_years):
        raise ValueError(f"No data in selected period: {year_from}-{year_to}")

    arr = arr[:, mask_years, :]
    basin = arr.mean(axis=0)
    mean_ = basin.mean(axis=0)
    q05_ = np.quantile(basin, 0.05, axis=0)
    q95_ = np.quantile(basin, 0.95, axis=0)

    x = np.arange(1, 13)
    period_label = _format_period_label(year_from, year_to)

    fig = plt.figure(figsize=(9, 6))
    plt.plot(x, mean_, marker="o", label="Monthly mean (basin)")
    plt.fill_between(x, q05_, q95_, alpha=0.2, label="5–95% interannual")
    plt.xticks(x)
    if period_label is None:
        plt.title(f"Intermonthly {title.lower()}")
    else:
        plt.title(f"Intermonthly {title.lower()} ({period_label})")
    plt.xlabel("Months")
    plt.ylabel(f"{title} ({unit}/month)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    if ymax is not None:
        plt.ylim(0, ymax)

    return save_figure(fig, save_path, dpi=150)


def plot_spatialised(csv_path, component, save_path, clip_shp, boundary_shp=None, glaciers_shp=None, hillshade_dem=None, target_crs="EPSG:3035", snap_m=10.0, agg="mean"):
    save_path = ensure_parent_dir(save_path)

    arr, _, tr, crs = _csv_points_to_raster(
        csv_path=csv_path,
        value_col=component,
        lat_col="lat_dd",
        lon_col="lon_dd",
        target_crs=target_crs,
        snap_m=float(snap_m),
        agg=agg,
    )

    ref = RasterRef(crs=crs, transform=tr, height=arr.shape[0], width=arr.shape[1])

    border_path = boundary_shp if boundary_shp and Path(boundary_shp).exists() else clip_shp
    border = gpd.read_file(border_path) if border_path else None

    glaciers = None
    if glaciers_shp and Path(glaciers_shp).exists():
        glaciers = gpd.read_file(glaciers_shp)
        if glaciers.crs is None:
            glaciers = glaciers.set_crs("EPSG:4326")
        glaciers = glaciers[glaciers.geometry.notna() & ~glaciers.geometry.is_empty].copy()
        glaciers = glaciers.to_crs(ref.crs)

        xmin, xmax, ymin, ymax = extent_from_transform(ref.transform, ref.height, ref.width)
        bbox = gpd.GeoDataFrame({"id": [1]}, geometry=[box(xmin, ymin, xmax, ymax)], crs=ref.crs)
        glaciers = gpd.clip(glaciers, bbox)
        if glaciers.empty:
            glaciers = None

    hillshade_show = hillshade_transform = None
    if hillshade_dem is not None:
        xmin, xmax, ymin, ymax = extent_from_transform(ref.transform, ref.height, ref.width)
        bbox = gpd.GeoDataFrame({"id": [1]}, geometry=[box(xmin, ymin, xmax, ymax)], crs=ref.crs)

        with tempfile.TemporaryDirectory() as td:
            bbox_path = Path(td) / "bbox.gpkg"
            bbox.to_file(bbox_path, driver="GPKG")
            hillshade_show, hillshade_transform = compute_hillshade(
                dem_path=hillshade_dem,
                clip_shp=str(bbox_path),
                ref=ref,
                azdeg=135.0,
                altdeg=45.0,
                vert_exag=2.0,
                smooth_sigma=1.0,
            )

    stem = {
        "precip": "precipitation",
        "runoff": "runoff",
        "evapo": "evapotranspiration",
        "rechg": "recharge",
    }.get(component, component)

    save_stack_pngs(
        out_dir=save_path.parent,
        stem=stem,
        stack=arr[None, ...].astype(np.float32),
        ref=ref,
        border=border,
        glaciers=glaciers,
        hillshade=hillshade_show,
        hillshade_transform=hillshade_transform,
        hillshade_alpha=1.0,
        overlay_alpha=0.75,
        glaciers_alpha=1.0,
        qmin=0.10,
        qmax=0.90,
    )

    return save_path.parent / f"{stem}.png"


def plot_all_outputs(workdir, save_dir=None, area_yearly="help_example.out", monthly_clim_csv="help_example.out", 
                     components=("precip", "runoff", "evapo", "rechg"), 
                     year_from=-np.inf, year_to=np.inf, ymax=None):
    workdir = Path(workdir)
    save_dir_path = ensure_dir(save_dir if save_dir is not None else workdir)

    for comp in components:
        plot_trend_and_mean(
            workdir / area_yearly,
            comp,
            save_dir_path / f"{comp}_trend_mean.png",
            year_from=year_from,
            year_to=year_to
        )
        plot_intermonthly(
            workdir / monthly_clim_csv,
            comp,
            save_dir_path / f"{comp}_intermonthly.png",
            year_from=year_from,
            year_to=year_to,
            ymax=ymax
        )

    return save_dir_path


def generate_historical_pyhelp_plots(workdir, save_dir=None, watershed_shp=None, glaciers_shp=None, hillshade_dem=None, components=("rechg", "runoff", "evapo"), year_from=-np.inf, year_to=np.inf):
    workdir = Path(workdir)
    plots_dir = ensure_dir(save_dir if save_dir is not None else workdir / "plots_pyhelp")

    plot_all_outputs(
        workdir=workdir,
        save_dir=plots_dir,
        year_from=year_from,
        year_to=year_to,
    )
    for component in components:
        plot_spatialised(
            csv_path=workdir / "help_example_yearly.csv",
            component=component,
            save_path=plots_dir / f"{component}_spatial.png",
            clip_shp=watershed_shp,
            glaciers_shp=glaciers_shp,
            hillshade_dem=hillshade_dem,
        )
    return plots_dir


def generate_builtin_pyhelp_plots(workdir, save_dir, out_file = "help_example.out", fig_title: str = "PyHELP results", ymax = None):
    output_fpath = Path(workdir, out_file)
    hout = HelpOutput(str(output_fpath))
    # grid = hout.grid
    hout.plot_area_monthly_avg(
        fig_title=fig_title,
        figname=Path(save_dir, "area_monthly_avg.png")
        )
    hout.plot_area_yearly_avg(
        fig_title=fig_title,
        figname=Path(save_dir, "area_yearly_avg.png"),
        ymax=ymax
        )
    hout.plot_area_yearly_series(
        fig_title=fig_title,
        figname=Path(save_dir, "area_yearly_series.png"),
        ymax=ymax
        )


__all__ = [
    "COMPONENTS",
    "load_monthly_climatology",
    "load_area_yearly",
    "plot_trend_and_mean",
    "plot_intermonthly",
    "plot_spatialised",
    "plot_all_outputs",
    "generate_historical_pyhelp_plots",
]




if __name__ == "__main__":
    # workdir='C:/Users/Pelissierm/Waterwise_predictions/zugs/_inm_cm5_0'
    # savedir='C:/Users/Pelissierm/Waterwise_predictions/zugs/_inm_cm5_0/plots_pyhelp'
    
    workdir='C:/Users/Pelissierm/Waterwise/HDPY_models/_rech/results_pyhelp'
    savedir='C:/Users/Pelissierm/Waterwise/HDPY_models/_rech/results_pyhelp/plots_pyhelp'
    # plot_all_outputs(workdir, savedir, year_from=2075, year_to=2100, ymax=280)
    
    generate_builtin_pyhelp_plots(workdir, savedir, ymax = 2300)
    
    pass

    
    
    
    
    
    
    
    
    
    