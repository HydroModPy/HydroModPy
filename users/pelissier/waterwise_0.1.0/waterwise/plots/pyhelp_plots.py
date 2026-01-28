# -*- coding: utf-8 -*-
"""
Created on Tue Jan 27 08:45:15 2026

@author: pelissierm
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import geopandas as gpd

import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from pyproj import Transformer
from matplotlib.colors import LightSource
from matplotlib.patches import Patch, PathPatch
from matplotlib.lines import Line2D
from matplotlib.path import Path as MplPath



#%%config & constants

COMPONENTS = {
    "rechg": ("Recharge", "mm"),
    "runoff": ("Runoff", "mm"),
    "evapo": ("Evapotranspiration", "mm"),
    "precip": ("Precipitation", "mm"),
}

MONTHS = tuple(range(1, 13))

CLIMATE_BANDS_UNITS = {
    "precipitation": "mm/day",
    "air temperature": "°C",
    "solar radiation": "MJ/m²",
}

# Expected file
CLIMATE_INPUT_STEMS = {
    "precipitation": "precip_input_data_fixed.csv",
    "air temperature": "airtemp_input_data_fixed.csv",
    "solar radiation": "solrad_input_data_fixed.csv",
}


#%%Data loading

def load_area_yearly_series(csv_path):

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing file: {csv_path}")

    df = pd.read_csv(csv_path)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["year"]).copy()
    df["year"] = df["year"].astype(int)
    return df.sort_values("year").reset_index(drop=True)

def load_monthly_climatology_long(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing file: {csv_path}")

    df = pd.read_csv(csv_path, dtype={"cid": str})

    df = df.set_index("cid")
    pat = re.compile(r"^(?P<var>[a-zA-Z]+)_(?P<mm>\d{2})$")
    allowed = set(COMPONENTS.keys())

    cols: list[str] = []
    tuples: list[Tuple[str, int]] = []
    for c in df.columns:
        m = pat.match(c)
        if not m:
            continue
        var = m.group("var")
        mm = int(m.group("mm"))
        if var in allowed and 1 <= mm <= 12:
            cols.append(c)
            tuples.append((var, mm))

    if not cols:
        raise ValueError(
            f"No monthly climatology columns found in {csv_path.name}. "
            "Expected columns like 'precip_01', 'runoff_12', etc."
        )

    sub = df[cols].copy()
    sub.columns = pd.MultiIndex.from_tuples(tuples, names=["var", "month"])

    long = sub.stack(level="month").reset_index()
    long["month"] = pd.to_numeric(long["month"], errors="coerce").astype(int)

    # Ensure all standard columns exist
    for v in allowed:
        if v not in long.columns:
            long[v] = np.nan

    return long[["cid", "month", "precip", "runoff", "evapo", "rechg"]].sort_values(["cid", "month"])


#%%Private functions
def _linear_trend_per_decade(years, values):
    x = years.astype(float)
    y = values.astype(float)
    a, b = np.polyfit(x, y, 1)
    return float(a * 10.0), (a * x + b)


def _read_climate_timeseries_csv(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing file: {csv_path}")

    df = pd.read_csv(csv_path, header=None)

    if df.shape[0] < 3 or df.shape[1] < 2:
        raise ValueError(f"Unexpected climate CSV shape for {csv_path.name}: {df.shape}")

    raw_dates = df.iloc[2:, 0].astype(str).str.strip()
    dates = pd.to_datetime(raw_dates, dayfirst=True, errors="coerce", infer_datetime_format=True)

    data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy()

    valid = dates.notna().to_numpy()
    return pd.DatetimeIndex(dates[valid]), data[valid, :]

def _test_parent_dir(path):
    path.parent.mkdir(parents=True, exist_ok=True)

def _get_component_title_unit(component):
    return COMPONENTS[component]

def _detect_climate_band(csv_path):
    name = csv_path.name.lower()
    if "precip" in name:
        return "precipitation"
    if "airtemp" in name or "air_temp" in name or "temperature" in name:
        return "air temperature"
    if "solrad" in name or "solar" in name:
        return "solar radiation"
    return None

#%%Helpers for spatial mappings
def _ring_to_vertices_codes(coords):
    coords = list(coords)
    if len(coords) < 4:
        return [], []

    x0, y0 = coords[0][0], coords[0][1]
    verts = [(x0, y0)]
    codes = [MplPath.MOVETO]

    for pt in coords[1:]:
        x, y = pt[0], pt[1]
        verts.append((x, y))
        codes.append(MplPath.LINETO)

    codes[-1] = MplPath.CLOSEPOLY
    return verts, codes


def _geom_to_path(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        verts, codes = [], []
        v, c = _ring_to_vertices_codes(geom.exterior.coords)
        verts += v
        codes += c
        for ring in geom.interiors:
            v, c = _ring_to_vertices_codes(ring.coords)
            verts += v
            codes += c
        return MplPath(verts, codes) if verts else None
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        all_verts, all_codes = [], []
        for g in geom.geoms:
            p = _geom_to_path(g)
            if p is None:
                continue
            all_verts.extend(p.vertices.tolist())
            all_codes.extend(p.codes.tolist())
        return MplPath(all_verts, all_codes) if all_verts else None
    return None

def _csv_points_to_raster(
    csv_path,
    value_col,
    lat_col="lat_dd",
    lon_col="lon_dd",
    target_crs="EPSG:3035",
    snap_m=10.0,
    agg="mean",
):
    """
    Build a regular raster from CSV points by projecting lon/lat to a metric CRS.
    This avoids the 'each point has unique lat/lon' issue.

    - target_crs: use EPSG:3035 (LAEA Europe) to get meters.
    - snap_m: snapping precision in meters to stabilize unique x/y extraction.
    """
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

    # Project lon/lat -> x/y (meters)
    t = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    x, y = t.transform(d[lon_col].to_numpy(dtype=float), d[lat_col].to_numpy(dtype=float))
    d["x"] = x
    d["y"] = y

    # Optional snapping to reduce floating noise
    if snap_m and snap_m > 0:
        d["x"] = (d["x"] / snap_m).round() * snap_m
        d["y"] = (d["y"] / snap_m).round() * snap_m

    # Aggregate duplicates
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

    # raster extent (edges)
    xmin = float(xs.min() - dx / 2.0)
    xmax = float(xs.max() + dx / 2.0)
    ymin = float(ys.min() - dy / 2.0)
    ymax = float(ys.max() + dy / 2.0)

    ncol = xs.size
    nrow = ys.size
    arr = np.full((nrow, ncol), np.nan, dtype=np.float32)

    # y descending for imshow(origin="upper")
    y_to_i = {float(v): i for i, v in enumerate(ys[::-1])}
    x_to_j = {float(v): j for j, v in enumerate(xs)}

    for _, r in g.iterrows():
        i = y_to_i[float(r["y"])]
        j = x_to_j[float(r["x"])]
        arr[i, j] = float(r[value_col])

    transform = from_origin(xmin, ymax, dx, dy)
    extent = (xmin, xmax, ymin, ymax)
    return arr, extent, transform, target_crs



def _hillshade_on_grid(
    dem_path,
    dst_shape,
    dst_transform,
    dst_crs,
    azdeg=135.0,
    altdeg=45.0,
    vert_exag=2.0,
):
    dem_path = Path(dem_path)

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32)
        if src.nodata is not None:
            dem[dem == src.nodata] = np.nan

        res_x, res_y = src.res
        ls = LightSource(azdeg=azdeg, altdeg=altdeg)

        hs_native = ls.hillshade(
            dem,
            vert_exag=vert_exag,
            dx=res_x,
            dy=res_y,
        ).astype(np.float32)

        dst = np.full(dst_shape, np.nan, np.float32)

        reproject(
            source=hs_native,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )

    return dst


def _dem_on_grid(dem_path, dst_shape, dst_transform, dst_crs):
    dem_path = Path(dem_path)
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32)
        if src.nodata is not None:
            dem[dem == src.nodata] = np.nan

        dst = np.full(dst_shape, np.nan, np.float32)
        reproject(
            source=dem,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
    return dst



#%%Plotting climatic functions
def plot_climate_timeseries(csv_path, save_path, label = None, unit = None):
    csv_path = Path(csv_path)
    save_path = Path(save_path)
    _test_parent_dir(save_path)

    dates, data = _read_climate_timeseries_csv(csv_path)
    ts_mean = np.nanmean(data, axis=1)
    global_mean = float(np.nanmean(ts_mean))

    if label is None or unit is None:
        band = _detect_climate_band(csv_path)
        if label is None and band is not None:
            label = band
        if unit is None and band in CLIMATE_BANDS_UNITS:
            unit = CLIMATE_BANDS_UNITS[band]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(dates, ts_mean)
    ax.axhline(global_mean, linestyle="--", label=f"Global mean = {global_mean:.3g}")
    ax.set_title(label or csv_path.stem)
    ax.set_xlabel("Date")
    ax.set_ylabel(unit or "")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    return save_path

def plot_climate_timeseries_batch(workdir, save_dir = None, csv_paths = None):
    workdir = Path(workdir)
    save_dir = Path(save_dir) if save_dir is not None else workdir / "plots_climate_inputs"
    save_dir.mkdir(parents=True, exist_ok=True)

    if csv_paths is None:
        csv_paths = sorted(workdir.glob("*_input_data_fixed.csv"))

    for csv in map(Path, csv_paths):
        band = _detect_climate_band(csv)
        out_png = save_dir / f"{csv.stem}_timeseries.png"
        plot_climate_timeseries(
            csv_path=csv,
            save_path=out_png,
            label=band,
            unit=CLIMATE_BANDS_UNITS.get(band, "") if band else "",
        )

    return save_dir

def plot_climate_boxplots(workdir, save_dir = None):
    workdir = Path(workdir)
    save_dir_path = Path(save_dir) if save_dir is not None else None
    if save_dir_path is not None:
        save_dir_path.mkdir(parents=True, exist_ok=True)

    for band, filename in CLIMATE_INPUT_STEMS.items():
        csv_path = workdir / filename
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path, header=None)
        data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy().ravel()
        data = data[np.isfinite(data)]
        if data.size == 0:
            continue

        plt.figure(figsize=(4, 6))
        plt.boxplot(data)
        plt.title(band)
        plt.ylabel(CLIMATE_BANDS_UNITS[band])
        plt.grid(True, axis="y", alpha=0.3)

        if save_dir_path is not None:
            out_png = save_dir_path / f"boxplot_{band.replace(' ', '_')}.png"
            plt.savefig(out_png, dpi=150, bbox_inches="tight")
            plt.close()
        else:
            plt.show()

    return save_dir_path


def plot_climate_mean_maps(workdir, watershed_shp = None, save_dir = None):
    workdir = Path(workdir)
    save_dir_path = Path(save_dir) if save_dir is not None else None
    if save_dir_path is not None:
        save_dir_path.mkdir(parents=True, exist_ok=True)

    if watershed_shp is None:
        watershed_shp = workdir.parent / "results_stable" / "geographic" / "watershed.shp"
    watershed_shp = Path(watershed_shp)

    basin = None
    if watershed_shp.exists():
        basin = gpd.read_file(watershed_shp).to_crs(epsg=4326)

    for band, filename in CLIMATE_INPUT_STEMS.items():
        csv_path = workdir / filename
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path, header=None)

        lats = pd.to_numeric(df.iloc[0, 1:], errors="coerce").to_numpy()
        lons = pd.to_numeric(df.iloc[1, 1:], errors="coerce").to_numpy()
        data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy()

        mean_pixels = np.nanmean(data, axis=0)
        valid = np.isfinite(lats) & np.isfinite(lons) & np.isfinite(mean_pixels)
        if not np.any(valid):
            continue

        fig, ax = plt.subplots(figsize=(8, 6))
        sc = ax.scatter(lons[valid], lats[valid], c=mean_pixels[valid], cmap="viridis", s=2000, marker="s")

        if basin is not None:
            basin.boundary.plot(ax=ax, edgecolor="red", linewidth=1.5)

        fig.colorbar(sc, ax=ax, label=f"mean value [{CLIMATE_BANDS_UNITS[band]}]")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(f"{band} mean map")
        ax.set_aspect("equal", adjustable="box")

        if save_dir_path is not None:
            out_png = save_dir_path / f"mean_map_{band.replace(' ', '_')}.png"
            fig.savefig(out_png, dpi=150, bbox_inches="tight")
            plt.close(fig)
        else:
            fig.tight_layout()
            plt.show()

    return save_dir_path


#%%Plotting PyHELP outputs

def plot_trend_and_mean(df_area_yearly, component, save_path):
    title, unit = _get_component_title_unit(component)

    if "year" not in df_area_yearly.columns:
        raise ValueError("df_area_yearly must contain a 'year' column")

    years = pd.to_numeric(df_area_yearly["year"], errors="coerce").to_numpy()
    y = pd.to_numeric(df_area_yearly.get(component), errors="coerce").to_numpy()

    mask = np.isfinite(years) & np.isfinite(y)
    years = years[mask].astype(int)
    y = y[mask].astype(float)

    mean_val = float(np.mean(y))
    trend_decade, y_fit = _linear_trend_per_decade(years, y)

    save_path = Path(save_path)
    _test_parent_dir(save_path)

    plt.figure(figsize=(9, 6))
    plt.plot(years, y, marker="o", label=f"Annual {title.lower()}")
    plt.ticklabel_format(style="plain", axis="x", useOffset=False)
    plt.axhline(mean_val, linestyle="--", label=f"Mean = {mean_val:.1f} {unit}/yr")
    plt.plot(years, y_fit, linestyle="--", label=f"Trend = {trend_decade:.2f} {unit}/decade")
    plt.title(f"{title}: mean and linear trend")
    plt.xlabel("Year")
    plt.ylabel(f"{title} ({unit}/year)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.savefig(save_path, bbox_inches="tight", dpi=150)
    plt.close()
    return save_path


def plot_interannual(df_area_yearly, component, save_path):
    title, unit = _get_component_title_unit(component)

    if "year" not in df_area_yearly.columns:
        raise ValueError("df_area_yearly must contain a 'year' column")

    years = pd.to_numeric(df_area_yearly["year"], errors="coerce").to_numpy()
    y = pd.to_numeric(df_area_yearly.get(component), errors="coerce").to_numpy()

    mask = np.isfinite(years) & np.isfinite(y)
    years = years[mask].astype(int)
    y = y[mask].astype(float)

    if years.size == 0:
        raise ValueError(f"No valid data for '{component}'")

    mean_val = float(np.mean(y))

    save_path = Path(save_path)
    _test_parent_dir(save_path)

    plt.figure(figsize=(9, 6))
    plt.plot(years, y, marker="o", label=f"Annual {title.lower()}")
    plt.ticklabel_format(style="plain", axis="x", useOffset=False)
    plt.axhline(mean_val, linestyle="--", label=f"Mean = {mean_val:.1f} {unit}/yr")
    plt.title(f"Interannual {title.lower()}")
    plt.xlabel("Year")
    plt.ylabel(f"Annual {title.lower()} ({unit}/year)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.savefig(save_path, bbox_inches="tight", dpi=150)
    plt.close()
    return save_path


def plot_intermonthly(df_clim_long, component, save_path):

    title, unit = _get_component_title_unit(component)

    if "month" not in df_clim_long.columns or component not in df_clim_long.columns:
        raise ValueError(f"df_clim_long must contain 'month' and '{component}' columns")

    d = df_clim_long.dropna(subset=["month", component]).copy()
    d["month"] = pd.to_numeric(d["month"], errors="coerce").astype(int)
    d = d[(d["month"] >= 1) & (d["month"] <= 12)]
    if d.empty:
        raise ValueError(f"No valid monthly data for '{component}'")

    g = d.groupby("month")[component]
    stats = pd.DataFrame(
        {"mean": g.mean(), "q05": g.quantile(0.05), "q95": g.quantile(0.95)}
    ).reindex(MONTHS)

    x = np.array(MONTHS)
    y = stats["mean"].to_numpy()
    y05 = stats["q05"].to_numpy()
    y95 = stats["q95"].to_numpy()

    save_path = Path(save_path)
    _test_parent_dir(save_path)

    plt.figure(figsize=(9, 6))
    plt.plot(x, y, marker="o", label="Monthly sum mean")
    plt.fill_between(x, y05, y95, alpha=0.2, label="5–95%")
    plt.xticks(MONTHS)
    plt.title(f"Intermonthly {title.lower()}")
    plt.xlabel("Months")
    plt.ylabel(f"{title} ({unit}/month)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.savefig(save_path, bbox_inches="tight", dpi=150)
    plt.close()
    return save_path

def plot_spatialised(csv_path, component, save_path, title=None, cbar_label=None, boundary_shp=None, glaciers_shp=None,
    dem_for_hillshade=None, overlay_alpha=0.8, hillshade_alpha=0.35, glaciers_alpha=1.0, vmin=None, vmax=None,
    lat_col="lat_dd", lon_col="lon_dd",
):
    
    csv_path = Path(csv_path)
    save_path = Path(save_path)
    _test_parent_dir(save_path)
    
    comp_title, comp_unit = _get_component_title_unit(component)
    if title is None:
        title = comp_title
    if cbar_label is None:
        cbar_label = f"{comp_unit}/year"
        
    arr, (xmin, xmax, ymin, ymax), dst_transform, dst_crs = _csv_points_to_raster(
        csv_path=csv_path,
        value_col=component,
        lat_col=lat_col,
        lon_col=lon_col,
        target_crs="EPSG:3035",
        snap_m=10.0,
        agg="mean",
    )

    hillshade = None
    if dem_for_hillshade is not None:
        hillshade = _hillshade_on_grid(
            dem_path=dem_for_hillshade,
            dst_shape=arr.shape,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
        )

        
    border = None
    if boundary_shp is not None and Path(boundary_shp).exists():
        border = gpd.read_file(Path(boundary_shp)).to_crs(dst_crs)
    
    glaciers = None
    if glaciers_shp is not None and Path(glaciers_shp).exists():
        glaciers = gpd.read_file(Path(glaciers_shp)).to_crs(dst_crs)

    fig = plt.figure(figsize=(5, 7))
    ax = fig.add_axes([0.06, 0.06, 0.72, 0.88])
    
    if hillshade is not None:
        ax.imshow(hillshade, cmap="Greys", extent=[xmin, xmax, ymin, ymax],
          origin="upper", alpha=hillshade_alpha, zorder=1)
    
    im = ax.imshow(arr, cmap="viridis", extent=[xmin, xmax, ymin, ymax],
               origin="upper", alpha=1.0, zorder=10)
    
    if glaciers is not None and not glaciers.empty:
        try:
            plt.rcParams["hatch.linewidth"] = 1.0
        except Exception:
            pass
        
        for geom in glaciers.geometry:
            pth = _geom_to_path(geom)
            if pth is None:
                continue
            
            ax.add_patch(PathPatch(pth, facecolor=(0.0, 1.0, 1.0, 0.10), edgecolor="none", linewidth=0.0, zorder=90))
            ax.add_patch(PathPatch(pth, facecolor="none", edgecolor="cyan", linewidth=1.4, hatch="///", alpha=glaciers_alpha, zorder=95))
    
    if border is not None and not border.empty:
        border.boundary.plot(ax=ax, color="red", linewidth=2.6, zorder=130)
        xmin2, ymin2, xmax2, ymax2 = border.total_bounds
        dx, dy = xmax2 - xmin2, ymax2 - ymin2
        m = 0.12
        ax.set_xlim(xmin2 - m * dx, xmax2 + m * dx)
        ax.set_ylim(ymin2 - m * dy, ymax2 + m * dy)
    else:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

    ax.set_axis_off()
    ax.set_title(title, pad=6)
    
    cax = fig.add_axes([0.80, 0.10, 0.05, 0.80])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(cbar_label)
    
    legend_items = []
    if glaciers is not None and not glaciers.empty:
        legend_items.append(Patch(facecolor=(0.0, 1.0, 1.0, 0.10), edgecolor="cyan", hatch="///", label="Glacier"))
    if border is not None and not border.empty:
        legend_items.append(Line2D([0], [0], color="red", lw=2.6, label="Boundaries"))
        
    if legend_items:
        leg = ax.legend(handles=legend_items, loc="lower left", frameon=True, framealpha=1.0, facecolor="white", edgecolor="black", fontsize=6)
        leg.set_zorder(1000)
        
    fig.savefig(save_path, dpi=300)
    plt.close(fig)
    return save_path
        


# Main pipeline
def plot_all_outputs(workdir, save_dir = None,
    area_yearly_csv: str = "help_example_area_yearly_series_from_daily.csv",
    monthly_clim_csv: str = "help_example_monthly_climatology_from_daily.csv",
    components = ("precip", "runoff", "evapo", "rechg"),
):

    workdir = Path(workdir)
    save_dir_path = Path(save_dir) if save_dir is not None else workdir
    save_dir_path.mkdir(parents=True, exist_ok=True)

    df_area = load_area_yearly_series(workdir / area_yearly_csv)
    df_clim_long = load_monthly_climatology_long(workdir / monthly_clim_csv)

    for comp in components:
        plot_trend_and_mean(df_area, comp, save_dir_path / f"{comp}_trend_mean.png")
        plot_interannual(df_area, comp, save_dir_path / f"{comp}_interannual.png")
        plot_intermonthly(df_clim_long, comp, save_dir_path / f"{comp}_intermonthly.png")

    return save_dir_path



workdir = r"C:\Users\Pelissierm\Waterwise\HDPY_models\_urse\results_pyhelp"
workdir = Path(workdir)

plot_spatialised(
    csv_path=workdir / "help_example_yearly.csv",
    component="rechg",
    save_path=workdir / "plots_pyhelp" / "rechg_spatial.png",
    boundary_shp=workdir.parent / "results_stable" / "geographic" / "watershed.shp",
    glaciers_shp=Path(r"Z:\HDPY_database_forModelling\PyHELP_rasters\rgi_clip.shp"),
    dem_for_hillshade=r"Z:\HDPY_database_forModelling\_sites\_urse\_urse_clipped_dem.tif"
    
)