from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tempfile

from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box

from scipy.interpolate import griddata

from waterwise.plots.plots_common import ensure_dir, ensure_parent_dir, save_figure, RasterRef, compute_hillshade, save_stack_pngs


CLIMATE_BANDS_UNITS = {
    "precipitation": "mm/day",
    "air temperature": "°C",
    "solar radiation": "MJ/m²",
}

CLIMATE_INPUT_STEMS = {
    "precipitation": "precip_input_data.csv",
    "air temperature": "airtemp_input_data.csv",
    "solar radiation": "solrad_input_data.csv",
}


def _read_climate_timeseries_csv(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing file: {csv_path}")

    df = pd.read_csv(csv_path, header=None)

    if df.shape[0] < 3 or df.shape[1] < 2:
        raise ValueError(f"Unexpected climate CSV shape for {csv_path.name}: {df.shape}")

    raw_dates = df.iloc[2:, 0].astype(str).str.strip()

    dates = pd.to_datetime(raw_dates, dayfirst=True, errors="coerce")
    data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy()

    valid = ~pd.isna(dates)

    dates = pd.DatetimeIndex(dates[valid])
    data = data[valid, :]

    return dates, data


def _detect_climate_band(csv_path):
    name = Path(csv_path).name.lower()
    if "precip" in name:
        return "precipitation"
    if "airtemp" in name or "air_temp" in name or "temperature" in name:
        return "air temperature"
    if "solrad" in name or "solar" in name:
        return "solar radiation"
    return None


def plot_climate_timeseries(csv_path, save_path, label=None, unit=None):
    csv_path = Path(csv_path)
    save_path = ensure_parent_dir(save_path)

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
    return save_figure(fig, save_path, dpi=150, bbox_inches=None)


def plot_climate_timeseries_batch(workdir, save_dir=None, csv_paths=None):
    workdir = Path(workdir)
    save_dir = ensure_dir(save_dir if save_dir is not None else workdir / "plots_climate_inputs")

    if csv_paths is None:
        csv_paths = [workdir / f for f in CLIMATE_INPUT_STEMS.values()]

    for csv in map(Path, csv_paths):
        if not csv.exists():
            continue

        band = _detect_climate_band(csv)
        out_png = save_dir / f"{csv.stem}_timeseries.png"

        plot_climate_timeseries(
            csv_path=csv,
            save_path=out_png,
            label=band,
            unit=CLIMATE_BANDS_UNITS.get(band, "") if band else "",
        )

    return save_dir


def plot_climate_boxplots(workdir, save_dir=None):
    workdir = Path(workdir)
    save_dir_path = ensure_dir(save_dir) if save_dir is not None else None

    for band, filename in CLIMATE_INPUT_STEMS.items():
        csv_path = workdir / filename
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path, header=None)
        data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy().ravel()
        data = data[np.isfinite(data)]
        if data.size == 0:
            continue

        fig = plt.figure(figsize=(4, 6))
        plt.boxplot(data)
        plt.title(band)
        plt.ylabel(CLIMATE_BANDS_UNITS[band])
        plt.grid(True, axis="y", alpha=0.3)

        if save_dir_path is not None:
            out_png = save_dir_path / f"boxplot_{band.replace(' ', '_')}.png"
            save_figure(fig, out_png, dpi=150)
        else:
            plt.show()

    return save_dir_path


