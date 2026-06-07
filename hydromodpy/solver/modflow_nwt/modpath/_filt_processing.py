"""Filtering and weighted-flux post-processing for MODPATH outputs."""

from __future__ import annotations

import json
import os
import random
from typing import Any

import flopy.utils.postprocessing as pp
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from scipy.optimize import curve_fit

from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.core.logging import get_logger

from ._resolvers import (
    crs_for_write_from_proj,
    resolve_domain_raster,
    resolve_watershed_shp,
)

logger = get_logger(__name__)


def filter_pathlines(
    *,
    modpath_runner: Any,
    model_modpath: Any,
    norm_flux: bool,
    filt_time: bool,
    filt_seep: bool,
    filt_inout: bool,
    calc_rtd: bool,
    random_id: int | None,
) -> None:
    """Apply weight, filter and RTD steps on the MODPATH shapefile outputs."""
    full_path = os.path.join(model_modpath.model_folder, model_modpath.model_name)
    particles_file = os.path.join(full_path, "_postprocess", "_particles")
    modpath_runner.full_path = full_path
    modpath_runner.particles_file = particles_file

    crs = model_modpath._get_crs_proj()
    crs_for_write, _ = crs_for_write_from_proj(crs)

    track_dir = modpath_runner.track_dir
    model_name = model_modpath.model_name

    if norm_flux:
        keep_particles = _build_weighted_outputs(
            modpath_runner=modpath_runner,
            model_modpath=model_modpath,
            full_path=full_path,
            particles_file=particles_file,
            crs_for_write=crs_for_write,
            filt_time=filt_time,
            filt_seep=filt_seep,
            filt_inout=filt_inout,
            random_id=random_id,
            track_dir=track_dir,
        )
        _ = keep_particles  # kept for trace symmetry; downstream filters now consume shapefiles

    if calc_rtd:
        _compute_residence_time_distribution(
            modpath_runner=modpath_runner,
            model_name=model_name,
            track_dir=track_dir,
            crs_for_write=crs_for_write,
        )


def _ensure_crs(gdf: gpd.GeoDataFrame, crs_for_write: object | None) -> gpd.GeoDataFrame:
    """Attach CRS when missing to avoid warnings and mismatches."""
    if gdf.crs is None and crs_for_write is not None:
        return gdf.set_crs(crs_for_write, allow_override=True)
    return gdf


