# -*- coding: utf-8 -*-
"""
Created on Mon Mar 23 11:56:46 2026

@author: pelissierm
"""

from pathlib import Path
import numpy as np
import pandas as pd
import h5py


def _param_stats(workdir):
    path = Path(workdir) / "input_grid.csv"

    df = pd.read_csv(path)
    df = df.select_dtypes(include=[np.number])

    return pd.DataFrame({"mean": df.mean(), "std": df.std(), "min": df.min(),  "max": df.max()}).T


def _climate_stats(workdir):
    files = ["precip_input_data.csv", "solrad_input_data.csv", "airtemp_input_data.csv"]
    out = {}

    for f in files:
        path = Path(workdir) / f
        if not path.exists():
            continue

        df = pd.read_csv(path, header=None)
        data = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce").values.ravel()
        data = data[np.isfinite(data)]

        if data.size == 0:
            continue

        name = f.split("_")[0]
        out[name] = [data.mean(), data.std(), data.min(), data.max()]

    if not out:
        return None

    return pd.DataFrame(out, index=["mean", "std", "min", "max"])


def _pyhelp_stats(workdir):
    files = list(Path(workdir).glob("*.out")) + \
            list(Path(workdir).glob("*.h5")) + \
            list(Path(workdir).glob("*.hdf5"))

    if not files:
        return None

    fpath = files[0]

    with h5py.File(fpath, "r") as h5:
        if "data" not in h5:
            return None

        g = h5["data"]
        years = g["years"][:] if "years" in g else None

        vars_ = ["precip", "evapo", "runoff", "subrun1", "subrun2", "rechg", "perco"]

        stats = {}
        trends = {}

        for v in vars_:
            if v not in g:
                continue

            arr = g[v][:]
            flat = arr.ravel()
            flat = flat[np.isfinite(flat)]

            if flat.size == 0:
                continue

            stats[v] = [flat.mean(), flat.std(), flat.min(), flat.max()]

            # trend mm/decade
            if years is not None:
                if arr.ndim == 3:
                    annual = np.nansum(arr, axis=2)
                    series = np.nanmean(annual, axis=0)
                elif arr.ndim == 2:
                    series = np.nanmean(arr, axis=0)
                else:
                    series = arr

                mask = np.isfinite(series)
                if mask.sum() > 1:
                    slope = np.polyfit(years[mask], series[mask], 1)[0]
                    trends[v] = slope * 10.0
                else:
                    trends[v] = np.nan
            else:
                trends[v] = np.nan

    if not stats:
        return None

    df = pd.DataFrame(stats, index=["mean", "std", "min", "max"])
    df.loc["trend_mm_decade"] = pd.Series(trends)

    return df


def write_historical_stats_csv(workdir, out_csv=None, logger=None):
    workdir = Path(workdir)
    out_csv = Path(out_csv) if out_csv else workdir / "pyhelp_historical_stats.csv"

    with open(out_csv, "w") as f:
        f.write("### block historical\n")

        p = _param_stats(workdir)
        if p is not None:
            f.write("### section param\n")
            f.write(p.to_csv())

        c = _climate_stats(workdir)
        if c is not None:
            f.write("\n### section climate\n")
            f.write(c.to_csv())

        h = _pyhelp_stats(workdir)
        if h is not None:
            f.write("\n### section pyhelp\n")
            f.write(h.to_csv())

    if logger:
        logger.info(f"[stats] wrote {out_csv}")

    return out_csv


def write_prediction_stats_csv(model_dir, out_csv=None, logger=None):
    model_dir = Path(model_dir)

    if not model_dir.exists():
        return None

    out_files = list(model_dir.glob("*.out"))
    if not out_files:
        if logger:
            logger.info(f"[stats] no .out file in {model_dir}")
        return None

    pyhelp_output = out_files[0]

    out_csv = Path(out_csv) if out_csv else model_dir / "pyhelp_prediction_stats.csv"

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        f.write("### block prediction\n")

        # param
        if (model_dir / "input_grid.csv").exists():
            p = _param_stats(model_dir)
            f.write("### section param\n")
            f.write(p.to_csv())

        # climate
        c = _climate_stats(model_dir)
        if c is not None:
            f.write("\n### section climate\n")
            f.write(c.to_csv())

        # pyhelp
        h = _pyhelp_stats(pyhelp_output)
        if h is not None:
            f.write("\n### section pyhelp\n")
            f.write(h.to_csv())

    if logger:
        logger.info(f"[stats] wrote {out_csv}")

    return out_csv