def plot_climate_mean_maps(workdir, watershed_shp=None, save_dir=None, dem_path=None, snap_m=25.0):
    workdir = Path(workdir)
    save_dir_path = ensure_dir(save_dir) if save_dir is not None else None

    if watershed_shp is None:
        watershed_shp = workdir.parent / "results_stable" / "geographic" / "watershed.shp"
    watershed_shp = Path(watershed_shp)

    border = None
    if watershed_shp.exists():
        border = gpd.read_file(watershed_shp)

    for band, filename in CLIMATE_INPUT_STEMS.items():
        csv_path = workdir / filename
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path, header=None)

        lat_row = np.where(df.iloc[:, 0].astype(str).str.strip().str.lower() == "latitude")[0][0]
        lon_row = np.where(df.iloc[:, 0].astype(str).str.strip().str.lower() == "longitude")[0][0]
        data_start_row = max(lat_row, lon_row) + 1

        lats = pd.to_numeric(df.iloc[lat_row, 1:], errors="coerce").to_numpy()
        lons = pd.to_numeric(df.iloc[lon_row, 1:], errors="coerce").to_numpy()
        data = df.iloc[data_start_row:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy()

        values = np.nanmean(data, axis=0)

        if band == "precipitation":
            values = values * 365
            unit = "mm/year"
            stem = "precip"
        elif band == "air_temperature":
            unit = "°C"
            stem = "air temperature"
        elif band == "solar radiation":
            unit = "MJ/m²"
            stem = "solar_radiation"
        else:
            unit = CLIMATE_BANDS_UNITS.get(band, "")
            stem = band.replace(" ", "_")

        valid = np.isfinite(lats) & np.isfinite(lons) & np.isfinite(values)
        lats = lats[valid]
        lons = lons[valid]
        values = values[valid]

        target_crs = "EPSG:3035"
        transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
        xs, ys = transformer.transform(lons, lats)

        xs = (np.asarray(xs) / snap_m).round() * snap_m
        ys = (np.asarray(ys) / snap_m).round() * snap_m

        pts_df = pd.DataFrame({"x": xs, "y": ys, "value": values})
        agg = pts_df.groupby(["x", "y"], as_index=False)["value"].mean()

        x_unique = np.sort(agg["x"].unique())
        y_unique = np.sort(agg["y"].unique())

        dx = float(np.median(np.diff(x_unique)))
        dy = float(np.median(np.diff(y_unique)))

        xmin = float(x_unique.min() - dx / 2.0)
        xmax = float(x_unique.max() + dx / 2.0)
        ymin = float(y_unique.min() - dy / 2.0)
        ymax = float(y_unique.max() + dy / 2.0)

        ncol = x_unique.size
        nrow = y_unique.size
        arr = np.full((nrow, ncol), np.nan, dtype=np.float32)

        y_to_i = {float(v): i for i, v in enumerate(y_unique[::-1])}
        x_to_j = {float(v): j for j, v in enumerate(x_unique)}

        for _, row in agg.iterrows():
            i = y_to_i[float(row["y"])]
            j = x_to_j[float(row["x"])]
            arr[i, j] = float(row["value"])
            
        # yy, xx = np.indices(arr.shape)
        
        # known = np.isfinite(arr)
        # missing = ~known
        
        # if np.any(missing) and np.any(known):
        #     points = np.column_stack((xx[known], yy[known]))
        #     values_known = arr[known]
        #     points_missing = np.column_stack((xx[missing], yy[missing]))
        
        #     arr[missing] = griddata(points, values_known, points_missing, method="nearest")

        transform = from_origin(xmin, ymax, dx, dy)
        ref = RasterRef(crs=target_crs, transform=transform, height=arr.shape[0], width=arr.shape[1])

        hillshade_show = None
        hillshade_transform = None

        if dem_path is not None:
            bbox = gpd.GeoDataFrame({"id": [1]}, geometry=[box(xmin, ymin, xmax, ymax)], crs=target_crs)

            with tempfile.TemporaryDirectory() as td:
                bbox_path = Path(td) / "climate_bbox.gpkg"
                bbox.to_file(bbox_path, driver="GPKG")

                hillshade_show, hillshade_transform = compute_hillshade(
                    dem_path=dem_path,
                    clip_shp=str(bbox_path),
                    ref=ref,
                    azdeg=135.0,
                    altdeg=45.0,
                    vert_exag=2.0,
                    smooth_sigma=1.0,
                )

        print(f"{band}: min={np.nanmin(values):.3f}, max={np.nanmax(values):.3f}, mean={np.nanmean(values):.3f}")

        save_stack_pngs(
            out_dir=save_dir_path,
            stem=stem,
            stack=arr[None, ...],
            ref=ref,
            border=border,
            glaciers=None,
            hillshade=hillshade_show,
            fill_missing=False,
            hillshade_transform=hillshade_transform,
            hillshade_alpha=1.0,
            overlay_alpha=0.55,
            glaciers_alpha=1.0,
            qmin=0.10,
            qmax=0.90,
        )

    return save_dir_path

__all__ = [
    "CLIMATE_BANDS_UNITS",
    "CLIMATE_INPUT_STEMS",
    "plot_climate_timeseries",
    "plot_climate_timeseries_batch",
    "plot_climate_boxplots",
    "plot_climate_mean_maps",
]


if __name__ == "__main__":
    
    plot_climate_mean_maps(
        workdir='C:/Users/Pelissierm/Waterwise/HDPY_models/_rech/results_pyhelp',
        watershed_shp="Z:/HDPY_outputs/historic/_rech/results_stable/geographic/watershed.shp",
        save_dir="Z:/HDPY_outputs/historic/_rech/results_pyhelp/climate_mean_map",
        dem_path="Z:/HDPY_database_forModelling/PyHELP_rasters/eu_dem_eusalp.tif",
        snap_m=25.0,
    )