def _sample_raster_values_at_points(raster_path: str, points_gdf: gpd.GeoDataFrame) -> np.ndarray:
    """Sample raster at point locations without rewriting input shapefiles."""
    sampled = np.full(len(points_gdf), np.nan, dtype=float)
    if points_gdf.empty:
        return sampled

    coords: list[tuple[float, float]] = []
    valid_idx: list[int] = []
    for idx, geom in enumerate(points_gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        coords.append((geom.x, geom.y))
        valid_idx.append(idx)

    if len(coords) == 0:
        return sampled

    with rasterio.open(raster_path) as src:
        values = np.array([val[0] for val in src.sample(coords)], dtype=float)
        nodata = src.nodata

    if nodata is not None:
        values[values == nodata] = np.nan

    sampled[np.asarray(valid_idx, dtype=int)] = values
    return sampled


def _update_time(df: gpd.GeoDataFrame, filt_time: bool) -> gpd.GeoDataFrame:
    """Convert tracking days to years and drop zero-time rows when requested."""
    if filt_time:
        df["time_y"] = df["time"] / 365
        try:
            df["time_win_y"] = df["time_win"] / 365
        except Exception:
            logger.debug("Failed to convert 'time_win' to years", exc_info=True)
        df = df[df["time"] > 0]
    return df


def _update_locout(
    df: gpd.GeoDataFrame,
    *,
    filt_seep: bool,
    filt_inout: bool,
    track_dir: str,
):
    """Keep particles ending in seepage and remove same-cell in/out."""
    if filt_seep and track_dir == "forward":
        df = df[df["k"] <= 1]
        df = df[df["zone"] == 1]
    if filt_inout:
        df = df[
            df.i0.astype(str) + "-" + df.j0.astype(str) != df.i.astype(str) + "-" + df.j.astype(str)
        ]
    keep_particles = df["particleid"]
    return df, keep_particles


def _build_weighted_outputs(
    *,
    modpath_runner: Any,
    model_modpath: Any,
    full_path: str,
    particles_file: str,
    crs_for_write: object | None,
    filt_time: bool,
    filt_seep: bool,
    filt_inout: bool,
    random_id: int | None,
    track_dir: str,
) -> Any:
    """Compute recharge-weighted shapefiles and write filtered exports."""
    modeldir = full_path + "/"
    namepath = model_modpath.model_name
    model_name = model_modpath.model_name
    mymodel = model_modpath.mf
    aux_rech = mymodel.get_package("RCH")
    mymodel.get_package("BAS6")
    mydis = mymodel.get_package("DIS")
    dcol = np.unique(mydis.delc)[0]
    drow = np.unique(mydis.delr)[0]
    period = 0
    step = 0

    Qx, Qy, Qz_rech = pp.get_extended_budget(
        modeldir + namepath + ".cbc",
        precision="single",
        idx=None,
        kstpkper=(step, period),
        totim=None,
        boundary_ifaces={"RECHARGE": 6},
        hdsfile=modeldir + namepath + ".hds",
        model=mymodel,
    )
    Qx_2, Qy_2, Qz_drain = pp.get_extended_budget(
        modeldir + namepath + ".cbc",
        precision="single",
        idx=None,
        kstpkper=(step, period),
        totim=None,
        boundary_ifaces={"DRAINS": 6},
        hdsfile=modeldir + namepath + ".hds",
        model=mymodel,
    )
    _ = (Qx, Qy, Qx_2, Qy_2)  # silence: original kept for parity

    recharge_raw = aux_rech.rech.array[0, 0]
    recharge_list = recharge_raw.flatten()
    recharge_matrix = recharge_raw * dcol * drow
    drain_matrix = Qz_drain[0, :, :]
    sflux = recharge_matrix - drain_matrix
    sflows = sflux / drow / dcol

    sflows_tif = os.path.join(particles_file, "sflows_weighted.tif")
    start_shp = os.path.join(particles_file, "starting.shp")
    end_shp = os.path.join(particles_file, "ending.shp")
    start_weighted_shp = os.path.join(particles_file, "starting_weighted.shp")
    end_weighted_shp = os.path.join(particles_file, "ending_weighted.shp")

    export_tif(resolve_domain_raster(model_modpath.model_modflow), sflows, sflows_tif, -9999)

    start = _ensure_crs(gpd.read_file(start_shp), crs_for_write)
    start_weighted = start.copy()
    start_weighted["VALUE1"] = _sample_raster_values_at_points(sflows_tif, start_weighted)
    start_weighted.to_file(start_weighted_shp)

    end = _ensure_crs(gpd.read_file(end_shp), crs_for_write)
    end_weighted = end.copy()
    end_weighted["VALUE1"] = _sample_raster_values_at_points(sflows_tif, end_weighted)
    end_weighted.to_file(end_weighted_shp)

    recharge_list = np.ones(len(end)) * recharge_raw.mean()

    start_process = _ensure_crs(gpd.read_file(start_weighted_shp), crs_for_write)
    end_process = _ensure_crs(gpd.read_file(end_weighted_shp), crs_for_write)

    if track_dir == "forward":
        end_process["VALUE1_in"] = start_weighted["VALUE1"]
        end_process["rchPerc"] = end_process["VALUE1_in"] / recharge_list
        end_process.loc[end_process["rchPerc"] < 0, "rchPerc"] = 0
        time_win = end_process["time"] * end_process["rchPerc"]
    else:
        start_process["VALUE1_in"] = end_weighted["VALUE1"]
        start_process["rchPerc"] = start_process["VALUE1_in"] / recharge_list
        start_process.loc[start_process["rchPerc"] < 0, "rchPerc"] = 0
        time_win = start_process["time"] * start_process["rchPerc"]

    start_process["time_win"] = time_win
    end_process["time_win"] = time_win

    end_up = _update_time(end_process, filt_time)
    end_up, keep_particles = _update_locout(
        end_up,
        filt_seep=filt_seep,
        filt_inout=filt_inout,
        track_dir=track_dir,
    )
    end_up = _ensure_crs(end_up, crs_for_write)
    end_up.to_file(
        os.path.join(
            modpath_runner.model_folder,
            model_name,
            "_postprocess",
            "_particles",
            "ending_weighted.shp",
        )
    )

    start_up = _update_time(start_process, filt_time)
    start_up, keep_particles = _update_locout(
        start_up,
        filt_seep=filt_seep,
        filt_inout=filt_inout,
        track_dir=track_dir,
    )
    start_up = _ensure_crs(start_up, crs_for_write)
    start_up.to_file(
        os.path.join(
            modpath_runner.model_folder,
            model_name,
            "_postprocess",
            "_particles",
            "starting_weighted.shp",
        )
    )

    if modpath_runner.pathlines_shp:
        _write_weighted_pathlines(
            modpath_runner=modpath_runner,
            model_name=model_name,
            crs_for_write=crs_for_write,
            end_process=end_process,
            start_process=start_process,
            track_dir=track_dir,
            filt_time=filt_time,
            keep_particles=keep_particles,
            random_id=random_id,
        )

    if modpath_runner.particles_shp:
        _write_weighted_particles(
            modpath_runner=modpath_runner,
            model_name=model_name,
            crs_for_write=crs_for_write,
            filt_time=filt_time,
            random_id=random_id,
        )
    return keep_particles


def _write_weighted_pathlines(
    *,
    modpath_runner: Any,
    model_name: str,
    crs_for_write: object | None,
    end_process,
    start_process,
    track_dir: str,
    filt_time: bool,
    keep_particles,
    random_id: int | None,
) -> None:
    pathlines_process = _ensure_crs(
        gpd.read_file(
            os.path.join(
                modpath_runner.model_folder,
                model_name,
                "_postprocess",
                "_particles",
                "pathlines.shp",
            )
        ),
        crs_for_write,
    )
    if track_dir == "forward":
        pathlines_process["time_win"] = end_process["time"] * end_process["rchPerc"]
    else:
        pathlines_process["time_win"] = start_process["time"] * start_process["rchPerc"]
    pathlines_up = _update_time(pathlines_process, filt_time)
    pathlines_up = pathlines_up[pathlines_up["particleid"].isin(keep_particles)]

    random_data_file = os.path.join(modpath_runner.model_folder, "_id_particles_random.json")
    if random_id is not None:
        if not os.path.exists(random_data_file):
            id_particles_random = random.sample(pathlines_up[:-1], random_id)
            with open(random_data_file, "w") as f:
                json.dump([int(x) for x in id_particles_random], f)
        else:
            with open(random_data_file) as f:
                id_particles_random = json.load(f)
        pathlines_up = pathlines_up[pathlines_up["particleid"].isin(id_particles_random)]
    pathlines_up = _ensure_crs(pathlines_up, crs_for_write)
    pathlines_up.to_file(
        os.path.join(
            modpath_runner.model_folder,
            model_name,
            "_postprocess",
            "_particles",
            "pathlines_weighted.shp",
        )
    )


def _write_weighted_particles(
    *,
    modpath_runner: Any,
    model_name: str,
    crs_for_write: object | None,
    filt_time: bool,
    random_id: int | None,
) -> None:
    particles_process = _ensure_crs(
        gpd.read_file(
            os.path.join(
                modpath_runner.model_folder,
                model_name,
                "_postprocess",
                "_particles",
                "particles.shp",
            )
        ),
        crs_for_write,
    )
    particles_up = _update_time(particles_process, filt_time)
    random_data_file = os.path.join(modpath_runner.model_folder, "_id_particles_random.json")
    if random_id is not None:
        if not os.path.exists(random_data_file):
            id_particles_random = random.sample(particles_up[:-1], random_id)
            with open(random_data_file, "w") as f:
                json.dump([int(x) for x in id_particles_random], f)
        else:
            with open(random_data_file) as f:
                id_particles_random = json.load(f)
        particles_up = particles_up[particles_up["particleid"].isin(id_particles_random)]
    particles_up = _ensure_crs(particles_up, crs_for_write)
    particles_up.to_file(
        os.path.join(
            modpath_runner.model_folder,
            model_name,
            "_postprocess",
            "_particles",
            "particles_weighted.shp",
        )
    )


def _compute_residence_time_distribution(
    *,
    modpath_runner: Any,
    model_name: str,
    track_dir: str,
    crs_for_write: object | None,
) -> None:
    """Estimate the weighted residence time distribution and a polynomial fit."""
    if track_dir == "forward":
        end = _ensure_crs(
            gpd.read_file(
                os.path.join(
                    modpath_runner.model_folder,
                    model_name,
                    "_postprocess",
                    "_particles",
                    "ending_weighted.shp",
                )
            ),
            crs_for_write,
        )
    else:
        end = _ensure_crs(
            gpd.read_file(
                os.path.join(
                    modpath_runner.model_folder,
                    model_name,
                    "_postprocess",
                    "_particles",
                    "starting_weighted.shp",
                )
            ),
            crs_for_write,
        )
    try:
        watershed_shp = resolve_watershed_shp(modpath_runner.model_modflow)
        if watershed_shp is not None:
            shp = gpd.read_file(watershed_shp)
            end = end.clip(shp)
    except Exception:
        logger.debug("Failed to clip particles to watershed boundary", exc_info=True)
    end.loc[end["time_win"] == 0, :] = np.nan
    end = end.dropna()

    try:
        tau = np.average(end["time_win"], weights=end["rchPerc"])
        nbin = int(2 * len(end["time_win"]) ** (2 / 5))
        xh, yh = _pdf_function(end["time_win"] / tau, nbin, end.rchPerc)
        idzeros = np.where(yh != 0)
        xfil = xh[idzeros]
        yfil = yh[idzeros]
        x_log = np.log10(xfil)
        y_log = np.log10(yfil)
    except Exception:
        logger.debug("Failed to compute log-scale residence time bins", exc_info=True)
        return

    try:
        params, _covariance = curve_fit(_quartic, x_log, y_log)
        a, b, c, d, e = params
        x_fit = np.linspace(min(x_log), max(x_log), 100)
        y_fit = _quartic(x_fit, a, b, c, d, e)

        fig = plt.figure(figsize=(6, 4))
        ax = fig.add_subplot(111)
        ax.plot(xfil, yfil, "-", lw=2, c="red", label="Binning on particles")
        ax.plot(xh, yh, marker="o", markeredgecolor="none", lw=0, c="red")
        ax.plot(10**x_fit, 10**y_fit, "-", lw=2, c="k", label="Fitting curve")
        ax.set_ylabel("PDF")
        ax.set_xlabel("t / " + r"$\tau$")
        ax.set_xscale("log")
        ax.set_title("Residence times distribution")
        ax.legend(loc="upper right")
    except Exception:
        logger.debug("Failed to fit and plot residence time distribution curve", exc_info=True)


def _pdf_function(
    values: np.ndarray, nbin: int, weight: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    bin_min = np.quantile(values, 0.01)
    bin_max = np.quantile(values, 0.99)
    bins = np.logspace(np.log10(bin_min), np.log10(bin_max), nbin)
    pdf, bin_edges = np.histogram(values, bins=bins, density=True, weights=weight)
    xh = (bin_edges[1:] + bin_edges[:-1]) / 2
    return np.array(xh), pdf


def _quartic(x: np.ndarray, a: float, b: float, c: float, d: float, e: float) -> np.ndarray:
    return a * x**4 + b * x**3 + c * x**2 + d * x + e
