from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import griddata

from waterwise.plots.plots_common import save_figure

REF = (2010, 2025)
FUT = (2075, 2100)
VARS = {"runoff": "runoff", "evapo": "evapo", "rechg": "rechg"}
THR = {"runoff": 1e-2, "evapo": 1e-3, "rechg": 1e-2}
CLIM = {"runoff": (-70, 70), "evapo": (-25, 25), "rechg": (-20, 20)}
FIGSIZE = (8, 6)
NX, NY = 320, 220
ZOOM = 0.02


def load_out(out_file):
    with h5py.File(out_file, "r") as f:
        return {k: f["data"][k][:] for k in f["data"].keys()}


def mean_period(data, var, period):
    years = data["years"].astype(int)
    mask = (years >= period[0]) & (years <= period[1])
    return np.nanmean(data[var][:, mask, :], axis=(1, 2))


def calc_anomaly(vref, vfut, thr):
    return (vfut - vref) / vref * 100.0


def get_dynamic_clim(z, q=98, min_span=10):
    z = np.asarray(z, dtype=float)
    z = z[np.isfinite(z)]
    if z.size == 0:
        return (-min_span, min_span)

    vmax = np.nanpercentile(np.abs(z), q)
    vmax = max(float(vmax), float(min_span))
    return (-vmax, vmax)


def prepare_geometry(lon, lat):
    lon0, lat0 = lon.mean(), lat.mean()
    x = (lon - lon0) * 111320.0 * np.cos(np.deg2rad(lat0))
    y = (lat - lat0) * 110540.0

    pts = np.c_[x, y]
    center = pts.mean(0)
    pts0 = pts - center

    w, v = np.linalg.eigh(np.cov(pts0.T))
    theta = np.arctan2(v[:, np.argmax(w)][1], v[:, np.argmax(w)][0])

    c, s = np.cos(-theta), np.sin(-theta)
    R = np.array([[c, -s], [s, c]])
    pr = pts0 @ R.T
    xr, yr = pr[:, 0], pr[:, 1]

    flip_x = np.corrcoef(xr, lon)[0, 1] < 0
    flip_y = np.corrcoef(yr, lat)[0, 1] < 0
    if flip_x:
        xr = -xr
    if flip_y:
        yr = -yr

    return {"lon0": lon0, "lat0": lat0, "center": center, "R": R, "flip_x": flip_x, "flip_y": flip_y, "xr": xr, "yr": yr}


def project_coords(lon, lat, geom):
    x = (np.asarray(lon) - geom["lon0"]) * 111320.0 * np.cos(np.deg2rad(geom["lat0"]))
    y = (np.asarray(lat) - geom["lat0"]) * 110540.0
    pr = (np.c_[x, y] - geom["center"]) @ geom["R"].T
    xr, yr = pr[:, 0], pr[:, 1]
    if geom["flip_x"]:
        xr = -xr
    if geom["flip_y"]:
        yr = -yr
    return xr, yr


def rasterize(x, y, z, nx=NX, ny=NY):
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    xi = np.linspace(x[m].min(), x[m].max(), nx)
    yi = np.linspace(y[m].min(), y[m].max(), ny)
    XI, YI = np.meshgrid(xi, yi)
    ZI = griddata((x[m], y[m]), z[m], (XI, YI), method="nearest")
    return xi, yi, ZI


def add_basin(ax, basin_shp, geom):
    gdf = gpd.read_file(basin_shp)
    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")

    for g in gdf.geometry:
        geoms = [g] if g.geom_type == "Polygon" else list(g.geoms) if g.geom_type == "MultiPolygon" else []
        for poly in geoms:
            bx, by = project_coords(*poly.exterior.xy, geom)
            ax.plot(bx, by, color="k", lw=1)


def format_axes(ax, xr, yr, lon, lat, zoom=ZOOM):
    ax.set_xticks(np.linspace(xr.min(), xr.max(), 5))
    ax.set_yticks(np.linspace(yr.min(), yr.max(), 5))
    ax.set_xticklabels([f"{v:.2f}" for v in np.linspace(lon.min(), lon.max(), 5)])
    ax.set_yticklabels([f"{v:.2f}" for v in np.linspace(lat.min(), lat.max(), 5)])

    dx, dy = xr.max() - xr.min(), yr.max() - yr.min()
    ax.set_xlim(xr.min() + zoom * dx, xr.max() - zoom * dx)
    ax.set_ylim(yr.min() + zoom * dy, yr.max() - zoom * dy)
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")


def anomaly_maps(out_file, outdir, basin_shp, scenario_name=None, ref=REF, fut=FUT, vars_map=VARS, thr=THR, clim=CLIM, nx=NX, ny=NY, zoom=ZOOM):
    data = load_out(out_file)
    lon = data["lon_dd"].astype(float)
    lat = data["lat_dd"].astype(float)
    geom = prepare_geometry(lon, lat)

    outdir = Path(outdir)
    outdir.mkdir(exist_ok=True)
    scenario_name = scenario_name or Path(out_file).parent.name

    for label, var in vars_map.items():
        vref = mean_period(data, var, ref)
        vfut = mean_period(data, var, fut)
        z = calc_anomaly(vref, vfut, thr[label])
        xi, yi, zi = rasterize(geom["xr"], geom["yr"], z, nx=nx, ny=ny)

        if label == "evapo":
            vmin, vmax = get_dynamic_clim(z, q=98, min_span=5)
        else:
            vmin, vmax = clim[label]

        fig, ax = plt.subplots(figsize=FIGSIZE)
        im = ax.imshow(zi, origin="lower", extent=[xi.min(), xi.max(), yi.min(), yi.max()], cmap="RdBu", vmin=vmin, vmax=vmax, interpolation="nearest", aspect="equal")
        add_basin(ax, basin_shp, geom)
        format_axes(ax, geom["xr"], geom["yr"], lon, lat, zoom=zoom)
        plt.colorbar(im, ax=ax, label="anomaly [%]")
        ax.set_title(f"{label} anomaly (%)\n{scenario_name} {fut[0]}-{fut[1]}")
        plt.tight_layout()
        save_figure(fig, outdir / f"{scenario_name}_{label}_anomaly.png", dpi=300)


def classification_plot(path):
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(5, 7))
    dL = df[df["family"] == "L"]
    dS = df[df["family"] == "S"]
    dC = df[df["family"] == "C"]

    ax.plot(dL["dP_DJF"], dL["dP_JJA"], 'o', label="Limitée")
    ax.plot(dS["dP_DJF"], dS["dP_JJA"], 'd', label="Sèche")
    ax.plot(dC["dP_DJF"], dC["dP_JJA"], 's', label="Contrastée")

    for _, row in dL.iterrows():
        ax.annotate(row["model"], (row["dP_DJF"], row["dP_JJA"]))
    for _, row in dS.iterrows():
        ax.annotate(row["model"], (row["dP_DJF"], row["dP_JJA"]))
    for _, row in dC.iterrows():
        ax.annotate(row["model"], (row["dP_DJF"], row["dP_JJA"]))

    ax.set_xlabel("Ecart relatif DJF (%)")
    ax.set_ylabel("Ecart relatif JJA (%)")
    fig.legend(loc="outside right upper")
    plt.show()


__all__ = [
    "REF",
    "FUT",
    "VARS",
    "THR",
    "CLIM",
    "anomaly_maps",
    "classification_plot",
]


if __name__ == "__main__":
    
    out_file=Path('Z:/HDPY_outputs/prediction/peca/_CESM2/help_example.out')
    outdir=Path('Z:/HDPY_outputs/prediction/peca/_CESM2/plots_pyhelp')
    basin_shp=Path('C:/Users/Pelissierm/Waterwise/HDPY_models/_peca/results_stable/geographic/watershed.shp')
    classification=Path('Z:/HDPY_database_forModelling/_climate/_merged_projection_and_historic/climate_narratives/climate_metrics_with_families.csv')
    
    classification_plot(classification)
    #anomaly_maps(out_file, outdir, basin_shp, scenario_name=None, ref=REF, fut=FUT, vars_map=VARS, thr=THR, clim=CLIM, nx=NX, ny=NY, zoom=ZOOM)